"""
Idees de collection : des cartes qu'un connaisseur conseillerait, pas
seulement des bonnes affaires.

CE QUE CE MODULE FAIT
---------------------
Il parcourt le catalogue chiffre et retient, dans le budget choisi, les
cartes qui reunissent ce qui fait une belle collection :

- un BEAU visuel : illustration alternative (parallele), carte SP, Treasure
  Rare, Leader parallele. On ne juge pas une image — l'interface les montre
  en grand, c'est l'oeil du collectionneur qui tranche — mais une
  illustration alternative est, par construction, la version que l'editeur
  a voulue speciale ;
- un PERSONNAGE qui compte : les icones de la serie et les personnages tres
  recherches (liste ci-dessous, graphies francaises et anglaises) ;
- un MARCHE favorable : en hausse (variation mesuree, jamais inventee), ou
  moins chere que les cartes comparables ;
- une affinite avec ce que l'utilisateur collectionne deja (« Ma liste »,
  « Ma collection »).

Chaque suggestion dit POURQUOI, en clair. Ce sont des reperes, pas des
conseils d'investissement : une tendance passee ne dit pas l'avenir, et
l'interface le rappelle.
"""
import re
import statistics
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.collectors.cardlist_fr import rang_de_parallele
from app.models import (AppSettings, CardPriceSnapshot, CartePossedee, CarteSuivie, MarketCardPrice,
                        RecommandationEcartee)
from app.services import card_catalog, card_themes
from app.services.catalog_prices import code_rarete

# --- personnages --------------------------------------------------------

# (motif sur le nom sans accents, nom affiche). Les ICONES sont les visages
# de la serie, demandes quelle que soit la carte ; les RECHERCHES ont une
# vraie base de fans, et leurs illustrations alternatives partent vite.
_ICONES = [
    (r"luffy", "Luffy"), (r"zoro|zorro", "Zoro"), (r"shanks", "Shanks"),
    (r"\bace\b", "Ace"), (r"\blaw\b|trafalgar", "Law"), (r"\bnami\b", "Nami"),
    (r"\brobin\b", "Robin"), (r"hancock", "Boa Hancock"), (r"yamato", "Yamato"),
    (r"\buta\b", "Uta"), (r"sanji", "Sanji"), (r"mihawk", "Mihawk"),
    (r"\broger\b", "Gol D. Roger"), (r"newgate|barbe blanche|whitebeard", "Barbe Blanche"),
    (r"kaido|kaidou", "Kaido"),
]
_RECHERCHES = [
    (r"\bsabo\b", "Sabo"), (r"katakuri", "Katakuri"), (r"doflamingo", "Doflamingo"),
    (r"crocodile", "Crocodile"), (r"\benel\b|\bener\b", "Ener"), (r"\bgarp\b", "Garp"),
    (r"rayleigh", "Rayleigh"), (r"kuzan|aokiji", "Kuzan"), (r"kizaru|borsalino", "Kizaru"),
    (r"akainu|sakazuki", "Akainu"), (r"\bteach\b|barbe noire|blackbeard", "Barbe Noire"),
    (r"perona", "Perona"), (r"\bvivi\b", "Vivi"), (r"carrot", "Carrot"), (r"bonney", "Bonney"),
    (r"reiju", "Reiju"), (r"\bkoby\b|\bkobby\b", "Koby"), (r"smoker", "Smoker"),
    (r"jinbe|jimbei|jinbei", "Jinbe"), (r"chopper", "Chopper"), (r"\bkid\b", "Kid"),
    (r"linlin|big mom", "Big Mom"), (r"\bmarco\b", "Marco"), (r"lucci", "Lucci"),
    (r"buggy|baggy", "Baggy"), (r"\bdragon\b", "Dragon"), (r"\boden\b", "Oden"),
    (r"hiyori", "Hiyori"), (r"rebecca", "Rebecca"), (r"\bviola\b", "Viola"),
    (r"usopp|\bpipo\b", "Usopp"), (r"franky", "Franky"), (r"\bbrook\b", "Brook"),
    (r"kalifa", "Kalifa"), (r"\bizo\b", "Izo"), (r"momonosuke", "Momonosuke"),
]
_PERSONNAGES = ([(re.compile(m), nom, 3) for m, nom in _ICONES]
                + [(re.compile(m), nom, 2) for m, nom in _RECHERCHES])


def personnage(nom_affiche: str) -> Tuple[Optional[str], int]:
    """(nom du personnage, poids 3 icone / 2 recherche), ou (None, 0)."""
    texte = card_themes._sans_accents(nom_affiche or "")
    for motif, nom, poids in _PERSONNAGES:
        if motif.search(texte):
            return nom, poids
    return None, 0


# --- visuel ---------------------------------------------------------------

def visuel(ligne: MarketCardPrice) -> Tuple[Optional[str], int]:
    """(ce qui rend la carte belle, poids). Une illustration alternative ou
    une rarete speciale ; rien pour une impression ordinaire courante."""
    rang = rang_de_parallele(ligne.name_slug)
    rarete = code_rarete(ligne.rarity) or ""
    if rang >= 2:
        return "Manga Rare : l'illustration la plus spectaculaire", 4
    if rarete in ("TR",):
        return "Treasure Rare", 4
    if rarete.startswith("SP"):
        return "Carte SP : illustration spéciale", 3
    if rang == 1 and rarete == "L":
        return "Leader en illustration alternative", 3
    if rang == 1:
        return "Illustration alternative (parallèle)", 3
    if rarete == "SEC":
        return "Secret Rare", 2
    if rarete == "SR":
        return "Super Rare", 1
    return None, 0


# --- marche ---------------------------------------------------------------

# En dessous, une variation n'est que du bruit : +0,10 EUR sur une carte a
# 0,40 EUR fait +25 % sans rien signifier.
VARIATION_MINIMALE_EUR = 0.50
HAUSSE_7J = 0.10
HAUSSE_30J = 0.15
# « Sous-cotee » : a moins de 60 % de la mediane des cartes comparables,
# mediane calculee sur au moins 5 cartes — sur moins, elle ne dit rien.
PART_SOUS_COTEE = 0.60
COMPARABLES_MINIMUM = 5
# Un connaisseur varie ses conseils : pas huit Shanks d'affilee parce que
# l'utilisateur en possede un.
PAR_PERSONNAGE_ET_RUBRIQUE = 2


def variation_7j(ligne: MarketCardPrice) -> Optional[float]:
    """La variation recente en part du prix d'avant, quand elle est connue
    et assez grande pour signifier quelque chose."""
    v, prix = ligne.variation_7d_eur, ligne.price_eur
    if v is None or prix is None or abs(v) < VARIATION_MINIMALE_EUR:
        return None
    avant = prix - v
    return v / avant if avant > 0 else None


def variations_30j(db: Session, lignes: List[MarketCardPrice]) -> Dict[Tuple, float]:
    """La variation sur environ un mois, d'apres les releves qu'on accumule
    chaque jour — seulement quand un releve a au moins une semaine."""
    if not lignes:
        return {}
    depuis = date.today() - timedelta(days=35)
    jusqu = date.today() - timedelta(days=7)
    anciens: Dict[Tuple, Tuple[date, float]] = {}
    for r in (db.query(CardPriceSnapshot)
              .filter(CardPriceSnapshot.captured_on >= depuis,
                      CardPriceSnapshot.captured_on <= jusqu)
              .all()):
        cle = (r.card_code, r.name_slug)
        if cle not in anciens or r.captured_on < anciens[cle][0]:
            anciens[cle] = (r.captured_on, r.price_eur)
    resultat = {}
    for ligne in lignes:
        cle = (ligne.card_code, ligne.name_slug)
        if cle in anciens and anciens[cle][1] > 0 and ligne.price_eur is not None:
            ecart = ligne.price_eur - anciens[cle][1]
            if abs(ecart) >= VARIATION_MINIMALE_EUR:
                resultat[cle] = ecart / anciens[cle][1]
    return resultat


def _euros(valeur: float) -> str:
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " €"


# --- les gouts declares ---------------------------------------------------

# Les styles qu'on peut preferer, et ce qui les reconnait.
STYLES = {
    "alternatives": "Illustrations alternatives",
    "leaders": "Leaders",
    "speciales": "SP, Treasure Rare et Manga",
    "secretes": "Secret Rare",
}
GOUTS_VIDES = {"personnages": [], "themes": [], "styles": []}


def style_de(p: dict) -> Optional[str]:
    """Le style de la carte, au sens de STYLES."""
    if p["rarete"] == "L":
        return "leaders"
    if p["rang"] >= 2 or p["rarete"] in ("TR",) or p["rarete"].startswith("SP"):
        return "speciales"
    if p["rang"] == 1:
        return "alternatives"
    if p["rarete"] == "SEC":
        return "secretes"
    return None


def options_de_gouts() -> dict:
    """Ce qu'on peut choisir : personnages (icones d'abord), groupes, styles."""
    return {
        "personnages": ([{"nom": nom, "calibre": "icone"} for _, nom in _ICONES]
                        + [{"nom": nom, "calibre": "recherche"} for _, nom in _RECHERCHES]),
        "themes": [{"slug": t.slug, "label": t.label} for t in card_themes.THEMES_SUJET],
        "styles": [{"cle": cle, "label": label} for cle, label in STYLES.items()],
    }


def lire_gouts(db: Session) -> dict:
    ligne = db.query(AppSettings).filter(AppSettings.key == "gouts").first()
    valeur = ligne.value if ligne is not None and isinstance(ligne.value, dict) else {}
    return {cle: list(valeur.get(cle) or []) for cle in GOUTS_VIDES}


def enregistrer_gouts(db: Session, personnages: List[str], themes: List[str], styles: List[str]) -> dict:
    """N'enregistre que des valeurs connues : un nom mal orthographie ne
    correspondrait a aucune carte, en silence."""
    options = options_de_gouts()
    noms = {o["nom"] for o in options["personnages"]}
    slugs = {o["slug"] for o in options["themes"]}
    gouts = {
        "personnages": [n for n in dict.fromkeys(personnages) if n in noms],
        "themes": [t for t in dict.fromkeys(themes) if t in slugs],
        "styles": [st for st in dict.fromkeys(styles) if st in STYLES],
    }
    db.merge(AppSettings(key="gouts", value=gouts))
    db.commit()
    return gouts


# --- la recommandation ----------------------------------------------------

def _profil(ligne: MarketCardPrice) -> dict:
    perso, poids_perso = personnage(ligne.display_name)
    beau, poids_visuel = visuel(ligne)
    return {"ligne": ligne, "perso": perso, "poids_perso": poids_perso,
            "visuel": beau, "poids_visuel": poids_visuel,
            "rang": rang_de_parallele(ligne.name_slug),
            "rarete": code_rarete(ligne.rarity) or "?",
            "themes": card_themes.decoder_themes(ligne.theme_slugs)}


def _groupe_comparable(p: dict) -> Tuple:
    """Les cartes auxquelles une carte se compare : meme version (ordinaire
    ou alternative), meme rarete, personnage du meme calibre."""
    return (p["rang"] >= 1, p["rarete"], p["poids_perso"])


def _avis(p: dict, raisons: List[dict]) -> str:
    """Le verdict de l'expert, en une phrase. Les raisons detaillees sont
    deja affichees a part ; la phrase dit ce qu'on en retient, par ordre
    d'importance : ce qui prolonge sa collection, la bonne affaire relative,
    la cote qui monte, la belle version d'un personnage."""
    ligne = p["ligne"]
    prix = _euros(ligne.price_eur)
    nom = p["perso"] or ligne.display_name
    types = {r["type"] for r in raisons}
    belle = p["poids_visuel"] >= 3
    if "gout" in types and p["perso"] and belle:
        return f"Pour ta collection de {p['perso']} : une belle version, à {prix}."
    if "collection" in types and p["perso"]:
        return f"Elle prolongerait bien tes cartes de {p['perso']}, pour {prix}."
    if "sous-cotee" in types:
        return f"Une belle version de {nom} pour {prix}, bien en dessous de ses semblables."
    if "tendance" in types:
        return f"Sa cote monte : cette carte de {nom} est à {prix} aujourd'hui."
    if belle and p["poids_perso"] == 3:
        return f"Une des plus belles versions de {nom}, à {prix}."
    if belle and p["perso"]:
        return f"Une belle illustration de {nom}, personnage très recherché, à {prix}."
    if belle:
        return f"Un beau visuel accessible, à {prix}."
    return f"{nom}, à {prix}."


def recommander(db: Session, budget_max: float = 20.0, toutes_langues: bool = False,
                limite: int = 8) -> dict:
    """Les idees de collection, par rubrique, dans le budget."""
    requete = db.query(MarketCardPrice).filter(MarketCardPrice.price_eur.isnot(None),
                                               MarketCardPrice.price_eur > 0)
    if not toutes_langues:
        # Les cartes francaises : le jeu francais commence a OP09, les series
        # anterieures n'existent qu'en anglais (voir core/langues).
        requete = requete.filter(MarketCardPrice.language == "fr")
    lignes = requete.all()

    possedees = {(c.card_code, c.name_slug) for c in db.query(CartePossedee).all()}
    suivies = {(c.card_code, c.name_slug) for c in db.query(CarteSuivie).all()}
    gouts = lire_gouts(db)
    persos_aimes, themes_aimes, styles_aimes = (set(gouts["personnages"]), set(gouts["themes"]),
                                                 set(gouts["styles"]))
    ecartees = {(c.card_code, c.name_slug) for c in db.query(RecommandationEcartee).all()}

    profils = [_profil(l) for l in lignes]

    # Les gouts de l'utilisateur, lus dans ce qu'il possede et suit deja.
    # Possede et suivi sont comptes a part : « tu as deja » ne vaut que pour
    # ce qu'il a vraiment.
    # Lus sur TOUTES les cartes possedees et suivies, pas seulement celles
    # qu'on examine : un Shanks d'OP01, serie sans version francaise, dit
    # autant le gout de l'utilisateur qu'un Shanks d'OP10.
    cles_deja = possedees | suivies
    deja = [_profil(l) for l in db.query(MarketCardPrice).all()
            if (l.card_code, l.name_slug) in cles_deja] if cles_deja else []
    perso_possede: Dict[str, int] = {}
    perso_suivi: Dict[str, int] = {}
    gouts_theme: Dict[str, int] = {}
    for p in deja:
        cle_p = (p["ligne"].card_code, p["ligne"].name_slug)
        if p["perso"]:
            compte = perso_possede if cle_p in possedees else perso_suivi
            compte[p["perso"]] = compte.get(p["perso"], 0) + 1
        for t in p["themes"]:
            if card_themes.theme_par_slug(t) and card_themes.theme_par_slug(t).famille == "sujet":
                gouts_theme[t] = gouts_theme.get(t, 0) + 1
    gouts_perso = {n: perso_possede.get(n, 0) + perso_suivi.get(n, 0)
                   for n in set(perso_possede) | set(perso_suivi)}

    # Mediane des cartes comparables, sur TOUT le catalogue chiffre (pas
    # seulement le budget) : c'est le marche de reference.
    par_groupe: Dict[Tuple, List[float]] = {}
    for p in profils:
        if p["poids_visuel"] >= 1:
            par_groupe.setdefault(_groupe_comparable(p), []).append(p["ligne"].price_eur)
    medianes = {g: statistics.median(v) for g, v in par_groupe.items() if len(v) >= COMPARABLES_MINIMUM}

    dans_budget = [p for p in profils
                   if p["ligne"].price_eur <= budget_max
                   and (p["ligne"].card_code, p["ligne"].name_slug) not in possedees | ecartees]
    v30 = variations_30j(db, [p["ligne"] for p in dans_budget])
    compteurs = card_catalog.compteurs_d_annonces(db, [p["ligne"].id for p in dans_budget])

    candidats = []
    for p in dans_budget:
        ligne = p["ligne"]
        cle = (ligne.card_code, ligne.name_slug)
        raisons = []
        if p["visuel"]:
            raisons.append({"type": "visuel", "texte": p["visuel"]})
        if p["perso"]:
            raisons.append({"type": "personnage", "texte": (
                f"{p['perso']} : une icône de la série" if p["poids_perso"] == 3
                else f"{p['perso']} : personnage très recherché")})
        h7, h30 = variation_7j(ligne), v30.get(cle)
        en_hausse = (h7 is not None and h7 >= HAUSSE_7J) or (h30 is not None and h30 >= HAUSSE_30J)
        if h7 is not None and h7 >= HAUSSE_7J:
            raisons.append({"type": "tendance", "texte": f"en hausse de {round(h7 * 100)} % ces derniers jours"})
        elif h30 is not None and h30 >= HAUSSE_30J:
            raisons.append({"type": "tendance", "texte": f"en hausse de {round(h30 * 100)} % sur un mois"})
        mediane = medianes.get(_groupe_comparable(p))
        ratio = ligne.price_eur / mediane if mediane else None
        if ratio is not None and ratio <= PART_SOUS_COTEE and p["poids_visuel"] >= 1:
            raisons.append({"type": "sous-cotee", "texte": (
                f"{round((1 - ratio) * 100)} % moins chère que les cartes comparables "
                f"(médiane {_euros(mediane)})")})
        annonces = compteurs.get(ligne.id, {}).get("listings_count", 0)
        if annonces:
            raisons.append({"type": "vinted", "texte": (
                f"{annonces} annonce{'s' if annonces > 1 else ''} en vente en ce moment")})
        # L'affinite, SANS la carte elle-meme : une carte suivie ne doit pas
        # se recommander « parce que tu suis deja une carte de Shanks ».
        lui_meme = 1 if cle in suivies else 0
        perso_ailleurs = (gouts_perso.get(p["perso"], 0) - lui_meme) if p["perso"] else 0
        themes_ailleurs = {t: gouts_theme.get(t, 0) - lui_meme for t in p["themes"]
                           if gouts_theme.get(t, 0) - lui_meme > 0}
        affinite = perso_ailleurs + sum(themes_ailleurs.values())
        if perso_ailleurs > 0:
            possede = perso_possede.get(p["perso"], 0)
            if possede:
                raisons.append({"type": "collection", "texte": (
                    f"tu as déjà {possede} carte{'s' if possede > 1 else ''} de {p['perso']}")})
            else:
                raisons.append({"type": "collection", "texte": (
                    f"tu suis déjà {perso_ailleurs} carte{'s' if perso_ailleurs > 1 else ''} de {p['perso']}")})
        elif affinite:
            theme = max(themes_ailleurs, key=lambda t: themes_ailleurs[t])
            raisons.append({"type": "collection", "texte": (
                f"dans la lignée de ta collection : {card_themes.theme_par_slug(theme).label}")})

        # Ce que l'utilisateur a DIT aimer pese plus que ce qu'on devine.
        perso_aime = p["perso"] in persos_aimes
        themes_communs = [t for t in p["themes"] if t in themes_aimes]
        style_aime = style_de(p) in styles_aimes
        if perso_aime:
            raisons.insert(0, {"type": "gout", "texte": f"{p['perso']} : un de tes personnages préférés"})
        elif themes_communs:
            raisons.insert(0, {"type": "gout", "texte": (
                f"{card_themes.theme_par_slug(themes_communs[0]).label} : un de tes groupes préférés")})
        gout = (4 if perso_aime else 0) + (3 if themes_communs else 0) + (2 if style_aime else 0)

        candidats.append({
            "p": p, "raisons": raisons, "en_hausse": en_hausse, "h7": h7, "h30": h30,
            "ratio": ratio, "annonces": annonces, "affinite": affinite,
            "suivie": cle in suivies, "gout": gout, "aime": perso_aime or bool(themes_communs),
            # L'attrait : ce qui fait qu'un connaisseur s'y arrete.
            "attrait": p["poids_visuel"] * 2 + p["poids_perso"] * 2 + min(affinite, 3) * 2
                       + (2 if en_hausse else 0) + (1 if annonces else 0) + gout,
        })

    def sortie(c: dict) -> dict:
        carte = card_catalog.carte_en_dict(c["p"]["ligne"], {"listings_count": c["annonces"]})
        return {**carte, "raisons": c["raisons"], "avis": _avis(c["p"], c["raisons"]),
                "suivie": c["suivie"], "variation_7j": c["h7"], "variation_30j": c["h30"]}

    # Une carte n'apparait qu'une fois, dans la premiere rubrique qui la
    # retient : ses autres atouts sont deja dits par ses raisons. Les
    # rubriques suivantes montrent ainsi d'AUTRES cartes.
    deja_montrees = set()

    def rubrique(cle: str, titre: str, explication: str, choisis: List[dict]) -> Optional[dict]:
        retenus, par_perso = [], {}
        for c in choisis:
            if c["p"]["ligne"].id in deja_montrees:
                continue
            perso = c["p"]["perso"]
            if perso and par_perso.get(perso, 0) >= PAR_PERSONNAGE_ET_RUBRIQUE:
                continue
            retenus.append(c)
            if perso:
                par_perso[perso] = par_perso.get(perso, 0) + 1
            if len(retenus) >= limite:
                break
        if not retenus:
            return None
        deja_montrees.update(c["p"]["ligne"].id for c in retenus)
        return {"cle": cle, "titre": titre, "explication": explication,
                "cartes": [sortie(c) for c in retenus]}

    beaux = [c for c in candidats if c["p"]["poids_visuel"] >= 2 and c["p"]["poids_perso"] >= 2]
    beaux.sort(key=lambda c: (-c["attrait"], c["p"]["ligne"].price_eur))

    hausses = [c for c in candidats if c["en_hausse"]
               and (c["p"]["poids_visuel"] >= 1 or c["p"]["poids_perso"] >= 2)]
    hausses.sort(key=lambda c: -max(c["h7"] or 0, c["h30"] or 0))

    # Seulement les personnages qui comptent : une illustration alternative
    # d'un figurant peu connu est bon marche parce qu'elle est peu demandee.
    sous_cotees = [c for c in candidats if c["ratio"] is not None and c["ratio"] <= PART_SOUS_COTEE
                   and c["p"]["poids_visuel"] >= 1 and c["p"]["poids_perso"] >= 2]
    sous_cotees.sort(key=lambda c: (c["ratio"], -c["attrait"]))

    pour_toi = [c for c in candidats if c["affinite"] and c["p"]["poids_visuel"] >= 2]
    pour_toi.sort(key=lambda c: (-c["affinite"], -c["attrait"]))

    # Ce qui prolonge sa collection passe en premier quand il en a une :
    # c'est la suggestion la plus personnelle. Sans elle, les coups de coeur.
    def personnelle():
        return rubrique("pour-ta-collection", "Pour ta collection",
                        "Dans la lignée de ce que tu possèdes et suis déjà.", pour_toi)

    selon_gouts = [c for c in candidats if c["aime"] and c["p"]["poids_visuel"] >= 2]
    selon_gouts.sort(key=lambda c: (-c["gout"], -c["attrait"], c["p"]["ligne"].price_eur))

    rubriques = []
    if persos_aimes or themes_aimes:
        rubriques.append(rubrique("selon-tes-gouts", "Selon tes goûts",
                                  "Les plus belles versions de tes personnages et groupes préférés.",
                                  selon_gouts))
    if gouts_perso or gouts_theme:
        rubriques.append(personnelle())
    rubriques += [
        rubrique("coups-de-coeur", "Coups de cœur accessibles",
                 f"Les plus belles cartes des personnages qui comptent, à moins de {_euros(budget_max)}.", beaux),
        rubrique("en-hausse", "En hausse, encore abordables",
                 "Leur cote monte. Une tendance passée ne garantit rien : c'est un signal, pas une promesse.",
                 hausses),
        rubrique("sous-cotees", "Moins chères que leurs semblables",
                 "De beaux visuels de personnages qui comptent, comparés aux cartes de même version, même "
                 "rareté et personnage du même calibre.", sous_cotees),
    ]
    rubriques = [r for r in rubriques if r]

    return {"budget_max": budget_max, "toutes_langues": toutes_langues,
            "cartes_examinees": len(dans_budget), "rubriques": rubriques, "gouts": gouts,
            "projets": projets(profils, gouts, budget_max, possedees, suivies),
            "themes": idees_de_collection(profils, budget_max, possedees)}


def projets(profils: List[dict], gouts: dict, budget_max: float, possedees: set, suivies: set) -> List[dict]:
    """Pour chaque personnage et groupe prefere : ou en est la collection de
    ses belles versions, ce qu'il manque dans le budget, et par quoi
    continuer — la moins chere des belles versions manquantes."""
    def projet(nature: str, nom: str, cartes: List[dict]) -> Optional[dict]:
        if not cartes:
            return None
        cle = lambda p: (p["ligne"].card_code, p["ligne"].name_slug)
        possedees_ici = [p for p in cartes if cle(p) in possedees]
        manquantes = sorted((p for p in cartes if cle(p) not in possedees), key=lambda p: p["ligne"].price_eur)
        dans_budget = [p for p in manquantes if p["ligne"].price_eur <= budget_max]
        hors_budget = [p for p in manquantes if p["ligne"].price_eur > budget_max]
        prochaine = dans_budget[0] if dans_budget else None
        return {
            "nature": nature, "nom": nom,
            "total": len(cartes), "possedees": len(possedees_ici),
            "manquantes_budget": len(dans_budget),
            "cout_budget": round(sum(p["ligne"].price_eur for p in dans_budget), 2),
            "hors_budget": len(hors_budget),
            "hors_budget_des": hors_budget[0]["ligne"].price_eur if hors_budget else None,
            "prochaine": None if prochaine is None else {
                **card_catalog.carte_en_dict(prochaine["ligne"]),
                "suivie": cle(prochaine) in suivies,
                "visuel": prochaine["visuel"],
            },
        }

    # Les belles versions : illustrations alternatives, SP, TR, Manga,
    # Leaders paralleles — ce qui fait une collection qu'on montre.
    belles = [p for p in profils if p["poids_visuel"] >= 3]
    resultat = [projet("personnage", nom, [p for p in belles if p["perso"] == nom])
                for nom in gouts["personnages"]]
    for slug in gouts["themes"]:
        theme = card_themes.theme_par_slug(slug)
        if theme is not None:
            resultat.append(projet("theme", theme.label, [p for p in belles if slug in p["themes"]]))
    return [p for p in resultat if p]


def idees_de_collection(profils: List[dict], budget_max: float, possedees: set) -> List[dict]:
    """Des projets de collection a theme : les belles versions d'un equipage
    ou d'un groupe, chacune dans le budget, et ce que coute l'ensemble."""
    idees = []
    for theme in card_themes.THEMES_SUJET:
        cartes = [p for p in profils if theme.slug in p["themes"] and p["poids_visuel"] >= 3
                  and p["ligne"].price_eur <= budget_max]
        if len(cartes) < 3:
            continue
        cartes.sort(key=lambda p: (-p["poids_perso"], p["ligne"].price_eur))
        deja = sum(1 for p in cartes if (p["ligne"].card_code, p["ligne"].name_slug) in possedees)
        idees.append({
            "slug": theme.slug, "label": theme.label, "description": theme.description,
            "nombre": len(cartes), "deja": deja,
            "total_eur": round(sum(p["ligne"].price_eur for p in cartes), 2),
            "apercu": [card_catalog.carte_en_dict(p["ligne"]) for p in cartes[:4]],
        })
    idees.sort(key=lambda i: (-i["nombre"], i["total_eur"]))
    return idees[:6]


# --- une carte, vue par l'expert -------------------------------------------

_NATURE_DE_VERSION = {0: "ordinaire", 1: "parallèle", 2: "manga"}


def versions_de_la_carte(db: Session, ligne: MarketCardPrice) -> List[dict]:
    """Toutes les versions d'un meme code — ordinaire, paralleles, manga —
    avec leur cote, et ce que l'utilisateur en possede ou suit : de quoi
    choisir laquelle viser."""
    possedees = {}
    for c in db.query(CartePossedee).filter(CartePossedee.card_code == ligne.card_code).all():
        possedees[c.name_slug] = possedees.get(c.name_slug, 0) + 1
    suivies = {c.name_slug for c in db.query(CarteSuivie).filter(CarteSuivie.card_code == ligne.card_code).all()}
    lignes = db.query(MarketCardPrice).filter(MarketCardPrice.card_code == ligne.card_code).all()
    versions = []
    for v in sorted(lignes, key=lambda v: (rang_de_parallele(v.name_slug), v.name_slug)):
        rang = rang_de_parallele(v.name_slug)
        versions.append({
            "id": v.id, "display_name": v.display_name, "rang": rang,
            "nature": _NATURE_DE_VERSION.get(rang, "variante"),
            "price_eur": v.price_eur, "image_url": v.image_url,
            "exemplaires": possedees.get(v.name_slug, 0), "suivie": v.name_slug in suivies,
            "actuelle": v.id == ligne.id,
        })
    return versions


def analyse_de_la_carte(db: Session, ligne: MarketCardPrice) -> dict:
    """Ce qu'un connaisseur dirait de cette carte : ses atouts et un verdict,
    avec les memes regles que les idees de collection."""
    p = _profil(ligne)
    raisons = []
    gouts = lire_gouts(db)
    if p["perso"] in gouts["personnages"]:
        raisons.append({"type": "gout", "texte": f"{p['perso']} : un de tes personnages préférés"})
    else:
        communs = [t for t in p["themes"] if t in gouts["themes"]]
        if communs:
            raisons.append({"type": "gout", "texte": (
                f"{card_themes.theme_par_slug(communs[0]).label} : un de tes groupes préférés")})
    if p["visuel"]:
        raisons.append({"type": "visuel", "texte": p["visuel"]})
    if p["perso"]:
        raisons.append({"type": "personnage", "texte": (
            f"{p['perso']} : une icône de la série" if p["poids_perso"] == 3
            else f"{p['perso']} : personnage très recherché")})
    if ligne.price_eur is None:
        return {"raisons": raisons, "avis": None}

    h7 = variation_7j(ligne)
    h30 = variations_30j(db, [ligne]).get((ligne.card_code, ligne.name_slug))
    if h7 is not None and h7 >= HAUSSE_7J:
        raisons.append({"type": "tendance", "texte": f"en hausse de {round(h7 * 100)} % ces derniers jours"})
    elif h30 is not None and h30 >= HAUSSE_30J:
        raisons.append({"type": "tendance", "texte": f"en hausse de {round(h30 * 100)} % sur un mois"})

    if p["poids_visuel"] >= 1:
        groupe = _groupe_comparable(p)
        semblables = [_profil(l) for l in db.query(MarketCardPrice).filter(
            MarketCardPrice.price_eur.isnot(None), MarketCardPrice.price_eur > 0,
            MarketCardPrice.language == ligne.language).all()]
        prix = [q["ligne"].price_eur for q in semblables
                if q["poids_visuel"] >= 1 and _groupe_comparable(q) == groupe]
        if len(prix) >= COMPARABLES_MINIMUM:
            mediane = statistics.median(prix)
            ratio = ligne.price_eur / mediane
            if ratio <= PART_SOUS_COTEE and p["poids_perso"] >= 2:
                raisons.append({"type": "sous-cotee", "texte": (
                    f"{round((1 - ratio) * 100)} % moins chère que les cartes comparables "
                    f"(médiane {_euros(mediane)})")})
    return {"raisons": raisons, "avis": _avis(p, raisons)}
