"""
Construction et interrogation de l'index local de prix de reference.

Deux responsabilites :
1. SYNCHRONISATION (`sync_series_batch`) : remplit `market_card_prices`
   depuis ZebraDex, de facon PROGRESSIVE. Les 169 series ne sont pas
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
from app.matching.title_parser import (
    NAME_SUFFIXES, extract_card_codes, extract_name_candidates,
    extract_set_number, extract_variant,
)
from app.models import MarketCardPrice, ZebraDexSeriesState

logger = logging.getLogger(__name__)

_client = ZebraDexClient()

# --- Rattrapage des fautes de frappe -------------------------------------
# Similarite minimale pour accepter une correction, longueur minimale du
# nom teste, et nombre de candidats essayes. Regles volontairement severes :
# un faux prix de reference est plus nuisible qu'une absence de prix.
FUZZY_MIN_RATIO = 0.80
FUZZY_MIN_LENGTH = 5
FUZZY_MAX_TRIES = 8
# Ecart de longueur tolere. "dracofeu" -> "dracaufeu" (1 lettre) : oui.
# "pikachu" -> "pikachu-ex" (3 caracteres) : non, ce sont deux cartes
# differentes, pas une faute de frappe.
FUZZY_MAX_LENGTH_DELTA = 2

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


def sync_series_batch(db: Session, batch_size: int = 6) -> dict:
    """
    Synchronise `batch_size` series : d'abord celles jamais synchronisees,
    puis les plus anciennes. Retourne un resume pour les logs / l'API admin.
    """
    if db.query(ZebraDexSeriesState).count() == 0:
        refresh_series_catalog(db)

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
        # l'incertitude : si 10 cartes s'appellent "Dracaufeu" et que leurs
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

    # (a) Code carte explicite : le seul cas ou on est vraiment sur, donc
    # le seul ou une variante non retrouvee dans le nom n'est pas suspecte.
    match = _match_by_card_code(db, codes)
    if match is not None:
        return match

    # (b) Nom (groupe de mots le plus specifique d'abord), affine par le
    # numero de set quand il est present.
    match = _match_by_name(db, names, set_number)
    if match is None:
        # (c) Dernier recours : faute de frappe probable dans le titre.
        match = _match_by_fuzzy_name(db, names, set_number)

    if match is not None:
        _flag_variant_mismatch(match, variant)
    return match


def _match_by_card_code(db: Session, codes: List[str]) -> Optional[PriceMatch]:
    if not codes:
        return None
    rows = (
        db.query(MarketCardPrice)
        .filter(func.upper(MarketCardPrice.card_code).in_(codes))
        .all()
    )
    if not rows:
        return None

    grouped: dict = {}
    for row in rows:
        grouped.setdefault((row.card_code or "").upper(), []).append(row)

    for code in codes:  # ordre = celui d'apparition dans le titre
        group = grouped.get(code)
        if group:
            return PriceMatch(
                _median_row(group), "high",
                f"code carte {code} trouve dans le titre", group,
            )
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


def _match_by_fuzzy_name(db: Session, names: List[str], set_number) -> Optional[PriceMatch]:
    """
    Rattrapage des fautes de frappe ("dracofeu", "salameche" mal ecrit...).
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
    """Derniere partie du slug si c'est une variante ("dracaufeu-ex" -> "ex")."""
    tail = slug.rsplit("-", 1)[-1] if "-" in slug else None
    return tail if tail in NAME_SUFFIXES else None


def _is_plausible_typo(candidate: str, corrected: str) -> bool:
    """
    Garde-fou du rattrapage orthographique. Une similarite elevee ne suffit
    pas : "pikachu" et "pikachu-ex" se ressemblent beaucoup mais sont deux
    cartes aux prix sans rapport. On exige donc une longueur proche et une
    variante identique de part et d'autre.
    """
    if abs(len(candidate) - len(corrected)) > FUZZY_MAX_LENGTH_DELTA:
        return False
    return _variant_tail(candidate) == _variant_tail(corrected)


def _flag_variant_mismatch(match: PriceMatch, variant: Optional[str]) -> None:
    """
    Le titre annonce "Dracaufeu V" mais la carte retenue est "Dracaufeu"
    tout court ? Ce sont deux cartes differentes, aux prix sans rapport.
    On garde le prix (il donne un ordre de grandeur) mais on le signale
    explicitement au lieu de le presenter comme sur.
    """
    if not variant:
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
    ordered = sorted(rows, key=lambda r: r.price_eur)
    return ordered[len(ordered) // 2]


def index_stats(db: Session) -> dict:
    total_series = db.query(ZebraDexSeriesState).count()
    synced = db.query(ZebraDexSeriesState).filter(
        ZebraDexSeriesState.last_synced_at.isnot(None)
    ).count()
    return {
        "series_known": total_series,
        "series_synced": synced,
        "series_pending": total_series - synced,
        "cards_in_index": db.query(MarketCardPrice).count(),
        "progress_percent": round(100 * synced / total_series, 1) if total_series else 0.0,
    }
