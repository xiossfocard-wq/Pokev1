"""
Reconnaissance des sources possibles de catalogue One Piece.

POURQUOI CE MODULE EXISTE
-------------------------
Le catalogue (`MarketCardPrice`) etait alimente par ZebraDex seul. Verifie
le 15/10/2026 depuis un vrai navigateur : **ZebraDex ne couvre pas One
Piece**. Son sitemap FR ne contient que /fr/tcg/pokemon (336 series), et
/fr/tcg/one-piece rend 404. Ce n'est pas un slug a corriger, la section
n'existe pas. Tout ce qui depend du catalogue etait donc vide : exploration
par theme, prix de reference, et par ricochet les visuels, qui se deduisent
du code carte.

Il faut une autre source. Mais ecrire un parseur contre une page jamais vue
est precisement l'erreur qui a produit ce blocage : la couverture One Piece
de ZebraDex avait ete SUPPOSEE, jamais constatee.

Ce module ne parse donc RIEN. Il interroge des sources candidates et
rapporte ce qu'elles repondent : code HTTP, type de contenu, taille, et un
extrait brut. L'environnement de developpement n'a pas d'acces sortant vers
ces hotes, mais le backend deploye, lui, en a un. On se sert de lui comme
d'une paire d'yeux, puis on ecrit le parseur contre du reel.

Meme demarche que debug-vinted, debug-zebradex et debug-card-images, pour
la meme raison : un format distant ne se devine pas.

CE QU'IL FAUT DE CHAQUE SOURCE
------------------------------
Le catalogue a besoin, par carte : un CODE (OP01-120 — c'est lui qui porte
le rapprochement des annonces et la deduction du visuel), un NOM, une
SERIE, une RARETE, et un PRIX. Aucune source connue ne donne les cinq :

- la liste officielle du jeu donne code, nom, serie, rarete, visuel, mais
  aucun prix ;
- un guide de prix donne nom et prix, rarement le code.

L'architecture visee est donc a deux sources : la structure d'un cote, les
prix de l'autre. Cette sonde sert a etablir laquelle repond, et sous quelle
forme.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from app.config import settings
from app.core import robots_compliance

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 25
MIN_DELAY_SECONDS = 1.0

# Taille de l'extrait rendu. Assez pour reconnaitre une structure (balises,
# en-tete CSV, cles JSON), trop peu pour constituer une copie de la source.
TAILLE_EXTRAIT = 1200

USER_AGENT = robots_compliance.DEFAULT_USER_AGENT


@dataclass
class SourceCandidate:
    """Une source a sonder, et ce qu'on espere y trouver."""
    cle: str
    url: str
    apporte: str          # ce que cette source fournirait au catalogue
    remarque: str = ""


def candidates() -> List[SourceCandidate]:
    """Les sources a sonder.

    Designees le 15/10/2026 : la liste officielle FRANCAISE pour la
    structure et les visuels, une boutique francaise pour les prix. Le
    francais n'est pas un detail — c'est le jeu de cartes que l'app suit,
    et les noms imprimes changent d'une edition a l'autre.

    ZebraDex ne figure plus ici : son absence de couverture One Piece a ete
    constatee, la question est tranchee.
    """
    racine_officielle = settings.card_image_base_url.split("/images/")[0].rstrip("/")

    return [
        SourceCandidate(
            cle="liste_fr_index",
            url=f"{racine_officielle}/cardlist/",
            apporte="l'enumeration des series (pas les cartes elles-memes)",
            remarque="Sans l'identifiant de serie, cette page sert surtout a "
                     "savoir COMMENT les series sont enumerees : c'est ce qui "
                     "permettra de les parcourir toutes.",
        ),
        SourceCandidate(
            cle="liste_fr_serie",
            url=f"{racine_officielle}/cardlist/?series=622117",
            apporte="code, nom francais, rarete, visuel (pas de prix)",
            remarque="Une serie reelle, fournie comme echantillon. C'est la "
                     "forme de CETTE page que le parseur devra lire.",
        ),
        SourceCandidate(
            cle="prix_boutique_fr",
            url=settings.prix_source_url,
            apporte="prix en euros, pour des cartes francaises",
            remarque="Page d'accueil : on cherche d'abord comment les fiches "
                     "cartes sont adressees, pas encore les prix eux-memes.",
        ),
    ]


class SondeurDeSources:
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

    def sonder(self, candidat: SourceCandidate) -> dict:
        """Interroge une source et decrit sa reponse. Ne parse rien."""
        rapport = {
            "cle": candidat.cle,
            "url": candidat.url,
            "apporte": candidat.apporte,
            "remarque": candidat.remarque,
        }

        # Meme prudence que le reste du projet : on ne va pas la ou le site
        # demande qu'on n'aille pas, meme pour un diagnostic.
        #
        # On distingue « le site refuse » de « robots.txt illisible ». Les
        # deux empechent la sonde, mais appellent des suites opposees : le
        # premier ferme la source, le second dit seulement que le reseau
        # n'a pas repondu. Les confondre ferait dire au diagnostic le
        # contraire de la realite — l'erreur meme qui nous a menes ici.
        try:
            etat = robots_compliance.etat_pour_diagnostic(
                candidat.url, session=self._session)
        except Exception as exc:  # noqa: BLE001 - un robots.txt casse ne doit rien casser
            logger.warning("Sonde: robots.txt illisible pour %s (%s)", candidat.url, exc)
            etat = "illisible"

        rapport["robots_txt"] = etat

        if etat == "interdit":
            rapport["conclusion"] = "robots.txt INTERDIT cette adresse — non sondee"
            return rapport
        if etat == "illisible":
            rapport["conclusion"] = (
                "robots.txt illisible — non sondee. Ce n'est PAS un refus du "
                "site : l'hote n'a pas repondu. Attendu depuis un conteneur "
                "sans acces sortant ; depuis le backend deploye, cela signale "
                "un vrai probleme reseau."
            )
            return rapport

        self._throttle()
        try:
            reponse = self._session.get(candidat.url, timeout=TIMEOUT_SECONDS,
                                        allow_redirects=True)
        except requests.RequestException as exc:
            rapport["erreur_reseau"] = str(exc)
            rapport["conclusion"] = "injoignable"
            return rapport

        texte = reponse.text or ""
        type_contenu = (reponse.headers.get("Content-Type") or "").lower()

        rapport.update({
            "status_code": reponse.status_code,
            "url_finale": reponse.url,
            "content_type": type_contenu,
            "taille": len(texte),
            "extrait": texte[:TAILLE_EXTRAIT],
        })

        # Quelques reperes de forme, pour orienter la lecture sans decider.
        rapport["indices"] = _indices_de_forme(texte, type_contenu)
        # Les liens revelent comment le site adresse ses pages : c'est ce
        # qui dira ou vivent les series, et ou vivent les fiches cartes.
        rapport["liens_internes"] = _echantillon_de_liens(texte, reponse.url)
        rapport["conclusion"] = _conclure(reponse.status_code, rapport["indices"])
        return rapport

    def sonder_tout(self) -> dict:
        resultats = [self.sonder(c) for c in candidates()]
        utilisables = [r["cle"] for r in resultats
                       if r.get("status_code") == 200 and r.get("taille", 0) > 500]
        return {
            "jeu": settings.tcg_nom,
            "sources_sondees": len(resultats),
            "repondent": utilisables,
            "resultats": resultats,
            "quoi_faire": (
                "Copie ce rapport entier dans la conversation. Le parseur sera "
                "ecrit contre la forme reellement observee ici, pas contre une "
                "supposition."
            ),
        }


def _indices_de_forme(texte: str, type_contenu: str) -> dict:
    """Reperes grossiers : de quoi reconnaitre un JSON, un CSV, une page de
    liste de cartes, ou un mur anti-bot."""
    debut = texte.lstrip()[:1]
    premiere_ligne = texte.split("\n", 1)[0][:300] if texte else ""

    bas = texte.lower()
    return {
        "ressemble_a_du_json": debut in "[{" or "application/json" in type_contenu,
        "ressemble_a_du_csv": ";" in premiere_ligne or "," in premiere_ligne
                              and "<" not in premiere_ligne,
        "premiere_ligne": premiere_ligne,
        # Un code carte visible prouve que la page porte bien des cartes.
        "contient_un_code_carte": _premier_code_carte(texte),
        # Des euros prouvent que la page porte des prix. Une source de prix
        # sans prix visible n'en est pas une.
        "nombre_de_prix_en_euros": len(_MOTIF_PRIX.findall(texte)),
        "premier_prix": (_MOTIF_PRIX.search(texte).group(0).strip()
                         if _MOTIF_PRIX.search(texte) else None),
        # Le jeu suivi est le jeu FRANCAIS : une page anglaise serait la
        # mauvaise edition, avec les mauvais noms imprimes.
        "indices_de_francais": _mots_francais(bas),
        "mentions_anti_bot": [m for m in ("captcha", "cloudflare", "are you human",
                                          "access denied", "datadome")
                              if m in bas],
    }


# « 12,50 € », « 12.50€ », « € 12,50 ».
_MOTIF_PRIX = re.compile(r"(?:\d{1,5}[.,]\d{2}\s*\u20ac|\u20ac\s*\d{1,5}[.,]\d{2})")

# Mots qui n'apparaissent que sur une page francaise. La comparaison se
# fait sur des MOTS ENTIERS : « serie » en sous-chaine matche l'anglais
# « Series », et la sonde aurait alors pris une page anglaise pour une page
# francaise — exactement le genre de faux positif qu'elle doit eviter,
# puisque l'edition anglaise porte d'autres noms imprimes.
_MOTS_FRANCAIS = (
    "rareté", "rarete", "série", "serie", "prix", "disponible", "rupture",
    "panier", "livraison", "épuisé", "epuise", "occasion", "neuf",
)


def _mots_francais(texte_minuscule: str) -> List[str]:
    trouves = []
    for mot in _MOTS_FRANCAIS:
        if re.search(rf"(?<![a-zà-ÿ]){re.escape(mot)}(?![a-zà-ÿ])", texte_minuscule):
            trouves.append(mot)
    return trouves


def _echantillon_de_liens(texte: str, url_base: str, maximum: int = 25) -> List[str]:
    """Adresses internes rencontrees, dedoublonnees.

    C'est le renseignement le plus utile pour une source dont on ne connait
    pas l'organisation : savoir comment elle adresse ses pages dit ou
    chercher les series et les fiches cartes. Les fichiers (images, styles,
    scripts) sont ecartes, ils n'apprennent rien sur la navigation.
    """
    from urllib.parse import urljoin, urlparse

    hote = urlparse(url_base).netloc
    vus: List[str] = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', texte):
        if href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js|ico|woff2?)(\?|$)", href, re.I):
            continue
        absolu = urljoin(url_base, href)
        if urlparse(absolu).netloc != hote:
            continue
        if absolu not in vus:
            vus.append(absolu)
        if len(vus) >= maximum:
            break
    return vus


def _premier_code_carte(texte: str) -> Optional[str]:
    """Premier motif ressemblant a un code One Piece dans le texte.

    Si un code apparait, la source porte bien des cartes du jeu, quelle que
    soit sa mise en forme.
    """
    trouve = re.search(r"\b((?:OP|ST|EB|PRB)\d{2}|P)-\d{3}\b", texte)
    return trouve.group(0) if trouve else None


def _conclure(status: int, indices: dict) -> str:
    if status == 404:
        return "404 — cette source ne couvre pas le jeu vise"
    if status in (401, 403):
        return "refus (401/403) — cle requise, ou blocage automatise"
    if status != 200:
        return f"reponse inattendue ({status})"
    if indices.get("mentions_anti_bot"):
        return "repond, mais la page sent le mur anti-bot"
    if indices.get("contient_un_code_carte"):
        return (f"UTILISABLE — un code carte est present "
                f"({indices['contient_un_code_carte']})")
    return "repond, mais aucun code carte reperé dans l'extrait"
