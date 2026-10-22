"""
Prix de référence en euros, depuis OPECards.fr.

POURQUOI CETTE PIECE
--------------------
C'était la moitié manquante. Le catalogue savait quelles cartes existent et
comment elles s'appellent en français, mais pas ce qu'elles valent — donc
aucune marge, aucun score, aucune bonne affaire. Ce module apporte le prix.

CE QUE CETTE SOURCE EST
-----------------------
Un site communautaire français qui recense les cartes One Piece et publie
leur prix en euros, relevé chez Cardmarket (son propre pied de page le dit).
C'est donc un prix de MARCHE europeen, dans la bonne devise, pour des cartes
françaises — exactement ce que la chasse aux bonnes affaires demande.

Elle donne en prime la VARIATION recente du prix, ce qui alimente la
tendance de fond sans attendre d'avoir accumulé des relevés nous-mêmes.

CE QUI A ETE OBSERVE, PAS DEVINE
--------------------------------
Ecrit contre le code source reel, relevé le 22/10/2026 et conservé dans
tests/fixtures/opecards_op15_prix.html.

LA DECOUVERTE QUI A CHANGE LE MODELE
------------------------------------
Trois entrées portent le code OP15-118-SEC :

    Ener                10,50 €
    Ener (Version 2)    22,00 €
    Ener (Version 3)   695,00 €

Soixante-six fois l'écart. Le catalogue regroupait jusqu'ici toutes les
illustrations alternatives d'un code sous une seule fiche « (Parallèle) » :
il aurait annoncé 22 € pour une carte qui en vaut 695. Cette page prouve
qu'une variante n'est pas un detail d'affichage mais une carte differente,
et le modele a ete corrige en consequence (voir cardlist_fr.py).

LA STRUCTURE
------------
Une carte = un bloc `<div class="item ..." data-item="83838">` :

    <h3 class="item-name ..." title="Ener (Version 3)">   le nom + la version
    <div class="item-subname"><span>OP15-118-SEC</span>   le code ET la rarete, colles
    <span class="item-price d-block">695.00€</span>
    <span class="item-price-difference text-success">     baisse (text-danger = hausse)
"""
import html
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from app.core.robots_compliance import is_allowed

logger = logging.getLogger(__name__)

RACINE = "https://www.opecards.fr"
DELAI = 45

USER_AGENT = (
    "Mozilla/5.0 (compatible; OnePieceDealHunter/1.0; "
    "+https://github.com/xiossfocard-wq/One-piece-)"
)

# Raretes du jeu, telles que les cases a cocher du filtre les nomment. Sert a
# separer le code de la rarete dans « OP15-118-SEC », qui les colle.
RARETES = ("DON!!", "SEC", "SR", "UC", "TR", "L", "C", "R", "P")

# Pause entre deux pages. Le site est communautaire et tenu par une petite
# equipe : on ne le martele pas pour gagner quelques secondes.
DELAI_ENTRE_PAGES = 1.5

MAX_PAGES = 60

_BLOC = re.compile(r'<div class="item [^"]*" data-item="(?P<id>\d+)"\s*>(?P<corps>.*?)'
                   r'(?=<div class="item [^"]*" data-item="\d+"\s*>|</div>\s*<div class="row mt-3">|\Z)',
                   re.S)

# Le titre de <h3> plutot que son contenu : meme valeur, sans les retours a
# la ligne et l'indentation du gabarit.
_NOM = re.compile(r'<h3 class="item-name[^"]*"[^>]*title="(?P<nom>[^"]*)"')

_SOUS_NOM = re.compile(
    r'<div class="item-subname">\s*<span[^>]*>\s*(?P<code>[^<]+?)\s*</span>', re.S)

_PRIX = re.compile(
    r'<span class="item-price d-block">\s*(?P<prix>[\d.,]+)\s*€', re.S)

# La classe dit le SENS de la variation : text-success = baisse (bonne
# nouvelle pour un acheteur), text-danger = hausse. Le signe est aussi dans
# le texte, mais la classe est plus sure : elle ne depend pas du formatage.
_VARIATION = re.compile(
    r'<span class="item-price-difference (?P<sens>text-success|text-danger)[^"]*">'
    r'.*?<span[^>]*>\s*(?P<valeur>[+-]?[\d.,]+)\s*€', re.S)

_IMAGE = re.compile(r'data-src="(?P<url>https://static\.opecards\.fr/cards/[^"]+)"')

_LIEN = re.compile(r'<a class="d-block item-main-link[^"]*"[^>]*href="(?P<url>/cards/[^"]+)"')

# « (Version 3) » en fin de nom. La version 1 n'est jamais ecrite : c'est
# l'impression ordinaire.
_VERSION = re.compile(r'\s*\(Version\s+(?P<rang>\d+)\)\s*$', re.I)

# Le menu des series, groupe par langue. Seul le groupe francais nous
# interesse : il dit quelles series existent VRAIMENT en francais.
_GROUPE = re.compile(
    r'<optgroup label="[^"]*?S[ée]ries\s+Fran[çc]aises[^"]*?">(?P<corps>.*?)</optgroup>',
    re.S | re.I)
_OPTION = re.compile(
    r'<option value="(?P<valeur>\d+)"[^>]*>(?P<libelle>.*?)</option>', re.S)

_PAGE_SUIVANTE = re.compile(r'data-page="(?P<page>\d+)"')


def _texte(brut: Optional[str]) -> str:
    if not brut:
        return ""
    decode = html.unescape(html.unescape(brut))
    sans_balises = re.sub(r"<[^>]+>", " ", decode)
    return re.sub(r"\s+", " ", sans_balises).strip()


def _nombre(brut: Optional[str]) -> Optional[float]:
    """« 695.00 » ou « 1 234,56 » -> float. None si illisible."""
    if not brut:
        return None
    texte = re.sub(r"[\s  ]", "", brut)
    if re.search(r"[^\d,.+-]", texte):
        return None
    if "," in texte and "." in texte:
        texte = (texte.replace(".", "").replace(",", ".")
                 if texte.rfind(",") > texte.rfind(".")
                 else texte.replace(",", ""))
    elif "," in texte:
        texte = texte.replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return None


def separer_code_et_rarete(brut: str) -> tuple:
    """« OP15-118-SEC » -> (« OP15-118 », « SEC »).

    Le site colle les deux dans un seul libelle. Couper betement au dernier
    tiret donnerait « OP15 » / « 118-SEC » sur certains formats : on teste
    donc contre la liste des raretes connues.
    """
    texte = (brut or "").strip()
    if not texte:
        return None, None
    for rarete in RARETES:
        suffixe = f"-{rarete}"
        if texte.upper().endswith(suffixe.upper()):
            return texte[: -len(suffixe)].strip(), rarete
    return texte, None


def rang_de_version(nom: str) -> tuple:
    """« Ener (Version 3) » -> (« Ener », 2).

    Le rang rendu est celui des ILLUSTRATIONS ALTERNATIVES, pas celui du
    site : « Version 2 » est la PREMIERE alternative, donc rang 1. C'est la
    meme numerotation que les suffixes « _p1 », « _p2 » de la liste
    officielle, ce qui permet de rapprocher les deux sources.
    """
    trouve = _VERSION.search(nom or "")
    if not trouve:
        return (nom or "").strip(), 0
    rang = int(trouve.group("rang")) - 1
    return _VERSION.sub("", nom).strip(), max(rang, 0)


@dataclass
class PrixCarte:
    card_code: str
    display_name: str          # le nom SANS la mention de version
    rang_variante: int         # 0 = impression ordinaire, 1+ = alternative
    rarity: Optional[str]
    price_eur: float
    variation_eur: Optional[float]   # negatif = baisse
    image_url: Optional[str]
    detail_url: Optional[str]


def analyser_page(contenu: str, racine: str = RACINE) -> List[PrixCarte]:
    """Extrait les prix d'une page de liste."""
    cartes: List[PrixCarte] = []

    for bloc in _BLOC.finditer(contenu):
        corps = bloc.group("corps")

        nom_brut = _NOM.search(corps)
        sous_nom = _SOUS_NOM.search(corps)
        prix = _PRIX.search(corps)

        if not (nom_brut and sous_nom and prix):
            # Un bloc sans nom, sans code ou sans prix n'est pas exploitable.
            # On le dit : un bloc avale en silence, c'est une carte qu'on
            # croit absente du site alors qu'elle y est.
            logger.warning("OPECards : bloc %s incomplet (nom=%s code=%s prix=%s)",
                           bloc.group("id"), bool(nom_brut), bool(sous_nom), bool(prix))
            continue

        code, rarete = separer_code_et_rarete(_texte(sous_nom.group("code")))
        if not code:
            continue

        nom, rang = rang_de_version(_texte(nom_brut.group("nom")))
        valeur = _nombre(prix.group("prix"))
        if valeur is None:
            logger.warning("OPECards : prix illisible pour %s (%r)",
                           code, prix.group("prix"))
            continue

        variation = None
        trouve = _VARIATION.search(corps)
        if trouve:
            brut = _nombre(trouve.group("valeur"))
            if brut is not None:
                # La classe decide du signe : le texte porte deja « - » ou
                # « + », mais s'y fier seul rendrait la lecture dependante
                # du formatage du gabarit.
                amplitude = abs(brut)
                variation = -amplitude if trouve.group("sens") == "text-success" else amplitude

        image = _IMAGE.search(corps)
        lien = _LIEN.search(corps)

        cartes.append(PrixCarte(
            card_code=code,
            display_name=nom,
            rang_variante=rang,
            rarity=rarete,
            price_eur=valeur,
            variation_eur=variation,
            image_url=image.group("url") if image else None,
            detail_url=f"{racine.rstrip('/')}{lien.group('url')}" if lien else None,
        ))

    return cartes


def series_francaises(contenu: str) -> Dict[str, str]:
    """Les series du groupe « Séries Françaises » du menu deroulant.

    C'est la reponse a une question que le site officiel laissait ouverte :
    quelles series existent vraiment en francais. Le groupe ne contient ni
    OP01 ni OP08 — le jeu francais commence a OP09.
    """
    groupe = _GROUPE.search(contenu)
    if not groupe:
        return {}
    return {
        option.group("valeur"): _texte(option.group("libelle"))
        for option in _OPTION.finditer(groupe.group("corps"))
        if option.group("valeur")
    }


def derniere_page(contenu: str) -> int:
    """Le plus grand numero de page propose par la pagination."""
    pages = [int(p) for p in _PAGE_SUIVANTE.findall(contenu)]
    return max(pages) if pages else 1


class ClientOPECards:
    def __init__(self, session: Optional[requests.Session] = None,
                 racine: str = RACINE, delai_entre_pages: float = DELAI_ENTRE_PAGES):
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._racine = racine.rstrip("/")
        self._delai = delai_entre_pages

    def url(self, page: int = 1, serie: Optional[str] = None,
            langue: str = "FR") -> str:
        chemin = "/cards" if page <= 1 else f"/cards/{page}"
        parametres = ["sortBy=priceR"]
        if serie:
            parametres.append(f"serie={serie}")
        if langue:
            parametres.append(f"language={langue}")
        return f"{self._racine}{chemin}?" + "&".join(parametres)

    def recuperer(self, page: int = 1, serie: Optional[str] = None,
                  langue: str = "FR") -> str:
        adresse = self.url(page=page, serie=serie, langue=langue)
        if not is_allowed(adresse, user_agent=USER_AGENT, session=self._session):
            raise PermissionError(f"robots.txt n'autorise pas {adresse} pour ce robot")
        reponse = self._session.get(adresse, timeout=DELAI)
        reponse.raise_for_status()
        reponse.encoding = reponse.encoding or "utf-8"
        return reponse.text

    def series(self) -> Dict[str, str]:
        return series_francaises(self.recuperer())

    def prix_de_serie(self, serie: Optional[str] = None,
                      max_pages: int = MAX_PAGES) -> List[PrixCarte]:
        """Toutes les pages d'une serie, dans l'ordre.

        On s'arrete des qu'une page ne rend plus rien : une page vide
        signifie la fin, et insister ferait des requetes pour rien.
        """
        import time

        premiere = self.recuperer(page=1, serie=serie)
        cartes = analyser_page(premiere, racine=self._racine)
        total = min(derniere_page(premiere), max_pages)

        for page in range(2, total + 1):
            if self._delai:
                time.sleep(self._delai)
            try:
                lot = analyser_page(self.recuperer(page=page, serie=serie),
                                    racine=self._racine)
            except Exception as erreur:   # noqa: BLE001
                logger.warning("OPECards : page %d de la serie %s illisible (%s)",
                               page, serie, erreur)
                break
            if not lot:
                break
            cartes.extend(lot)

        logger.info("OPECards : serie %s, %d prix sur %d page(s)",
                    serie, len(cartes), total)
        return cartes
