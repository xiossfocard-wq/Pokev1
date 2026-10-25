"""
Construction et interrogation de l'index local de prix de reference.

Deux responsabilites :
1. SYNCHRONISATION (`sync_series_batch`) : remplit `market_card_prices`
   depuis ZebraDex, de facon PROGRESSIVE. Les 158 series ne sont pas
   telechargees d'un coup (ce serait ~17 min de requetes a 6s d'intervalle,
   incompatible avec un hebergement gratuit et peu respectueux du site) :
   on synchronise `batch_size` series par cycle, en priorisant celles
   jamais vues puis les plus anciennes. Avec un cycle toutes les 20 min et
   un batch de 6, l'index complet est construit en ~10h puis rafraichi en
   continu. Le dashboard reste utilisable pendant la construction : les
   series deja synchronisees servent immediatement.

2. MATCHING (`find_price_for_listing`) : retrouve le prix d'une annonce a
   partir de son titre. Strategie en cascade, du plus fiable au moins
   fiable, car un titre Vinted est souvent approximatif :
     a. code carte exact present dans le titre (ex "PAF 232") -> tres fiable
     b. nom de carte (groupe de mots le plus specifique d'abord, ex
        "epine-de-fer" avant "epine"), affine par le numero de set quand il
        est present -> fiable
     c. nom de carte seul, avec desambiguisation par prix median si
        plusieurs series portent ce nom -> peu fiable
     d. rattrapage d'une faute de frappe probable -> peu fiable

   Chaque niveau tient en UNE requete SQL (`IN (...)`), pas une par
   candidat : sur Neon chaque aller-retour coute ~100 ms et un titre peut
   produire des dizaines de candidats.

   Le niveau de confiance est renvoye ET affiche dans l'UI, avec le nombre
   de cartes homonymes departagees et l'ecart de prix entre elles : un prix
   median calcule entre 3 EUR et 250 EUR ne doit pas s'afficher avec le
   meme aplomb qu'un prix sur.
"""
import difflib
import logging
import re

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.collectors.zebradex_prices import ZebraDexClient
from app.collectors.cardlist_fr import rang_de_parallele
from app.matching.title_parser import (
    NAME_SUFFIXES, extract_card_codes, extract_name_candidates,
    extract_set_number, extract_variant,
)
from app.models import MarketCardPrice, ZebraDexSeriesState
from app.services.card_themes import (
    cle_de_recherche, encoder_themes, themes_de_la_carte,
)

logger = logging.getLogger(__name__)

_client = ZebraDexClient()

# --- Rattrapage des fautes de frappe -------------------------------------
# Similarite minimale pour accepter une correction, longueur minimale du
# nom teste, et nombre de candidats essayes. Regles volontairement severes :
# un faux prix de reference est plus nuisible qu'une absence de prix.
FUZZY_MIN_RATIO = 0.80
FUZZY_MIN_LENGTH = 5
FUZZY_MAX_TRIES = 8
# Ecart de longueur tolere. "zorro" -> "zoro" (1 lettre) : oui.
# "luffy" -> "luffy-leader" (7 caracteres) : non, ce sont deux cartes
# differentes, pas une faute de frappe.
FUZZY_MAX_LENGTH_DELTA = 2

# --- Rattrapage du nom usuel ---------------------------------------------
# One Piece indexe ses cartes sous le nom COMPLET du personnage
# (« Monkey D. Luffy », « Portgas D. Ace », « Charlotte Katakuri ») alors
# que les vendeurs ecrivent le nom usuel : « Luffy », « Ace », « Katakuri ».
# Sans ce rattrapage, la majorite des annonces du jeu ne trouvaient AUCUN
# prix de reference, le nom complet n'apparaissant presque jamais dans un
# titre Vinted.
#
# La regle est volontairement etroite : le candidat doit etre la FIN du nom
# indexe, sur des mots entiers. « luffy » retrouve « monkey-d-luffy », et
# « luffy-leader » retrouve « monkey-d-luffy-leader ». L'inverse — un
# candidat qui serait le DEBUT du nom indexe — ne correspond a rien
# d'observe : personne n'ecrit « Monkey » pour designer Luffy.
PARTIEL_MIN_LENGTH = 3
# Au-dela, le nom est trop porte pour qu'une mediane veuille dire quelque
# chose : mieux vaut aucun prix qu'un chiffre tire de trente cartes allant
# de 2 a 400 EUR.
PARTIEL_MAX_CARTES = 12

# La liste des noms connus est relue au plus toutes les 15 min : l'index
# grossit lentement (6 series par cycle de 20 min) et la relire pour chaque
# annonce couterait une requete lourde a chaque fois.
SLUG_CACHE_MAX_AGE = timedelta(minutes=15)
_slug_cache: List[str] = []
_slug_cache_at: Optional[datetime] = None

# --------------------------------------------------------------------------
# Synchronisation
# --------------------------------------------------------------------------

def refresh_series_catalog(db: Session) -> int:
    """Decouvre/actualise la liste des series (aucune config manuelle)."""
    series_list = _client.discover_series()
    if not series_list:
        logger.warning("ZebraDex: catalogue de series vide, rien a mettre a jour")
        return 0

    added = 0
    for s in series_list:
        existing = db.query(ZebraDexSeriesState).filter_by(series_id=s.series_id).first()
        if existing:
            existing.name, existing.code, existing.bloc, existing.url = s.name, s.code, s.bloc, s.url
        else:
            db.add(ZebraDexSeriesState(
                series_id=s.series_id, name=s.name, code=s.code, bloc=s.bloc, url=s.url,
            ))
            added += 1
    db.commit()
    logger.info("ZebraDex: %d series au catalogue (%d nouvelles)", len(series_list), added)
    return added


# Le catalogue des series n'etait redecouvert QUE lorsqu'il etait vide,
# c'est-a-dire une seule fois dans la vie de l'application. Les extensions
# sorties ensuite n'apparaissaient donc jamais : constate le 19/09/2026,
# trois series manquaient. Redecouverte quotidienne desormais.
CATALOG_REFRESH_INTERVAL = timedelta(hours=24)
_CATALOG_REFRESHED_KEY = "zebradex_catalog_refreshed_at"


def _catalog_needs_refresh(db: Session) -> bool:
    from app.models import AppSettings

    if db.query(ZebraDexSeriesState).count() == 0:
        return True
    row = db.query(AppSettings).filter_by(key=_CATALOG_REFRESHED_KEY).first()
    if row is None or not row.value:
        return True
    try:
        last = datetime.fromisoformat(str(row.value))
    except ValueError:
        return True
    return datetime.utcnow() - last > CATALOG_REFRESH_INTERVAL


def _mark_catalog_refreshed(db: Session) -> None:
    from app.models import AppSettings

    stamp = datetime.utcnow().isoformat()
    row = db.query(AppSettings).filter_by(key=_CATALOG_REFRESHED_KEY).first()
    if row is None:
        db.add(AppSettings(key=_CATALOG_REFRESHED_KEY, value=stamp))
    else:
        row.value = stamp
    db.commit()


def sync_series_batch(db: Session, batch_size: int = 6) -> dict:
    """
    Synchronise `batch_size` series : d'abord celles jamais synchronisees,
    puis les plus anciennes. Retourne un resume pour les logs / l'API admin.
    """
    if _catalog_needs_refresh(db):
        refresh_series_catalog(db)
        _mark_catalog_refreshed(db)

    pending = (
        db.query(ZebraDexSeriesState)
        .order_by(ZebraDexSeriesState.last_synced_at.asc().nullsfirst())
        .limit(batch_size)
        .all()
    )

    synced, total_cards = 0, 0
    for series in pending:
        cards = _client.fetch_series_cards(series.url, series_name=series.name)
        if not cards:
            series.last_error = "0 carte extraite"
            series.last_synced_at = datetime.utcnow()
            db.commit()
            continue

        for card in cards:
            _upsert_card_price(db, card)
        series.card_count = len(cards)
        series.last_synced_at = datetime.utcnow()
        series.last_error = None
        db.commit()
        synced += 1
        total_cards += len(cards)
        logger.info("ZebraDex: %s synchronisee (%d cartes)", series.name, len(cards))

    remaining = db.query(ZebraDexSeriesState).filter(
        ZebraDexSeriesState.last_synced_at.is_(None)
    ).count()
    return {
        "series_synced": synced,
        "cards_upserted": total_cards,
        "series_never_synced_remaining": remaining,
        "total_prices_in_index": db.query(MarketCardPrice).count(),
    }


def _upsert_card_price(db: Session, card) -> None:
    existing = (
        db.query(MarketCardPrice)
        .filter_by(card_code=card.card_code, name_slug=card.name_slug)
        .first()
    )
    values = dict(
        display_name=card.name,
        series_name=card.series_name,
        rarity=card.rarity,
        price_eur=card.price_eur,
        price_low_eur=card.price_low,
        price_high_eur=card.price_high,
        variation_7d_eur=card.variation_7d_eur,
        source="zebradex",
        updated_at=datetime.utcnow(),
        # Les themes sont recalcules a chaque passage plutot que figes a la
        # creation : les listes de card_themes.py evoluent, et une carte
        # synchronisee avant l'ajout d'un theme doit le rejoindre au
        # passage suivant sans intervention.
        theme_slugs=encoder_themes(themes_de_la_carte(card.name, card.rarity)),
        search_key=cle_de_recherche(card.name, card.card_code),
    )
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(MarketCardPrice(
            card_code=card.card_code, name_slug=card.name_slug, **values
        ))


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

class PriceMatch:
    def __init__(self, row: MarketCardPrice, confidence: str, reason: str,
                 candidates: Optional[List[MarketCardPrice]] = None,
                 warning: Optional[str] = None):
        self.row = row
        self.confidence = confidence  # "high" | "medium" | "low"
        self.reason = reason
        # Toutes les cartes qui portaient le meme nom. Sert a chiffrer
        # l'incertitude : si 10 cartes s'appellent "Monkey D. Luffy" et que leurs
        # prix vont de 3 a 230 EUR, le prix median retenu ne veut pas dire
        # grand-chose et l'utilisateur doit le savoir.
        self.candidates = candidates or [row]
        self.warning = warning

    @property
    def candidate_prices(self) -> List[float]:
        return [c.price_eur for c in self.candidates if c.price_eur is not None]

    @property
    def price_spread_eur(self) -> float:
        prices = self.candidate_prices
        if len(prices) < 2:
            return 0.0
        return round(max(prices) - min(prices), 2)

    @property
    def is_uncertain(self) -> bool:
        """Vrai quand le prix affiche ne doit PAS etre pris pour argent
        comptant : soit on a du departager plusieurs cartes homonymes aux
        prix tres differents, soit la variante annoncee ne correspond pas."""
        if self.warning:
            return True
        if self.confidence == "high":
            return False
        if len(self.candidates) < 2:
            return self.confidence == "low"
        # Ecart de plus de 50% du prix retenu entre les homonymes.
        return self.price_spread_eur > max(self.row.price_eur or 0.0, 1.0) * 0.5

    def to_dict(self) -> dict:
        return {
            "price_eur": self.row.price_eur,
            "price_low_eur": self.row.price_low_eur,
            "price_high_eur": self.row.price_high_eur,
            "variation_7d_eur": self.row.variation_7d_eur,
            "rarity": self.row.rarity,
            "series_name": self.row.series_name,
            "matched_card": self.row.display_name,
            "matched_code": self.row.card_code,
            # Identifiant de la carte retenue : c'est lui qui permet de
            # relier une annonce a sa fiche catalogue.
            "matched_card_id": self.row.id,
            "matched_name_slug": self.row.name_slug,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.row.source,
            "candidates_count": len(self.candidates),
            "price_spread_eur": self.price_spread_eur,
            # Bornes REELLES des cartes homonymes (a ne pas confondre avec
            # price_low_eur/price_high_eur, qui sont la volatilite 7 jours
            # d'UNE seule carte).
            "candidates_min_eur": round(min(self.candidate_prices), 2) if self.candidate_prices else None,
            "candidates_max_eur": round(max(self.candidate_prices), 2) if self.candidate_prices else None,
            "uncertain": self.is_uncertain,
            "warning": self.warning,
        }


def find_price_for_listing(db: Session, title: str, description: str = "") -> Optional[PriceMatch]:
    """
    Strategie en cascade, du plus fiable au moins fiable. Chaque niveau ne
    fait qu'UNE requete SQL (avec `IN (...)`) au lieu d'une par candidat :
    sur Neon chaque aller-retour coute ~100 ms, et un titre peut produire
    des dizaines de candidats.
    """
    text = f"{title or ''} {description or ''}"

    codes = extract_card_codes(text)
    names = extract_name_candidates(text)
    set_number = extract_set_number(text)
    variant = extract_variant(text)

    # (a) Code carte explicite : le rapprochement le plus sur.
    #
    # La variante lui est passee depuis le 20/10/2026. Avant, ce chemin
    # sortait sans la regarder, ce qui se tenait quand un code ne designait
    # qu'une carte. Depuis que le catalogue tient la liste officielle, un
    # code designe l'impression ordinaire ET son illustration alternative :
    # « Zoro parallele OP01-001 » tombait alors sur l'ordinaire, dont le prix
    # n'a rien a voir.
    # Le signalement d'une variante discordante est fait DANS la fonction,
    # qui seule sait si le code etait ambigu.
    match = _match_by_card_code(db, codes, variant)
    if match is not None:
        return match

    # (b) Nom (groupe de mots le plus specifique d'abord), affine par le
    # numero de set quand il est present.
    match = _match_by_name(db, names, set_number)
    if match is None:
        # (c) Nom usuel : le vendeur ecrit « Luffy », l'index contient
        # « Monkey D. Luffy ». Avant la faute de frappe, parce qu'une
        # correspondance exacte sur des mots entiers est une preuve plus
        # solide qu'une correction orthographique devinee.
        match = _match_by_partial_name(db, names)
    if match is None:
        # (d) Dernier recours : faute de frappe probable dans le titre.
        match = _match_by_fuzzy_name(db, names, set_number)

    if match is not None:
        _flag_variant_mismatch(match, variant)
    return match


def _normaliser_code(code: Optional[str]) -> str:
    """« OP01-120 », « OP01 120 » et « op01120 » designent la MEME carte.

    Le separateur depend de la source : One Piece ecrit « OP01-120 » avec un
    tiret, d'autres catalogues separent par une espace, et les vendeurs
    melangent les deux. Le parseur de titre, lui, normalise en
    espace. Comparer les chaines telles quelles faisait donc echouer le
    rapprochement par code sur TOUTES les cartes One Piece, en silence : le
    prix retombait sur un rapprochement par nom, beaucoup moins sur.
    """
    return re.sub(r"[\s\-_.]+", "", (code or "").upper())


def _variantes_de_code(code: str) -> set:
    """Formes equivalentes d'un code, pour que le filtre SQL puisse
    presélectionner sans dependre du separateur."""
    haut = (code or "").upper()
    return {haut, haut.replace(" ", "-"), haut.replace("-", " ")}


def _match_by_card_code(db: Session, codes: List[str],
                        variant: Optional[str] = None) -> Optional[PriceMatch]:
    if not codes:
        return None

    candidats = set()
    for code in codes:
        candidats |= _variantes_de_code(code)

    rows = (
        db.query(MarketCardPrice)
        .filter(func.upper(MarketCardPrice.card_code).in_(sorted(candidats)))
        .all()
    )
    if not rows:
        return None

    grouped: dict = {}
    for row in rows:
        grouped.setdefault(_normaliser_code(row.card_code), []).append(row)

    for code in codes:  # ordre = celui d'apparition dans le titre
        group = grouped.get(_normaliser_code(code))
        if group:
            # Un code peut designer plusieurs fiches (ordinaire / parallele).
            # On tranche avec la variante annoncee AVANT de prendre la
            # mediane, sinon la mediane departagerait des cartes qui ne sont
            # pas comparables.
            retenues = _choisir_selon_variante(group, variant)
            motif = f"code carte {code} trouve dans le titre"
            if len(retenues) < len(group):
                precision = ("variante « %s » annoncee" % variant) if variant \
                    else "aucune variante annoncee, impression ordinaire retenue"
                motif = f"{motif} ({precision})"
            match = PriceMatch(_median_row(retenues), "high", motif, retenues)
            # On ne signale une variante non retrouvee que si le code etait
            # AMBIGU. Quand il ne designe qu'une fiche, le code EST
            # l'identification : rien d'autre ne porte ce numero, et avertir
            # « verifie toi-meme » sans proposer d'alternative n'apprend rien
            # a personne. Une alerte qui se declenche sans enjeu use la
            # credibilite de celles qui en ont un.
            if (variant and len(group) > 1
                    and not any(_variante_satisfaite(l, variant) for l in group)):
                _flag_variant_mismatch(match, variant)
            return match
    return None


def _match_by_name(db: Session, names: List[str], set_number) -> Optional[PriceMatch]:
    if not names:
        return None
    rows = db.query(MarketCardPrice).filter(MarketCardPrice.name_slug.in_(names)).all()
    if not rows:
        return None

    grouped: dict = {}
    for row in rows:
        grouped.setdefault(row.name_slug, []).append(row)

    # `names` est deja trie du plus specifique au moins specifique
    # ("epine-de-fer" avant "epine"), on prend donc le premier qui existe.
    for name in names:
        group = grouped.get(name)
        if group:
            return _best_in_group(name, group, set_number)
    return None


def _best_in_group(name: str, group: List[MarketCardPrice], set_number) -> PriceMatch:
    if set_number:
        wanted = _as_int(set_number[0])
        # Comparaison NUMERIQUE et non textuelle : l'index melange les
        # conventions ("PBL 016" mais "CEC 66"), donc un LIKE '%004' ratait
        # la carte 4/102 dont le code reel se termine par " 4".
        exact = [r for r in group if _card_number(r.card_code) == wanted]
        if exact:
            return PriceMatch(
                _median_row(exact), "high",
                f"nom '{name}' + numero {wanted}", exact,
            )

    if len(group) == 1:
        return PriceMatch(group[0], "medium", f"nom '{name}' (unique dans l'index)", group)

    return PriceMatch(
        _median_row(group), "low",
        f"nom '{name}' present dans {len(group)} series - prix median retenu",
        group,
    )


def _slugs_finissant_par(connus: List[str], candidat: str) -> List[str]:
    """Noms indexes dont le candidat est la fin, sur des mots entiers.

    Le tiret dans le suffixe est ce qui garantit « mots entiers » :
    « ace » retrouve « portgas-d-ace » mais PAS « menace ».
    """
    suffixe = f"-{candidat}"
    return [slug for slug in connus if slug.endswith(suffixe)]


def _match_by_partial_name(db: Session, names: List[str]) -> Optional[PriceMatch]:
    """Rattrape le nom usuel quand l'index porte le nom complet.

    N'est atteint que si le nom complet n'a RIEN donne : une egalite exacte
    aurait deja ete trouvee par `_match_by_name`. Ici on ne cherche donc que
    des noms indexes PLUS LONGS que ce qu'a ecrit le vendeur.

    Pas d'affinage par numero de set, contrairement aux autres niveaux :
    One Piece numerote « OP01-120 » et non « 4/102 », donc ce signal
    n'existe pas ici — le pretendre rendrait le code plus difficile a
    suivre pour un gain nul.
    """
    if not names:
        return None
    connus = _known_slugs(db)
    if not connus:
        return None

    # `names` est trie du plus specifique au moins specifique : on essaie
    # donc « luffy-leader » avant « luffy ».
    for name in names:
        if len(name) < PARTIEL_MIN_LENGTH:
            continue
        slugs = _slugs_finissant_par(connus, name)
        if not slugs:
            continue

        rows = db.query(MarketCardPrice).filter(
            MarketCardPrice.name_slug.in_(slugs)
        ).all()
        if not rows or len(rows) > PARTIEL_MAX_CARTES:
            # Trop de cartes : on passe au candidat suivant plutot que de
            # rendre une mediane qui ne voudrait rien dire.
            continue

        if len(rows) == 1:
            return PriceMatch(
                rows[0], "medium",
                f"nom usuel '{name}' : une seule carte de l'index porte ce "
                f"nom ({rows[0].display_name})",
                rows,
            )

        # Plusieurs cartes : la mediane est retenue mais l'ecart est expose,
        # et `is_uncertain` s'en saisit pour prevenir l'utilisateur.
        return PriceMatch(
            _median_row(rows), "low",
            f"nom usuel '{name}' : {len(rows)} cartes de l'index finissent "
            f"par ce nom - prix median retenu",
            rows,
        )
    return None


def _match_by_fuzzy_name(db: Session, names: List[str], set_number) -> Optional[PriceMatch]:
    """
    Rattrapage des fautes de frappe ("zorro" pour "zoro", "lufy"...).
    Compare les candidats aux noms REELLEMENT presents dans l'index, garde
    en cache la liste des noms pour ne pas la relire a chaque annonce.

    Volontairement severe (similarite >= 0.86, noms courts exclus) : mieux
    vaut ne pas trouver de prix que d'en afficher un faux.
    """
    if not names:
        return None
    known = _known_slugs(db)
    if not known:
        return None

    for name in names[:FUZZY_MAX_TRIES]:
        if len(name) < FUZZY_MIN_LENGTH:
            continue
        close = difflib.get_close_matches(name, known, n=1, cutoff=FUZZY_MIN_RATIO)
        if not close or close[0] == name:
            continue
        corrected = close[0]
        if not _is_plausible_typo(name, corrected):
            continue
        rows = db.query(MarketCardPrice).filter(
            MarketCardPrice.name_slug == corrected
        ).all()
        if not rows:
            continue
        match = _best_in_group(corrected, rows, set_number)
        match.confidence = "low"
        match.reason = (
            f"'{name}' rapproche de '{corrected}' (faute de frappe probable) "
            f"- {match.reason}"
        )
        return match
    return None


def _variant_tail(slug: str) -> Optional[str]:
    """Derniere partie du slug si c'est une variante ("luffy-leader" -> "leader")."""
    tail = slug.rsplit("-", 1)[-1] if "-" in slug else None
    return tail if tail in NAME_SUFFIXES else None


# Mots differents, meme chose. Un vendeur ecrit « parallele », « alt »,
# « alt art » ou « alternative » pour la meme realite : une illustration
# alternative. Le catalogue, lui, n'en retient qu'une orthographe.
_FAMILLES_VARIANTE = {
    "parallele": {"parallele", "alternative", "alt"},
    "alternative": {"parallele", "alternative", "alt"},
    "alt": {"parallele", "alternative", "alt"},
    "secret": {"secret", "sec"},
    "sec": {"secret", "sec"},
    "manga": {"manga"},
    "leader": {"leader"},
}

# Une variante annoncee dans le titre peut etre confirmee par la RARETE de
# la carte au lieu de son nom. « Zoro OP01-001 Leader » annonce « leader »,
# et OP01-001 est bien un Leader — sa rarete le dit — alors que son nom ne
# porte aucun suffixe. Sans cette corroboration, presque toutes les annonces
# de Leaders seraient signalees comme douteuses a tort, et une alerte qui se
# declenche tout le temps ne s'ecoute plus.
_RARETE_CORROBORE = {
    "leader": r"\bleader\b|^l$",
    "secret": r"secret|^sec$",
    "sec": r"secret|^sec$",
    "manga": r"manga",
}


# Les variantes d'ILLUSTRATION, et le rang de fiche qu'elles designent.
#
# Le rang d'une fiche (0 = ordinaire, 1 = premiere alternative, 2 = seconde)
# vient de la liste officielle, et l'appariement « Parallele = 1, Manga = 2 »
# a ete etabli en comparant les images des deux sources (voir
# collectors/opecards_prices.RANGS_PAR_MENTION).
#
# POURQUOI LE RANG, ET PLUS LA FIN DU NOM. On lisait la variante d'une fiche
# sur la fin de son slug : « shanks-parallele » -> « parallele ». Depuis que
# chaque alternative a sa propre fiche — « shanks-parallele-1 »,
# « shanks-parallele-2 » —, cette lecture ne reconnaissait plus rien, et les
# trois fiches d'un code passaient toutes pour des impressions ordinaires.
# La mediane de leurs prix etait alors retenue : une annonce de la carte
# ordinaire, a 0,75 EUR, etait evaluee au prix du parallele, et s'affichait
# comme une affaire. Le rang, lui, ne depend pas de l'orthographe.
_RANG_DE_VARIANTE = {"parallele": 1, "alternative": 1, "alt": 1, "manga": 2}


def _rang(ligne) -> int:
    return rang_de_parallele(ligne.name_slug)


def _variante_satisfaite(ligne, variant: str) -> bool:
    """Vrai si `ligne` porte bien la variante annoncee, par son nom ou sa rarete."""
    if variant in _RANG_DE_VARIANTE:
        # Le rang EXACT. Quand le titre dit « manga » et que le code n'a
        # qu'un parallele, on retient ce parallele pour donner un ordre de
        # grandeur — mais rien ne prouve que ce soit l'illustration manga, et
        # le prix doit etre marque incertain plutot qu'affiche comme sur.
        return _rang(ligne) == _RANG_DE_VARIANTE[variant]
    famille = _FAMILLES_VARIANTE.get(variant, {variant})
    if _variant_tail((ligne.name_slug or "").lower()) in famille:
        return True
    motif = _RARETE_CORROBORE.get(variant)
    if motif and re.search(motif, (ligne.rarity or "").lower()):
        return True
    return False


def _choisir_selon_variante(group: List[MarketCardPrice],
                            variant: Optional[str]) -> List[MarketCardPrice]:
    """Restreint un groupe de cartes partageant un code a celles dont la
    variante correspond a ce que le titre annonce.

    Pourquoi c'est necessaire : la liste officielle donne DEUX fiches pour un
    meme code — l'impression ordinaire et l'illustration alternative — et sur
    ce marche l'alternative vaut plusieurs fois l'ordinaire. Prendre l'une
    pour l'autre ne produit pas une petite imprecision mais un prix de
    reference faux, donc une marge fausse, donc une « bonne affaire » qui
    n'existe pas (ou, pire, une vraie qu'on n'a pas vue).

    Les deux sens comptent. Un titre qui dit « parallele » doit retenir
    l'alternative ; un titre qui ne dit RIEN doit retenir l'ordinaire, et
    c'est le cas le plus courant.
    """
    if len(group) < 2:
        return group

    if variant in _RANG_DE_VARIANTE:
        voulu = _RANG_DE_VARIANTE[variant]
        exactes = [l for l in group if _rang(l) == voulu]
        if exactes:
            return exactes
        # Le rang annonce n'existe pas pour ce code — un seul parallele,
        # par exemple, quand le titre dit « manga ». On retient l'alternative
        # la plus proche plutot que toutes : la mediane de plusieurs
        # alternatives retomberait sur la plus chere.
        alternatives = sorted({_rang(l) for l in group if _rang(l) >= 1})
        if alternatives:
            return [l for l in group if _rang(l) == alternatives[0]]
        # Aucune alternative : groupe inchange, et _flag_variant_mismatch le
        # signalera plutot que de trancher au hasard.
        return group

    if variant:
        correspondantes = [l for l in group if _variante_satisfaite(l, variant)]
        # Une variante de TYPE (« leader ») ou de RARETE (« sec ») n'est pas
        # une illustration : parmi les cartes qui la portent, l'impression
        # ordinaire reste la bonne, sauf annonce contraire.
        ordinaires = [l for l in correspondantes if _rang(l) == 0]
        return ordinaires or correspondantes or group

    ordinaires = [l for l in group if _rang(l) == 0]
    return ordinaires or group


def _is_plausible_typo(candidate: str, corrected: str) -> bool:
    """
    Garde-fou du rattrapage orthographique. Une similarite elevee ne suffit
    pas : "luffy" et "luffy-leader" se ressemblent beaucoup mais sont deux
    cartes aux prix sans rapport. On exige donc une longueur proche et une
    variante identique de part et d'autre.
    """
    if abs(len(candidate) - len(corrected)) > FUZZY_MAX_LENGTH_DELTA:
        return False
    return _variant_tail(candidate) == _variant_tail(corrected)


def _flag_variant_mismatch(match: PriceMatch, variant: Optional[str]) -> None:
    """
    Le titre annonce "Luffy Leader" mais la carte retenue est "Luffy"
    tout court ? Ce sont deux cartes differentes, aux prix sans rapport.
    On garde le prix (il donne un ordre de grandeur) mais on le signale
    explicitement au lieu de le presenter comme sur.
    """
    if not variant:
        return
    # Meme regle que pour le choix de la fiche : le nom OU la rarete peut
    # confirmer la variante. Deux criteres differents ici et la aboutiraient
    # a retenir la bonne carte puis a la declarer douteuse.
    if _variante_satisfaite(match.row, variant):
        return
    slug = (match.row.name_slug or "").lower()
    if slug.endswith(f"-{variant}") or f"-{variant}-" in slug:
        return
    match.confidence = "low"
    match.warning = (
        f"Le titre annonce une carte « {variant.upper()} », mais la carte "
        f"trouvee dans l'index est « {match.row.display_name} ». Ce sont "
        f"probablement deux cartes differentes : verifie le prix toi-meme."
    )


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _card_number(card_code: Optional[str]) -> Optional[int]:
    """Partie numerique finale d'un code carte : "CEC 66" -> 66."""
    if not card_code:
        return None
    found = re.search(r"(\d+)\s*$", card_code)
    return int(found.group(1)) if found else None


def _known_slugs(db: Session) -> List[str]:
    global _slug_cache, _slug_cache_at
    now = datetime.utcnow()
    if _slug_cache and _slug_cache_at and now - _slug_cache_at < SLUG_CACHE_MAX_AGE:
        return _slug_cache
    _slug_cache = [row[0] for row in db.query(MarketCardPrice.name_slug).distinct().all() if row[0]]
    _slug_cache_at = now
    logger.info("Index prix : %d noms de cartes charges pour le rattrapage orthographique",
                len(_slug_cache))
    return _slug_cache


def _median_row(rows: List[MarketCardPrice]) -> MarketCardPrice:
    """Carte representative parmi des homonymes : celle du prix median.

    Les cartes sans prix connu sont ecartees du calcul — prendre la mediane
    d'un ensemble ou la moitie des valeurs manquent ne veut rien dire, et
    `None` n'est de toute facon pas comparable a un flottant.

    Quand AUCUNE n'a de prix, on rend quand meme une ligne : elle ne servira
    pas a chiffrer une marge, mais elle identifie la carte, ce qui suffit a
    afficher son visuel et a pointer vers sa fiche.
    """
    chiffrees = [r for r in rows if r.price_eur is not None]
    if not chiffrees:
        return rows[0]
    ordered = sorted(chiffrees, key=lambda r: r.price_eur)
    return ordered[len(ordered) // 2]


def index_stats(db: Session) -> dict:
    """Avancement de l'index des prix : combien de fiches sont chiffrees.

    CE QUE CETTE FONCTION MESURAIT AVANT, ET POURQUOI C'ETAIT FAUX
    --------------------------------------------------------------
    Elle comptait les series synchronisees dans ZebraDexSeriesState. Or
    ZebraDex ne couvre pas One Piece et a ete retire du cycle : plus rien
    ne remplit cette table. L'avancement valait donc 0 % en permanence, sur
    « 0/0 series », et le tableau de bord l'affichait en orange — c'est-a-dire
    qu'il signalait une panne alors que le catalogue etait chiffre a moitie.

    Un indicateur qui mesure une source disparue est pire qu'absent : il
    detourne l'attention de ce qui va vraiment mal.

    CE QU'ELLE MESURE MAINTENANT
    ----------------------------
    La seule chose qui compte pour l'utilisateur : la part des cartes du
    catalogue qui ont un prix de reference, donc pour lesquelles une marge
    peut etre calculee. Sans prix, une annonce est identifiee mais pas jugee.
    """
    from sqlalchemy import func

    total = db.query(MarketCardPrice).count()
    chiffrees = (db.query(MarketCardPrice)
                 .filter(MarketCardPrice.price_eur.isnot(None)).count())
    # Quand les prix de reference ont ete releves pour la derniere fois.
    # C'est ce qui permet au script de demarrage de NE PAS tout recharger a
    # chaque relance : des prix du jour n'ont pas besoin d'etre relus, et les
    # relire faisait attendre une demi-heure avant de pouvoir ouvrir le site.
    dernier = (db.query(func.max(MarketCardPrice.updated_at))
               .filter(MarketCardPrice.source == "opecards").scalar())
    return {
        "cards_in_index": total,
        "cards_priced": chiffrees,
        "cards_unpriced": total - chiffrees,
        "progress_percent": round(100 * chiffrees / total, 1) if total else 0.0,
        "prices_updated_at": dernier.isoformat() if dernier else None,
        # Conserves pour ne pas casser les appelants qui les lisent encore.
        # Ils ne decrivent plus une synchronisation de series, qui n'existe
        # plus, mais le meme decompte exprime en cartes.
        "series_known": total,
        "series_synced": chiffrees,
        "series_pending": total - chiffrees,
    }
