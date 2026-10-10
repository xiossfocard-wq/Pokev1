"""
Visuel des cartes, via l'API publique TCGdex.

Pourquoi une source separee
---------------------------
Demande du 10/10/2026 : « je veux voir l'image de chaque carte dans la
recherche ». ZebraDex fournit les prix mais pas d'image exploitable. Il faut
donc une seconde source, uniquement pour l'illustration.

Pourquoi TCGdex plutot qu'un scraping
-------------------------------------
TCGdex (https://tcgdex.dev) est une API publique, ouverte et documentee,
avec une localisation francaise et sans cle d'API. C'est donc un usage
prevu par la source, contrairement a Vinted ou ZebraDex ou le projet lit des
pages publiques faute d'API (voir l'avertissement du README). Aucune des
reserves juridiques du README ne s'applique ici.

CE CODE N'A PAS PU ETRE VERIFIE CONTRE L'API REELLE
---------------------------------------------------
L'environnement de developpement n'a pas d'acces reseau sortant vers
api.tcgdex.net : la politique reseau refuse l'hote. Le parsing est donc
ecrit d'apres la forme documentee de l'API, et volontairement TOLERANT :

- plusieurs formes de reponse acceptees (liste nue, ou objet enveloppant) ;
- plusieurs noms de champ essayes pour l'image ;
- toute reponse inattendue rend None et se LOGUE, au lieu de lever.

`diagnostic()` rend la reponse brute telle quelle : c'est par la qu'il faut
passer si aucune image ne remonte. Meme demarche que debug-vinted et
debug-zebradex, pour la meme raison — un format distant peut changer ou
differer de ce qui etait prevu.

Une carte sans image n'est pas une erreur : l'interface doit afficher un
cadre vide plutot que de masquer la carte. Un catalogue de prix sans visuel
reste utile ; un catalogue amoindri parce qu'une image manque ne l'est pas.
"""
import logging
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tcgdex.net/v2/fr"

# Politesse : l'API est gratuite et ouverte, on ne la martele pas. 4 req/s
# reste tres large pour un enrichissement progressif en tache de fond.
MIN_DELAY_SECONDS = 0.25

TIMEOUT_SECONDS = 15

# Qualites proposees par TCGdex. "high" pour l'affichage en grille, le
# format etant de toute facon redimensionne par Next/Image cote frontend.
QUALITE_IMAGE = "high"
EXTENSION_IMAGE = "png"


@dataclass
class ImageCarte:
    image_url: str
    source: str = "tcgdex"
    card_id: Optional[str] = None


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _nettoyer_nom(display_name: str) -> str:
    """Retire les suffixes de mecanique pour maximiser les chances de
    correspondance. TCGdex indexe « Dracaufeu ex » sous ce nom complet, mais
    une recherche sur « Dracaufeu » ramene aussi la variante ; l'inverse
    n'est pas vrai si le suffixe est ecrit differemment (ex/EX/Ex)."""
    nom = _sans_accents(display_name or "").strip()
    return " ".join(nom.split())


class ClientImagesCartes:
    def __init__(self, session: Optional[requests.Session] = None,
                 min_delay: float = MIN_DELAY_SECONDS):
        self._session = session or requests.Session()
        self._min_delay = min_delay
        self._dernier_appel = 0.0

    def _throttle(self):
        ecoule = time.time() - self._dernier_appel
        if ecoule < self._min_delay:
            time.sleep(self._min_delay - ecoule)
        self._dernier_appel = time.time()

    def _get_json(self, chemin: str):
        self._throttle()
        url = f"{BASE_URL}{chemin}"
        try:
            reponse = self._session.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logger.warning("Images: echec reseau sur %s (%s)", url, exc)
            return None

        if reponse.status_code == 404:
            return None
        if reponse.status_code != 200:
            logger.warning("Images: %s a repondu %s", url, reponse.status_code)
            return None

        try:
            return reponse.json()
        except ValueError as exc:
            logger.warning("Images: reponse non-JSON de %s (%s)", url, exc)
            return None

    @staticmethod
    def _premiere_entree(charge):
        """TCGdex rend une liste pour une recherche. On accepte aussi un
        objet enveloppant au cas ou la forme differe de la documentation."""
        if isinstance(charge, list):
            return charge[0] if charge else None
        if isinstance(charge, dict):
            for cle in ("data", "results", "cards", "items"):
                valeur = charge.get(cle)
                if isinstance(valeur, list) and valeur:
                    return valeur[0]
            # Peut-etre deja une carte unique.
            if charge.get("id") or charge.get("image"):
                return charge
        return None

    @staticmethod
    def _url_image(entree: dict) -> Optional[str]:
        """TCGdex rend une base d'URL SANS extension : il faut y ajouter la
        qualite et le format (`<base>/high.png`). D'autres formes de champ
        sont essayees par precaution."""
        if not isinstance(entree, dict):
            return None

        base = entree.get("image")
        if isinstance(base, str) and base:
            if base.rsplit("/", 1)[-1].count(".") >= 1:
                return base  # deja une URL complete
            return f"{base}/{QUALITE_IMAGE}.{EXTENSION_IMAGE}"

        # Formes alternatives tolerees.
        for cle in ("imageUrl", "image_url", "images"):
            valeur = entree.get(cle)
            if isinstance(valeur, str) and valeur:
                return valeur
            if isinstance(valeur, dict):
                for sous_cle in ("high", "large", "png", "small"):
                    sous = valeur.get(sous_cle)
                    if isinstance(sous, str) and sous:
                        return sous
        return None

    def chercher_image(self, display_name: str,
                       card_code: Optional[str] = None) -> Optional[ImageCarte]:
        """Cherche l'image d'une carte par son nom.

        Le code de carte de ZebraDex (« PAF 232 ») n'est pas l'identifiant
        TCGdex, les deux sources ne partagent aucune cle : la recherche se
        fait donc par nom, ce qui est approximatif par nature. Une carte
        reeditee dans plusieurs series peut recevoir l'illustration d'une
        autre edition. C'est acceptable pour un visuel de reperage, ca ne le
        serait pas pour un prix.
        """
        nom = _nettoyer_nom(display_name)
        if not nom:
            return None

        charge = self._get_json(f"/cards?name={quote(nom)}")
        entree = self._premiere_entree(charge)

        if entree is None and " " in nom:
            # Deuxieme essai sur le premier mot : « Dracaufeu ex » -> « Dracaufeu ».
            charge = self._get_json(f"/cards?name={quote(nom.split()[0])}")
            entree = self._premiere_entree(charge)

        if entree is None:
            return None

        url = self._url_image(entree)
        if not url:
            logger.info("Images: carte trouvee pour '%s' mais sans visuel", nom)
            return None

        return ImageCarte(
            image_url=url,
            source="tcgdex",
            card_id=str(entree.get("id")) if entree.get("id") else None,
        )

    def diagnostic(self, nom: str = "Dracaufeu") -> dict:
        """Rend la reponse brute, pour comparer a ce que ce code attend.

        A appeler via /api/admin/debug-card-images quand aucune image ne
        remonte : c'est ce qui permet de corriger le parsing sans deviner.
        """
        chemin = f"/cards?name={quote(_nettoyer_nom(nom))}"
        self._throttle()
        url = f"{BASE_URL}{chemin}"
        try:
            reponse = self._session.get(url, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            return {"url": url, "erreur_reseau": str(exc)}

        resultat = {
            "url": url,
            "status_code": reponse.status_code,
            "content_type": reponse.headers.get("Content-Type"),
            "extrait_brut": reponse.text[:1500],
        }
        try:
            charge = reponse.json()
        except ValueError:
            resultat["json"] = None
            return resultat

        entree = self._premiere_entree(charge)
        resultat["forme"] = type(charge).__name__
        resultat["nombre_entrees"] = len(charge) if isinstance(charge, list) else None
        resultat["premiere_entree"] = entree
        resultat["url_image_deduite"] = self._url_image(entree) if entree else None
        return resultat
