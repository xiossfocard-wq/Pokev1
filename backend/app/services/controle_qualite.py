"""
Controle de la justesse des prix et de la langue des cartes.

POURQUOI CE MODULE EXISTE
-------------------------
Un prix faux ne se voit pas. Il est plausible, il produit une marge
plausible, et l'application annonce une affaire qui n'en est pas une. Les
defauts qu'on a corriges jusqu'ici — la commune a 850 EUR, le manga a
0,02 EUR, le prix pose sur l'impression ordinaire — ont tous ete trouves
par hasard, en lisant un journal. Ce module les cherche systematiquement,
sur la base reelle de l'utilisateur.

Il ne CORRIGE rien : il rapporte, avec des exemples, pour qu'une anomalie
puisse etre verifiee carte par carte avant qu'on decide quoi en faire.

CE QUI EST CONTROLE
-------------------
Prix
  - une variante beaucoup moins chere que sa carte de base : signature d'un
    rapprochement qui a confondu les illustrations ;
  - un prix aberrant pour sa rarete, par rapport aux cartes de meme rarete ;
  - des prix venus d'autres sources que la boutique francaise ;
  - l'age du dernier releve.
Langue
  - des cartes au nom anglais dans une serie qui existe en francais : la
    liste officielle les a manquees ;
  - des cartes chiffrees par la source francaise mais marquees anglaises :
    leur langue est fausse ;
  - des annonces encore visibles que le filtre de langue actuel ecarterait.
"""
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from sqlalchemy.orm import Session

from app.collectors.cardlist_fr import rang_de_parallele
from app.core.langues import ANGLAIS, FRANCAIS
from app.models import Listing, ListingStatus, MarketCardPrice

SOURCE_FRANCAISE = "opecards"

# Une variante qui vaut moins de la moitie de sa carte de base est suspecte :
# une illustration alternative coute presque toujours plus cher que
# l'ordinaire, et c'est exactement ainsi que se manifestait le prix d'une
# carte pose sur une autre.
RAPPORT_VARIANTE_SUSPECT = 0.5

# Ecart a la mediane de la rarete au-dela duquel un prix est signale. Large
# a dessein : ce marche a de vraies cartes tres cheres et de vraies cartes
# bradees, et un controle qui crie a chaque carte ne serait plus lu.
FACTEUR_ABERRANT = 25.0
MINIMUM_PAR_RARETE = 8

EXEMPLES = 8


def _rarete(brut) -> str:
    """« SEC (Secret Rare) » et « SEC » -> « SEC »."""
    return (brut or "?").split("(")[0].strip().upper() or "?"


def _prefixe(code: str) -> str:
    """« OP09-001 » -> « OP09 », « P-084 » -> « P »."""
    return (code or "").split("-")[0].upper()


def _fiche(c: MarketCardPrice) -> dict:
    return {"code": c.card_code, "nom": c.display_name, "rarete": c.rarity,
            "prix": round(c.price_eur, 2) if c.price_eur is not None else None,
            "langue": c.language}


def controler_prix(cartes: List[MarketCardPrice]) -> dict:
    chiffrees = [c for c in cartes if c.price_eur is not None]

    # 1. Variantes moins cheres que leur carte de base.
    par_code: Dict[str, Dict[int, MarketCardPrice]] = defaultdict(dict)
    for c in chiffrees:
        par_code[(c.card_code or "").upper()][rang_de_parallele(c.name_slug)] = c
    variantes_suspectes = []
    for code, rangs in par_code.items():
        base = rangs.get(0)
        if not base or not base.price_eur:
            continue
        for rang, variante in sorted(rangs.items()):
            if rang > 0 and variante.price_eur < base.price_eur * RAPPORT_VARIANTE_SUSPECT:
                variantes_suspectes.append({
                    "code": code, "base": base.display_name,
                    "prix_base": round(base.price_eur, 2),
                    "variante": variante.display_name,
                    "prix_variante": round(variante.price_eur, 2),
                })
    variantes_suspectes.sort(key=lambda v: v["prix_variante"] / v["prix_base"])

    # 2. Prix aberrants pour leur rarete — sur les impressions ordinaires
    # seulement : les alternatives ont leur propre echelle.
    par_rarete: Dict[str, List[MarketCardPrice]] = defaultdict(list)
    for c in chiffrees:
        if rang_de_parallele(c.name_slug) == 0 and c.price_eur > 0:
            par_rarete[_rarete(c.rarity)].append(c)
    aberrants = []
    medianes = {}
    for rarete, groupe in par_rarete.items():
        if len(groupe) < MINIMUM_PAR_RARETE:
            continue
        mediane = statistics.median(c.price_eur for c in groupe)
        medianes[rarete] = round(mediane, 2)
        for c in groupe:
            if c.price_eur > mediane * FACTEUR_ABERRANT or c.price_eur < mediane / FACTEUR_ABERRANT:
                aberrants.append({**_fiche(c), "mediane_de_la_rarete": round(mediane, 2)})
    aberrants.sort(key=lambda a: -abs((a["prix"] or 0) - a["mediane_de_la_rarete"]))

    # 3. D'ou viennent les prix.
    par_source = defaultdict(int)
    for c in chiffrees:
        par_source[c.source or "inconnue"] += 1
    etrangeres = [c for c in chiffrees if (c.source or "") != SOURCE_FRANCAISE]

    # 4. Age du dernier releve.
    releves = [c.updated_at for c in chiffrees
               if c.source == SOURCE_FRANCAISE and c.updated_at]
    dernier = max(releves) if releves else None

    return {
        "cartes_chiffrees": len(chiffrees),
        "dernier_releve": dernier.isoformat() if dernier else None,
        "age_du_releve_heures": (round((datetime.utcnow() - dernier).total_seconds() / 3600, 1)
                                 if dernier else None),
        "prix_par_source": dict(par_source),
        "prix_hors_source_francaise": {
            "nombre": len(etrangeres),
            "explication": ("Prix qui ne viennent pas de la boutique francaise : restes "
                            "d'un ancien index, de donnees de demonstration ou d'une saisie. "
                            "Ils ne disent pas ce que vaut la carte francaise."),
            "exemples": [{**_fiche(c), "source": c.source} for c in etrangeres[:EXEMPLES]],
        },
        "variantes_moins_cheres_que_la_base": {
            "nombre": len(variantes_suspectes),
            "explication": ("Une illustration alternative vaut presque toujours plus que "
                            "l'ordinaire. Moins de la moitie : probablement deux cartes "
                            "confondues."),
            "exemples": variantes_suspectes[:EXEMPLES],
        },
        "prix_aberrants_pour_la_rarete": {
            "nombre": len(aberrants),
            "explication": (f"Plus de {FACTEUR_ABERRANT:g} fois au-dessus ou au-dessous de "
                            "la mediane des cartes de meme rarete. Certaines sont reelles "
                            "(cartes tres jouees ou bradees) : a verifier une a une."),
            "medianes_par_rarete": medianes,
            "exemples": aberrants[:EXEMPLES],
        },
    }


def controler_langue(cartes: List[MarketCardPrice]) -> dict:
    francaises = [c for c in cartes if c.language == FRANCAIS]
    anglaises = [c for c in cartes if c.language == ANGLAIS]
    sans_langue = [c for c in cartes if c.language not in (FRANCAIS, ANGLAIS)]

    # Une serie existe en francais si la liste officielle francaise y a mis
    # au moins une carte. Une carte anglaise dans une telle serie est donc
    # une carte que la liste a manquee — sauf illustration absente du jeu
    # francais, que ce controle ne peut pas distinguer.
    series_francaises = {_prefixe(c.card_code) for c in francaises}
    manquees = [c for c in anglaises if _prefixe(c.card_code) in series_francaises]
    manquees_par_serie = defaultdict(int)
    for c in manquees:
        manquees_par_serie[_prefixe(c.card_code)] += 1

    # Chiffree par la boutique francaise, qui ne liste que des cartes
    # francaises : la carte existe donc en francais, quoi que dise sa langue.
    langue_fausse = [c for c in anglaises
                     if c.price_eur is not None and c.source == SOURCE_FRANCAISE]

    return {
        "cartes": len(cartes),
        "francaises": len(francaises),
        "anglaises": len(anglaises),
        "sans_langue": len(sans_langue),
        "anglaises_hors_jeu_francais": len(anglaises) - len(manquees),
        "explication_anglaises": ("Le jeu francais commence a OP09 : les cartes des series "
                                  "plus anciennes n'existent qu'en anglais, sauf reedition. "
                                  "Elles restent au catalogue, signalees « nom anglais »."),
        "anglaises_dans_une_serie_francaise": {
            "nombre": len(manquees),
            "explication": ("Cartes au nom anglais dans une serie qui existe en francais : "
                            "la liste officielle francaise ne les a pas fournies."),
            "par_serie": dict(sorted(manquees_par_serie.items(), key=lambda s: -s[1])),
            "exemples": [_fiche(c) for c in manquees[:EXEMPLES]],
        },
        "chiffrees_en_francais_mais_marquees_anglaises": {
            "nombre": len(langue_fausse),
            "explication": ("La boutique francaise ne vend que des cartes francaises : une "
                            "carte qu'elle chiffre existe en francais, et sa langue est fausse."),
            "exemples": [_fiche(c) for c in langue_fausse[:EXEMPLES]],
        },
    }


def controler_annonces(db: Session) -> dict:
    """Les annonces visibles que le filtre de langue ACTUEL ecarterait.

    Le filtre est repasse a chaque cycle de collecte ; ce nombre dit combien
    d'annonces le prochain cycle va retirer du radar.
    """
    from app.core.language_filter import detect_language

    visibles = (db.query(Listing)
                .filter(Listing.status != ListingStatus.IGNORED)
                .all())
    a_ecarter = []
    for annonce in visibles:
        verdict = detect_language(annonce.title, annonce.description)
        if not verdict.is_french and verdict.confidence in ("high", "medium"):
            a_ecarter.append({"titre": annonce.title[:90], "langue": verdict.language,
                              "raison": verdict.reasons[0] if verdict.reasons else ""})
    return {
        "annonces_visibles": len(visibles),
        "que_le_filtre_actuel_ecarterait": {
            "nombre": len(a_ecarter),
            "explication": ("Annonces encore affichees mais jugees non francaises par le "
                            "filtre actuel : le prochain cycle de collecte les retirera."),
            "exemples": a_ecarter[:EXEMPLES],
        },
    }


def controler(db: Session) -> dict:
    cartes = db.query(MarketCardPrice).all()
    return {
        "etabli_le": datetime.utcnow().isoformat(),
        "prix": controler_prix(cartes),
        "langue": controler_langue(cartes),
        "annonces": controler_annonces(db),
    }
