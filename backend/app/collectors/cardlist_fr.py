"""
Liste officielle des cartes, en FRANÇAIS.

POURQUOI CETTE PIECE
--------------------
Le catalogue tenait ses noms d'un releve de la liste ANGLAISE. Pour les
personnages cela passait — « Roronoa Zoro » s'ecrit pareil des deux cotes —
mais c'est faux en general, et faux la ou ca compte :

    anglais « Buggy »                  francais « Baggy »
    anglais « Hive »                   francais « Ruche »
    anglais « Three Sweet Commanders » francais « Trois generaux sucres »

Les cartes Evenement sont integralement traduites. Un vendeur francais qui
ecrit « Baggy » dans son annonce ne rencontrait donc JAMAIS la fiche, et
l'annonce retombait sur un rapprochement par code — quand le code y etait.

Ce module lit la liste francaise et corrige les noms a la source.

CE QUI A ETE OBSERVE, PAS DEVINE
--------------------------------
Le code ci-dessous est ecrit contre le code source reel de
`fr.onepiece-cardgame.com/cardlist/?series=...`, releve le 22/10/2026 et
conserve dans tests/fixtures/cardlist_fr_op17.html. C'est une precaution
apprise a ses depens : la premiere source du projet (ZebraDex) avait ete
parsee a l'aveugle, et ne couvrait tout simplement pas One Piece.

La page est rendue par le SERVEUR : toutes les cartes sont dans le HTML, il
n'y a pas de JavaScript a executer. Une simple requete suffit.

LA STRUCTURE
------------
Une carte = un bloc `<dl class="modalCol" id="...">`. L'identifiant porte la
VARIANTE, le code seul ne la porte pas :

    id="OP17-001"       l'impression ordinaire
    id="OP17-001_p1"    une illustration alternative
    id="OP17-005_p2"    une autre

    <div class="infoCol"><span>CODE</span> | <span>RARETE</span> | <span>TYPE</span></div>
    <div class="cardName">NOM FRANCAIS</div>
    <img ... data-src="../images/cardlist/card/OP17-001.webp?261007">
    <div class="getInfo"><h3>Extension</h3>NOM DE LA SERIE [OP-17]</div>

Le `<span>` du code est identique pour toutes les variantes d'une carte :
c'est l'id du bloc, et lui seul, qui les distingue.
"""
import html
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

from app.config import settings
from app.core.robots_compliance import is_allowed

logger = logging.getLogger(__name__)

RACINE = "https://fr.onepiece-cardgame.com"
CHEMIN_LISTE = "/cardlist/"
DELAI = 45

USER_AGENT = (
    "Mozilla/5.0 (compatible; OnePieceDealHunter/1.0; "
    "+https://github.com/xiossfocard-wq/One-piece-)"
)

# Marque de variante dans le nom affiche. Le slug qui en decoule
# (« roronoa-zoro-parallele ») est exactement celui que title_parser tire
# d'un titre d'annonce francais « Roronoa Zoro parallele OP01-001 » : les
# deux bouts de la chaine se rencontrent sans table de correspondance.
MARQUE_ALTERNATIVE = "Parallèle"


def nom_avec_variante(nom: str, rang: int) -> str:
    """« Ener », 2 -> « Ener (Parallèle 2) ». Rang 0 = impression ordinaire.

    Le RANG est dans le nom, pas seulement la mention « Parallèle ». Verifie
    le 22/10/2026 sur OPECards : les trois impressions de OP15-118-SEC
    valent 10,50 €, 22,00 € et 695,00 €. Les regrouper sous une seule fiche
    « (Parallèle) », comme le faisait la version precedente, revenait a
    annoncer 22 € pour une carte qui en vaut 695.
    """
    return f"{nom} ({MARQUE_ALTERNATIVE} {rang})" if rang else nom


def rang_de_parallele(name_slug: Optional[str]) -> int:
    """Rang de variante lu dans un slug. 0 si c'est l'impression ordinaire.

    « ener »              -> 0
    « ener-parallele-2 »  -> 2
    « ener-parallele »    -> 1   (ancienne forme, sans rang)
    """
    slug = (name_slug or "").lower()
    trouve = re.search(r"-(?:parallele|alternative|alt)(?:-(\d+))?$", slug)
    if not trouve:
        return 0
    return int(trouve.group(1)) if trouve.group(1) else 1

# Series proposees par le menu deroulant du site, relevees le 22/10/2026.
#
# Pourquoi les graver ici alors que le site les publie : la liste sert de
# REPLI. Sans elle, une seule requete qui echoue (le menu) emporte tout le
# chargement, et l'utilisateur se retrouve avec un catalogue anglais sans
# comprendre pourquoi. Le menu reste interroge en premier — il restera a
# jour quand de nouvelles series sortiront — mais son echec ne bloque plus.
#
# Ce que cette liste dit aussi, et qui ne se lit nulle part ailleurs : le
# jeu francais n'a PAS de series OP01 a OP08. Il commence a OP09.
SERIES_CONNUES = {
    "622302": "One Piece Card The Best Vol.2 (PRB-02)",
    "622301": "One Piece Card The Best (PRB-01)",
    "622203": "One Piece Heroines Edition (EB-03)",
    "622202": "Anime 25th Collection (EB-02)",
    "622117": "Les Guerriers les plus Puissants au Monde (OP-17)",
    "622116": "L'heure de la Bataille Décisive (OP-16)",
    "622115": "Aventure sur l'Île de Dieu (OP15-EB04)",
    "622114": "Les Sept de la Mer d'Azur (OP14-EB04)",
    "622113": "Successeurs (OP-13)",
    "622112": "L'Héritage du Maître (OP-12)",
    "622111": "Des Poings Vifs comme l'Éclair (OP-11)",
    "622110": "Sang Royal (OP-10)",
    "622109": "Les Nouveaux Empereurs (OP-09)",
    "622036": "Eustass \"Captain\" Kidd — Jaune (ST-36)",
    "622035": "Sabo — Rouge/Noir (ST-35)",
    "622034": "Charlotte Katakuri — Violet (ST-34)",
    "622033": "Kuzan — Bleu (ST-33)",
    "622032": "Roronoa Zoro — Vert (ST-32)",
    "622031": "Monkey D. Luffy — Rouge (ST-31)",
    "622030": "Luffy et Ace (ST-30)",
    "622029": "Egg Head (ST-29)",
    "622028": "Yamato — Vert/Jaune (ST-28)",
    "622027": "Marshall D. Teach — Noir (ST-27)",
    "622026": "Monkey D. Luffy — Violet/Noir (ST-26)",
    "622025": "Baggy — Bleu (ST-25)",
    "622024": "Jewelry Bonney — Vert (ST-24)",
    "622023": "Shanks — Rouge (ST-23)",
    "622022": "Ace et Newgate (ST-22)",
    "622021": "Gear 5th (ST-21)",
    "622020": "Charlotte Katakuri — Jaune (ST-20)",
    "622019": "Smoker — Noir (ST-19)",
    "622018": "Monkey D. Luffy — Violet (ST-18)",
    "622017": "Don Quijote Doflamingo — Bleu (ST-17)",
    "622016": "Uta — Vert (ST-16)",
    "622015": "Edward Newgate — Rouge (ST-15)",
    "622901": "Cartes promo",
    "622801": "Cartes d'autres produits",
}

# --- Motifs, tires du code source observe -------------------------------

# Un bloc carte complet. `.*?` non gourmand : les blocs se suivent, et un
# motif gourmand avalerait toute la page d'un coup.
_BLOC = re.compile(
    r'<dl class="modalCol" id="(?P<id>[^"]+)">(?P<corps>.*?)</dl>',
    re.S,
)

# Les trois <span> de infoCol : code, rarete, type de carte.
_INFO = re.compile(
    r'<div class="infoCol">\s*'
    r'<span>(?P<code>[^<]*)</span>\s*\|\s*'
    r'<span>(?P<rarete>[^<]*)</span>\s*\|\s*'
    r'<span>(?P<type>[^<]*)</span>',
    re.S,
)

_NOM = re.compile(r'<div class="cardName">(?P<nom>.*?)</div>', re.S)

# L'adresse de l'illustration. `data-src` et non `src` : le site charge les
# images en differe, et `src` ne porte qu'un GIF de remplissage.
_IMAGE = re.compile(r'data-src="(?P<url>[^"]*?/cardlist/card/[^"]+)"')

_EXTENSION = re.compile(
    r'<div class="getInfo"><h3>Extension</h3>(?P<serie>.*?)</div>', re.S)

# Les series proposees par le menu deroulant : la liste de ce qui existe
# en francais, telle que l'editeur la publie.
_SERIE_OPTION = re.compile(
    r'<option value="(?P<valeur>\d+)"[^>]*>(?P<libelle>.*?)</option>', re.S)

_NOMBRE_RESULTATS = re.compile(r'<div class="countCol">\s*(\d+)')

# Suffixe de variante dans l'id du bloc.
_SUFFIXE_VARIANTE = re.compile(r'_p(\d+)$')


def _texte(brut: Optional[str]) -> str:
    """Nettoie un fragment HTML : entites decodees, balises retirees.

    Les noms de cartes en portent vraiment : `J&#039;ai aucune envie...`,
    `Capone &quot;Gang&quot; Bege`. Sans ce decodage on enregistrerait
    l'apostrophe sous forme d'entite, et le slug en serait defigure.
    """
    if not brut:
        return ""
    # DECODER D'ABORD, retirer les balises ENSUITE. L'ordre inverse laisse
    # passer les balises ECHAPPEES : les libelles de series contiennent
    # « &lt;br class=&quot;spInline&quot;&gt; », qui ne devient une balise
    # qu'au decodage — trop tard pour le filtre si celui-ci est deja passe.
    #
    # Deux passes de decodage : certains libelles sont encodes deux fois
    # (« L&amp;apos;HÉRITAGE »).
    decode = html.unescape(html.unescape(brut))
    sans_balises = re.sub(r"<[^>]+>", " ", decode)
    return re.sub(r"\s+", " ", sans_balises).strip()


def _nettoyer_serie(brut: Optional[str]) -> Optional[str]:
    """« BOOSTER -SANG ROYAL- [OP-10] » -> « Sang Royal (OP-10) »."""
    texte = _texte(brut)
    if not texte or texte == "-":
        return None

    code = None
    trouve = re.search(r"\[([^\]]+)\]\s*$", texte)
    if trouve:
        code = trouve.group(1).strip()
        texte = texte[: trouve.start()].strip()

    # Le prefixe de produit (« BOOSTER », « DECK POUR DÉBUTANT ») est retire :
    # le nom propre de la serie suffit a l'identifier, et le code entre
    # parentheses dit deja de quel type de produit il s'agit.
    texte = re.sub(
        r"^(PREMIUM\s+BOOSTER|EXTRA\s+BOOSTER|BOOSTER|DECK\s+DE\s+DÉMARRAGE(?:\s+EX)?"
        r"|DECK\s+POUR\s+DÉ(?:BUTANT|MARRAGE))\s*",
        "", texte, flags=re.I,
    ).strip()
    texte = texte.strip("-").strip()

    if texte and texte == texte.upper():
        texte = re.sub(r"[A-ZÀ-Þ][A-ZÀ-Þ’'ʼ]*",
                       lambda m: m.group(0).capitalize(), texte)
        LIAISONS = {"de", "du", "des", "la", "le", "les", "au", "aux", "en",
                    "et", "d", "l", "a", "sur", "dans", "plus"}
        mots = texte.split(" ")
        texte = " ".join(
            mot if i == 0 or mot.lower() not in LIAISONS else mot.lower()
            for i, mot in enumerate(mots)
        )

    if not texte:
        return code
    return f"{texte} ({code})" if code else texte


@dataclass
class CarteFR:
    """Une fiche telle que la liste officielle francaise la publie."""
    card_code: str          # « OP17-001 », identique pour toutes les variantes
    display_name: str       # le nom FRANCAIS, suffixe « (Parallèle) » si besoin
    rarity: Optional[str]
    card_type: Optional[str]      # LEADER | PERSONNAGE | ÉVÉNEMENTS | LIEU
    series_name: Optional[str]
    image_url: Optional[str]
    rang_variante: int            # 0 = impression ordinaire, 1+ = alternative

    def en_ligne_d_import(self) -> dict:
        """Au contrat de services/catalog_import.

        Pas de `price_eur` : cette source dit quelles cartes existent, pas
        ce qu'elles valent. La colonne est laissee vide plutot que remplie
        d'un zero qui se lirait comme « cette carte ne vaut rien ».
        """
        return {
            "card_code": self.card_code,
            "display_name": self.display_name,
            "series_name": self.series_name,
            "rarity": self.rarity,
            "price_eur": "",
        }


def analyser_page(contenu: str, racine: str = RACINE) -> List[CarteFR]:
    """Extrait les cartes d'une page de liste.

    Chaque variante donne sa PROPRE fiche, numerotee.

    La version precedente les regroupait sous une seule fiche « (Parallèle) »,
    au motif qu'une annonce francaise dit « parallele » sans preciser
    laquelle. Le releve des prix a montre que ce raisonnement coutait cher :
    les trois impressions de OP15-118-SEC valent 10,50 €, 22,00 € et
    695,00 €. Regrouper, c'etait accepter de se tromper d'un facteur
    soixante-six sur le prix de reference.

    L'ambiguite d'une annonce qui ne precise pas sa version est reelle, mais
    elle se traite la ou elle se pose — au rapprochement, qui sait deja
    signaler un ecart de prix suspect entre homonymes — et non en effacant
    l'information a la source.
    """
    cartes: List[CarteFR] = []
    deja_vues = set()

    for bloc in _BLOC.finditer(contenu):
        identifiant = bloc.group("id")
        corps = bloc.group("corps")

        info = _INFO.search(corps)
        nom = _NOM.search(corps)
        if not info or not nom:
            # Un bloc dont le code ou le nom manque n'est pas une carte
            # exploitable. On le signale plutot que de l'avaler : c'est le
            # genre de silence qui laisse croire qu'une page a ete lue.
            logger.warning("Liste FR : bloc « %s » sans code ou sans nom, ignore",
                           identifiant)
            continue

        code = _texte(info.group("code"))
        nom_fr = _texte(nom.group("nom"))
        if not code or not nom_fr:
            continue

        suffixe = _SUFFIXE_VARIANTE.search(identifiant)
        rang = int(suffixe.group(1)) if suffixe else 0

        cle = (code.upper(), rang)
        if cle in deja_vues:
            continue
        deja_vues.add(cle)

        image = _IMAGE.search(corps)
        url_image = urljoin(f"{racine}/cardlist/", image.group("url")) if image else None
        if url_image:
            url_image = url_image.split("?")[0]   # retire le cache-buster

        cartes.append(CarteFR(
            card_code=code,
            display_name=nom_avec_variante(nom_fr, rang),
            rarity=_texte(info.group("rarete")) or None,
            card_type=_texte(info.group("type")) or None,
            series_name=_nettoyer_serie(
                _EXTENSION.search(corps).group("serie")
                if _EXTENSION.search(corps) else None),
            image_url=url_image,
            rang_variante=rang,
        ))

    return cartes


def series_disponibles(contenu: str) -> Dict[str, str]:
    """Les series du menu deroulant : {valeur: libelle lisible}.

    C'est la liste de ce qui EXISTE en francais, telle que l'editeur la
    publie — et elle ne recouvre pas celle de l'anglais. S'y fier evite
    d'inscrire au catalogue des cartes qui n'ont jamais ete imprimees dans
    cette langue.
    """
    series = {}
    for option in _SERIE_OPTION.finditer(contenu):
        libelle = _nettoyer_serie(option.group("libelle"))
        if libelle:
            series[option.group("valeur")] = libelle
    return series


def nombre_annonce(contenu: str) -> Optional[int]:
    """Le compte que la page affiche elle-meme (« 169 résultats »).

    Sert de controle : si on extrait moins de cartes que la page n'en
    annonce, le parseur a rate quelque chose et il faut le savoir.
    """
    trouve = _NOMBRE_RESULTATS.search(contenu)
    return int(trouve.group(1)) if trouve else None


# --- Acces reseau --------------------------------------------------------

class ClientListeFR:
    def __init__(self, session: Optional[requests.Session] = None,
                 racine: str = RACINE):
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._racine = racine.rstrip("/")

    def url_de_serie(self, serie: Optional[str] = None) -> str:
        base = f"{self._racine}{CHEMIN_LISTE}"
        return f"{base}?series={serie}" if serie else base

    def recuperer(self, serie: Optional[str] = None) -> str:
        """Rend le HTML d'une page de liste. Leve en cas de refus."""
        url = self.url_de_serie(serie)
        if not is_allowed(url, user_agent=USER_AGENT, session=self._session):
            raise PermissionError(
                f"robots.txt n'autorise pas {url} pour ce robot")
        reponse = self._session.get(url, timeout=DELAI)
        reponse.raise_for_status()
        # Le serveur n'annonce pas toujours l'encodage ; la page est en UTF-8
        # et sans cela les accents arrivent en mojibake.
        reponse.encoding = reponse.encoding or "utf-8"
        return reponse.text

    def cartes_de_serie(self, serie: Optional[str] = None) -> List[CarteFR]:
        contenu = self.recuperer(serie)
        cartes = analyser_page(contenu, racine=self._racine)

        attendu = nombre_annonce(contenu)
        if attendu is not None and len(cartes) < attendu:
            # Les variantes sont regroupees, donc extraire MOINS que le
            # compte annonce est normal. On le journalise quand meme : si
            # l'ecart devient enorme, c'est que la structure a change.
            logger.info("Liste FR serie %s : %d fiches pour %d resultats annonces "
                        "(les variantes sont regroupees)", serie, len(cartes), attendu)
        return cartes

    def series(self) -> Dict[str, str]:
        """Series a charger : celles du menu, sinon la liste gravee.

        Le menu d'abord, parce qu'il restera a jour quand de nouvelles
        series sortiront. Le repli ensuite, pour qu'une seule requete en
        echec n'emporte pas tout le chargement.
        """
        try:
            vues = series_disponibles(self.recuperer())
        except Exception as erreur:   # noqa: BLE001
            logger.warning("Liste FR : menu des series illisible (%s), "
                           "repli sur la liste connue", erreur)
            return dict(SERIES_CONNUES)
        if not vues:
            logger.warning("Liste FR : menu des series vide, "
                           "repli sur la liste connue")
            return dict(SERIES_CONNUES)
        # Une serie connue mais absente du menu est conservee : le menu a pu
        # changer de forme, et perdre une serie en silence se verrait comme
        # un catalogue incomplet sans cause apparente.
        fusion = dict(SERIES_CONNUES)
        fusion.update(vues)
        return fusion
