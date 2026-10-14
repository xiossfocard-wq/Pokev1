"""
Visuel officiel des cartes One Piece, deduit du code de la carte.

Pourquoi par le CODE et pas par le nom
--------------------------------------
Chercher l'illustration par NOM serait approximatif par construction, et
c'est l'erreur que ce fichier evite :

1. les API d'illustrations grand public couvrent surtout d'autres jeux ;
2. « Luffy »
   designe une quarantaine de cartes differentes ; la premiere reponse
   n'est pas forcement celle qu'on a en base, et rien ne permet de le
   savoir. On aurait affiche le visuel d'une autre carte sous un prix,
   ce qui est pire que pas de visuel du tout : l'utilisateur regarde
   l'image pour decider d'acheter.

One Piece permet mieux. Le jeu numerote ses cartes « OP01-120 »,
« ST01-001 », « EB01-012 », « P-001 », et la liste officielle sert
l'illustration a une adresse qui se deduit directement de ce code. Pas de
recherche, pas d'ambiguite : le code identifie la carte, et l'adresse
identifie l'image de cette carte.

Pourquoi on VERIFIE avant d'enregistrer
---------------------------------------
Construire une URL ne prouve pas qu'elle existe. Une URL fausse enregistree
en base donnerait un cadre casse dans l'interface, c'est-a-dire un mensonge
visible a chaque affichage de la carte. On fait donc une requete de controle
et on n'enregistre QUE si la reponse est bien une image.

Consequence assumee : quand la verification ne peut pas aboutir (reseau
coupe, hote injoignable), aucune image n'est enregistree. L'app affiche
alors le cadre vide prevu pour ca, et non une image qui ne chargera pas.

CE CODE N'A PAS PU ETRE VERIFIE CONTRE L'HOTE REEL
--------------------------------------------------
La politique reseau de l'environnement de developpement refuse
en.onepiece-cardgame.com, comme tous les hotes de donnees de cartes. Le
format d'adresse est donc ecrit d'apres la forme publique connue, et reste
CONFIGURABLE sans toucher au code : `CARD_IMAGE_BASE_URL`. Si les images ne
remontent pas en production, `/api/admin/debug-card-images` rend le detail
de chaque tentative — code HTTP et type de contenu — ce qui suffit a
corriger le format sans deviner.

Une carte sans image n'est pas une erreur : l'interface doit afficher un
cadre vide plutot que de masquer la carte. Un catalogue de prix sans visuel
reste utile ; un catalogue amoindri parce qu'une image manque ne l'est pas.
"""
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

# Politesse : on interroge le site officiel du jeu, pas une API prevue pour
# l'automatisation. Une requete toutes les 400 ms pour un enrichissement de
# fond, c'est moins qu'un visiteur qui feuillette la liste des cartes.
MIN_DELAY_SECONDS = 0.4

TIMEOUT_SECONDS = 15

# Un navigateur ordinaire. Sans User-Agent credible, certains hebergeurs
# rendent 403 et on conclurait a tort que la carte n'existe pas.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# « OP01-120 », « OP01 120 », « op01120 » : un prefixe de serie (lettres plus
# eventuellement un numero d'extension) puis le numero de carte. Le
# separateur varie selon la source, donc il est optionnel.
MOTIF_CODE = re.compile(r"^([A-Z]{1,4}\d{0,2})[\s\-_.]*(\d{1,4})\b")

# Largeur du numero de carte dans les adresses officielles : OP01-001, pas
# OP01-1. Une source qui ecrit « OP01-1 » designe la meme carte.
LARGEUR_NUMERO = 3

# Indices, dans le nom de la carte, qu'il s'agit d'une illustration
# alternative. Le jeu les sert sous le meme code suffixe « _p1 », « _p2 ».
INDICES_ALTERNATIVE = (
    "parallel", "parallele", "alternative", "alt art", "manga",
    "special art", "full art",
)

SUFFIXES_ALTERNATIVE = ("_p1", "_p2")

EXTENSION_IMAGE = "png"


@dataclass
class ImageCarte:
    image_url: str
    source: str = "onepiece-cardgame"
    card_id: Optional[str] = None


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def code_canonique(card_code: Optional[str]) -> Optional[str]:
    """« OP01 120 », « op01-120 », « OP01-1 » -> « OP01-120 » / « OP01-001 ».

    Rend None si la chaine ne ressemble pas a un code de carte One Piece :
    mieux vaut ne rien tenter que construire une adresse au hasard.
    """
    brut = _sans_accents(card_code or "").strip().upper()
    if not brut:
        return None

    trouve = MOTIF_CODE.match(brut)
    if not trouve:
        return None

    serie, numero = trouve.group(1), trouve.group(2)
    return f"{serie}-{numero.zfill(LARGEUR_NUMERO)}"


def _est_alternative(display_name: str) -> bool:
    nom = _sans_accents(display_name or "").lower()
    return any(indice in nom for indice in INDICES_ALTERNATIVE)


def urls_candidates(card_code: Optional[str],
                    display_name: str = "") -> List[str]:
    """Adresses a essayer, dans l'ordre, pour une carte donnee.

    L'illustration de base d'abord, sauf si le nom annonce une alternative :
    dans ce cas on essaie les variantes avant, parce que c'est bien cette
    illustration-la qui est en vente a ce prix.
    """
    code = code_canonique(card_code)
    if not code:
        return []

    base = settings.card_image_base_url.rstrip("/")
    suffixes = ["", *SUFFIXES_ALTERNATIVE]
    if _est_alternative(display_name):
        suffixes = [*SUFFIXES_ALTERNATIVE, ""]

    return [f"{base}/{code}{suffixe}.{EXTENSION_IMAGE}" for suffixe in suffixes]


class ClientImagesCartes:
    def __init__(self, session: Optional[requests.Session] = None,
                 min_delay: float = MIN_DELAY_SECONDS):
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", USER_AGENT)
        self._min_delay = min_delay
        self._dernier_appel = 0.0

    def _throttle(self):
        ecoule = time.time() - self._dernier_appel
        if ecoule < self._min_delay:
            time.sleep(self._min_delay - ecoule)
        self._dernier_appel = time.time()

    def _sonder(self, url: str) -> dict:
        """Verifie qu'une adresse rend bien une image.

        HEAD d'abord, c'est la requete la plus legere. Certains hebergeurs la
        refusent (403/405) tout en servant le GET : dans ce cas on retombe
        sur un GET en flux, qu'on referme sans lire le corps.
        """
        self._throttle()
        try:
            reponse = self._session.head(url, timeout=TIMEOUT_SECONDS,
                                         allow_redirects=True)
            if reponse.status_code in (403, 405, 501):
                reponse = self._session.get(url, timeout=TIMEOUT_SECONDS,
                                            stream=True, allow_redirects=True)
                reponse.close()
        except requests.RequestException as exc:
            return {"url": url, "erreur_reseau": str(exc), "image": False}

        type_contenu = (reponse.headers.get("Content-Type") or "").lower()
        return {
            "url": url,
            "status_code": reponse.status_code,
            "content_type": type_contenu,
            "image": reponse.status_code == 200
            and type_contenu.startswith("image/"),
        }

    def chercher_image(self, display_name: str,
                       card_code: Optional[str] = None) -> Optional[ImageCarte]:
        """Visuel officiel d'une carte, deduit de son code.

        Sans code exploitable, rend None SANS appel reseau : on ne devine pas
        l'adresse a partir du nom, c'est precisement l'erreur qu'on repare.
        """
        candidates = urls_candidates(card_code, display_name)
        if not candidates:
            logger.debug("Images: '%s' n'a pas de code exploitable (%r)",
                         display_name, card_code)
            return None

        if not settings.card_image_verify:
            # Mode degrade, explicite : on fait confiance au format. A
            # n'activer que lorsque le format a ete constate correct, sinon
            # l'interface se remplit de cadres casses.
            return ImageCarte(image_url=candidates[0],
                              card_id=code_canonique(card_code))

        for url in candidates:
            resultat = self._sonder(url)
            if resultat.get("image"):
                return ImageCarte(image_url=url,
                                  card_id=code_canonique(card_code))

        logger.info("Images: aucune illustration servie pour %s (%d essai(s))",
                    code_canonique(card_code), len(candidates))
        return None

    def diagnostic(self, code: str = "OP01-001",
                   nom: str = "") -> dict:
        """Detail de chaque tentative pour un code donne.

        A appeler via /api/admin/debug-card-images quand aucune image ne
        remonte : le code HTTP et le type de contenu de chaque adresse
        essayee suffisent a corriger `CARD_IMAGE_BASE_URL` sans deviner.
        Meme demarche que debug-vinted et debug-zebradex.
        """
        candidates = urls_candidates(code, nom)
        resultat = {
            "code_fourni": code,
            "code_canonique": code_canonique(code),
            "base_url": settings.card_image_base_url,
            "verification_active": settings.card_image_verify,
            "urls_candidates": candidates,
        }
        if not candidates:
            resultat["erreur"] = (
                "Code non reconnu : attendu une forme « OP01-120 », "
                "« ST01-001 », « EB01-012 » ou « P-001 »."
            )
            return resultat

        resultat["tentatives"] = [self._sonder(url) for url in candidates]
        retenue = next((t for t in resultat["tentatives"] if t.get("image")), None)
        resultat["url_retenue"] = retenue["url"] if retenue else None
        return resultat
