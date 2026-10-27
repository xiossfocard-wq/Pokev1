"""
Une page par personnage : toutes ses cartes, de la plus accessible a la plus
rare, et les conseils d'un connaisseur pour commencer ou completer sa
collection.

Seulement les personnages APPRECIES — les icones de la serie et les
personnages tres recherches (voir recommandations._ICONES et _RECHERCHES).
Une page par figurant n'aiderait personne a construire une belle collection.

Une carte appartient au personnage reconnu dans son nom, selon les memes
regles que les idees de collection (graphies francaises et anglaises).
"""
import math
import re
import statistics
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import CartePossedee, CarteSuivie, MarketCardPrice
from app.services import card_catalog, card_themes, recommandations as reco, suivi

# Combien d'annonces montrer en tete de page : les meilleures affaires.
ANNONCES_EN_TETE = 8

# Les paliers de prix, du plus accessible au plus rare.
PALIERS = [
    ("petits-prix", "Les petits prix", "Moins de 5 € : de quoi poser les premières cartes.", 0, 5),
    ("abordables", "Belles et abordables", "De 5 à 20 €.", 5, 20),
    ("pieces", "Pièces de collection", "De 20 à 100 €.", 20, 100),
    ("graals", "Les graals", "Plus de 100 € : les cartes qu'on garde pour la fin.", 100, None),
]


def slug_de(nom: str) -> str:
    """« Boa Hancock » -> « boa-hancock », « Gol D. Roger » -> « gol-d-roger »."""
    return re.sub(r"[^a-z0-9]+", "-", card_themes._sans_accents(nom)).strip("-")


def _apprecies() -> List[dict]:
    """Les personnages qui ont leur page, icones d'abord."""
    return ([{"nom": nom, "calibre": "icone", "slug": slug_de(nom)} for _, nom in reco._ICONES]
            + [{"nom": nom, "calibre": "recherche", "slug": slug_de(nom)} for _, nom in reco._RECHERCHES])


def _cartes_par_personnage(db: Session, toutes_langues: bool) -> Dict[str, List[dict]]:
    requete = db.query(MarketCardPrice)
    if not toutes_langues:
        requete = requete.filter(MarketCardPrice.language == "fr")
    groupes: Dict[str, List[dict]] = {}
    for ligne in requete.all():
        p = reco._profil(ligne)
        if p["perso"]:
            groupes.setdefault(p["perso"], []).append(p)
    return groupes


def _possedees(db: Session) -> Dict[tuple, int]:
    compte: Dict[tuple, int] = {}
    for c in db.query(CartePossedee).all():
        cle = (c.card_code, c.name_slug)
        compte[cle] = compte.get(cle, 0) + 1
    return compte


def _cle(p: dict) -> tuple:
    return (p["ligne"].card_code, p["ligne"].name_slug)


def liste_des_personnages(db: Session, toutes_langues: bool = False) -> List[dict]:
    """Chaque personnage apprecie qui a au moins une carte : combien de
    cartes, de belles versions, a partir de quel prix, et ce qu'on en a."""
    groupes = _cartes_par_personnage(db, toutes_langues)
    possedees = _possedees(db)
    resultat = []
    for perso in _apprecies():
        cartes = groupes.get(perso["nom"], [])
        if not cartes:
            continue
        belles = [p for p in cartes if p["poids_visuel"] >= 3]
        prix = [p["ligne"].price_eur for p in cartes if p["ligne"].price_eur]
        # L'apercu : sa plus belle carte qui a un visuel (la plus rare d'abord).
        avec_visuel = [p for p in cartes if p["ligne"].image_url]
        apercu = max(avec_visuel, key=lambda p: (p["poids_visuel"], p["ligne"].price_eur or 0), default=None)
        resultat.append({
            **perso,
            "cartes": len(cartes),
            "belles": len(belles),
            "prix_min": min(prix) if prix else None,
            "prix_max": max(prix) if prix else None,
            "possedees": sum(1 for p in cartes if _cle(p) in possedees),
            "belles_possedees": sum(1 for p in belles if _cle(p) in possedees),
            "image_url": apercu["ligne"].image_url if apercu else None,
        })
    return resultat


def _medianes_des_semblables(db: Session, langue: Optional[str]) -> Dict[tuple, float]:
    """La mediane de chaque groupe de cartes comparables, sur tout le
    catalogue chiffre — le meme repere que les idees de collection."""
    requete = db.query(MarketCardPrice).filter(MarketCardPrice.price_eur.isnot(None),
                                               MarketCardPrice.price_eur > 0)
    if langue:
        requete = requete.filter(MarketCardPrice.language == langue)
    par_groupe: Dict[tuple, List[float]] = {}
    for ligne in requete.all():
        p = reco._profil(ligne)
        if p["poids_visuel"] >= 1:
            par_groupe.setdefault(reco._groupe_comparable(p), []).append(ligne.price_eur)
    return {g: statistics.median(v) for g, v in par_groupe.items() if len(v) >= reco.COMPARABLES_MINIMUM}


def page_du_personnage(db: Session, slug: str, toutes_langues: bool = False) -> Optional[dict]:
    """Toutes les cartes d'un personnage apprecie, par palier de prix, et les
    conseils pour sa collection. None si le personnage n'a pas de page."""
    perso = next((p for p in _apprecies() if p["slug"] == slug), None)
    if perso is None:
        return None
    cartes = _cartes_par_personnage(db, toutes_langues).get(perso["nom"], [])
    possedees = _possedees(db)
    suivies = {(c.card_code, c.name_slug) for c in db.query(CarteSuivie).all()}
    v30 = reco.variations_30j(db, [p["ligne"] for p in cartes])
    medianes = _medianes_des_semblables(db, None if toutes_langues else "fr")
    en_vente = card_catalog.compteurs_d_annonces(db, [p["ligne"].id for p in cartes])

    def entree(p: dict) -> dict:
        ligne = p["ligne"]
        h7, h30 = reco.variation_7j(ligne), v30.get(_cle(p))
        mediane = medianes.get(reco._groupe_comparable(p))
        return {
            **card_catalog.carte_en_dict(ligne),
            "version": reco._NATURE_DE_VERSION.get(p["rang"], "variante"),
            "visuel": p["visuel"],
            "belle": p["poids_visuel"] >= 3,
            "exemplaires": possedees.get(_cle(p), 0),
            "suivie": _cle(p) in suivies,
            "variation_7j": h7,
            "variation_30j": h30,
            "ratio_semblables": (ligne.price_eur / mediane
                                 if mediane and ligne.price_eur and p["poids_visuel"] >= 1 else None),
            "en_vente": en_vente.get(ligne.id, {}).get("listings_count", 0),
        }

    entrees = [entree(p) for p in cartes]
    chiffrees = sorted((e for e in entrees if e["price_eur"]), key=lambda e: e["price_eur"])

    paliers = []
    for cle, titre, explication, bas, haut in PALIERS:
        dedans = [e for e in chiffrees if e["price_eur"] >= bas and (haut is None or e["price_eur"] < haut)]
        if dedans:
            paliers.append({"cle": cle, "titre": titre, "explication": explication, "cartes": dedans})
    sans_cote = sorted((e for e in entrees if not e["price_eur"]), key=lambda e: e["card_code"] or "")
    if sans_cote:
        paliers.append({"cle": "sans-cote", "titre": "Cote inconnue",
                        "explication": "La source ne publie pas encore leur prix.", "cartes": sans_cote})

    belles = [e for e in entrees if e["belle"]]
    return {
        **perso,
        "aime": perso["nom"] in reco.lire_gouts(db)["personnages"],
        "cartes": len(entrees),
        "belles": len(belles),
        "possedees": sum(1 for e in entrees if e["exemplaires"]),
        "belles_possedees": sum(1 for e in belles if e["exemplaires"]),
        "prix_min": chiffrees[0]["price_eur"] if chiffrees else None,
        "prix_max": chiffrees[-1]["price_eur"] if chiffrees else None,
        "conseils": _conseils(perso["nom"], chiffrees),
        "annonces": _annonces(db, entrees),
        "paliers": paliers,
    }


def _annonces(db: Session, entrees: List[dict]) -> List[dict]:
    """Ses cartes en vente en ce moment (Vinted, eBay), les meilleures
    affaires d'abord, chacune avec la carte qu'elle vend."""
    par_id = {e["id"]: e for e in entrees}
    annonces = card_catalog.annonces_des_cartes(db, list(par_id), limite=ANNONCES_EN_TETE)
    for a in annonces:
        e = par_id[a["card_id"]]
        a["carte"] = {k: e[k] for k in ("id", "display_name", "card_code", "version", "visuel",
                                        "price_eur", "image_url", "exemplaires", "suivie")}
    return annonces


def belles_versions_a_chasser(page: dict, budget_max: float) -> List[dict]:
    """Les belles versions qu'on n'a pas, qu'on ne suit pas encore, et dont
    la cote tient dans le budget — de la moins chere a la plus chere."""
    return [c for palier in page["paliers"] for c in palier["cartes"]
            if c["belle"] and not c["exemplaires"] and not c["suivie"]
            and c["price_eur"] and c["price_eur"] <= budget_max]


def chasser_les_belles_versions(db: Session, slug: str, budget_max: float,
                                toutes_langues: bool = False) -> Optional[dict]:
    """Ajoute a Ma liste toutes les belles versions manquantes du personnage
    dans le budget, chacune avec sa cote (arrondie a l'euro superieur) comme
    budget : la chasse Vinted les cherchera. None si le personnage n'a pas
    de page."""
    page = page_du_personnage(db, slug, toutes_langues)
    if page is None:
        return None
    cartes = belles_versions_a_chasser(page, budget_max)
    for c in cartes:
        suivi.suivre(db, c["id"], float(math.ceil(c["price_eur"])))
    return {"ajoutees": len(cartes), "cout": round(sum(c["price_eur"] for c in cartes), 2)}


def _euros(valeur: float) -> str:
    return reco._euros(valeur)


def _conseils(nom: str, chiffrees: List[dict]) -> List[dict]:
    """Ce qu'un connaisseur dirait a qui veut collectionner ce personnage.
    Une carte ne sert qu'un conseil ; un conseil sans carte n'est pas donne."""
    conseils, prises = [], set()

    def ajouter(cle: str, titre: str, carte: Optional[dict], texte: str):
        if carte is None or carte["id"] in prises:
            return
        prises.add(carte["id"])
        conseils.append({"cle": cle, "titre": titre, "texte": texte, "carte": carte})

    belles = [e for e in chiffrees if e["belle"] and not e["exemplaires"]]
    if belles:
        c = belles[0]
        ajouter("pour-commencer", "Pour commencer", c,
                f"La plus abordable de ses belles versions : {(c['visuel'] or '').lower()}, à {_euros(c['price_eur'])}.")

    sous_cotees = sorted((e for e in chiffrees if e["ratio_semblables"] is not None
                          and e["ratio_semblables"] <= reco.PART_SOUS_COTEE and not e["exemplaires"]),
                         key=lambda e: e["ratio_semblables"])
    if sous_cotees:
        c = sous_cotees[0]
        ajouter("bon-plan", "Le bon rapport", c,
                f"{round((1 - c['ratio_semblables']) * 100)}\u00a0% moins chère que les cartes comparables, "
                f"à {_euros(c['price_eur'])}.")

    def hausse(e):
        return max(e["variation_7j"] or 0, e["variation_30j"] or 0)
    montantes = sorted((e for e in chiffrees if (e["variation_7j"] or 0) >= reco.HAUSSE_7J
                        or (e["variation_30j"] or 0) >= reco.HAUSSE_30J), key=hausse, reverse=True)
    if montantes:
        c = montantes[0]
        ajouter("monte", "Ce qui monte", c,
                f"Sa cote a pris {round(hausse(c) * 100)}\u00a0% récemment ; elle est à {_euros(c['price_eur'])}. "
                "Une tendance ne garantit rien.")

    if chiffrees:
        c = chiffrees[-1]
        ajouter("graal", "Le graal", c,
                f"La pièce maîtresse d'une collection de {nom} : {_euros(c['price_eur'])}.")
    return conseils
