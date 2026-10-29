"""
CardNexus (https://cardnexus.com) : une deuxieme reference de prix, a cote
de Cardmarket, et des ventes reellement conclues. API publique en
avant-premiere, sur cle personnelle (CARDNEXUS_API_KEY, « cnk_live_… »).

D'apres sa documentation (docs.cardnexus.com) :
- hote https://public-api.cardnexus.com, cle en « Authorization: Bearer » ;
- POST /v1/products/search : recherche au catalogue (name, printNumber,
  nameSlug, productIds, limit, offset), reponse { data, pagination } ;
- GET /v1/products/{id}/prices : prix courants par finition et par source
  (cardmarket, tcgplayer, cardnexus) — 600 requetes par heure ;
- GET /v1/products/{id}/sales : ventes conclues sur les 30 derniers jours.

La forme exacte des reponses pour One Piece n'est pas encore verifiee : le
diagnostic (/api/admin/debug-cardnexus) sert a la lire avant d'en tirer
quoi que ce soit, comme pour Vinted.

La cle ne sort jamais de ce module : ni journal, ni message d'erreur, ni
reponse de diagnostic ne la contiennent — meme si l'API la renvoyait.
"""
import json
from typing import Any, Optional, Tuple

import requests

from app.config import settings

HOTE = "https://public-api.cardnexus.com"
DELAI_SECONDES = 15
# Ce qu'un diagnostic rend de chaque reponse : de quoi en voir la forme.
ELEMENTS_PAR_LISTE = 3
CARACTERES_PAR_TEXTE = 300


class ErreurCardNexus(Exception):
    """CardNexus injoignable ou cle absente. Le message ne contient jamais
    la cle."""


def abreger(valeur: Any, profondeur: int = 0) -> Any:
    """La forme d'une reponse, sans son volume : listes coupees a quelques
    elements, textes raccourcis, imbrication bornee."""
    if profondeur > 8:
        return "…"
    if isinstance(valeur, dict):
        return {k: abreger(v, profondeur + 1) for k, v in valeur.items()}
    if isinstance(valeur, list):
        debut = [abreger(v, profondeur + 1) for v in valeur[:ELEMENTS_PAR_LISTE]]
        if len(valeur) > ELEMENTS_PAR_LISTE:
            debut.append(f"… {len(valeur) - ELEMENTS_PAR_LISTE} de plus")
        return debut
    if isinstance(valeur, str) and len(valeur) > CARACTERES_PAR_TEXTE:
        return valeur[:CARACTERES_PAR_TEXTE] + "…"
    return valeur


def _identifiant(produit: Any) -> Optional[str]:
    """L'identifiant d'un produit, quel que soit le nom du champ."""
    if not isinstance(produit, dict):
        return None
    for cle in ("id", "productId", "_id"):
        if produit.get(cle) not in (None, ""):
            return str(produit[cle])
    return None


class ClientCardNexus:
    def __init__(self, cle: Optional[str] = None, session: Optional[requests.Session] = None):
        self.cle = ((cle if cle is not None else settings.cardnexus_api_key) or "").strip()
        self.session = session or requests.Session()

    @property
    def configure(self) -> bool:
        return bool(self.cle)

    def _masquer(self, texte: str) -> str:
        return texte.replace(self.cle, "«clé masquée»") if self.cle else texte

    def appeler(self, methode: str, chemin: str, corps: Optional[dict] = None) -> Tuple[int, Any]:
        """(statut HTTP, reponse JSON — ou texte si ce n'en est pas)."""
        if not self.configure:
            raise ErreurCardNexus("CARDNEXUS_API_KEY absente : CardNexus n'est pas configuré.")
        try:
            reponse = self.session.request(
                methode, HOTE + chemin, json=corps, timeout=DELAI_SECONDES,
                headers={"Authorization": f"Bearer {self.cle}", "Accept": "application/json"},
            )
        except requests.RequestException as e:
            # Le message d'origine peut citer la requete : on n'en garde que le type.
            raise ErreurCardNexus(f"CardNexus injoignable ({type(e).__name__}).") from None
        try:
            contenu = reponse.json()
        except ValueError:
            contenu = reponse.text
        return reponse.status_code, contenu

    def chercher(self, **filtres) -> Tuple[int, Any]:
        return self.appeler("POST", "/v1/products/search", filtres)

    def prix(self, produit_id: str) -> Tuple[int, Any]:
        return self.appeler("GET", f"/v1/products/{produit_id}/prices")

    def ventes(self, produit_id: str) -> Tuple[int, Any]:
        return self.appeler("GET", f"/v1/products/{produit_id}/sales")

    def diagnostic(self, code: str, nom: str) -> dict:
        """Lecture seule, quatre requetes au plus : chercher la carte par son
        code, puis par son nom ; pour le premier produit trouve, ses prix et
        ses ventes. Rend la forme des reponses, abregee, pour ecrire la
        lecture de CardNexus sur du concret."""
        if not self.configure:
            return {
                "cle_configuree": False,
                "a_faire": "Ajoute CARDNEXUS_API_KEY=… dans backend/.env (et dans les variables "
                           "d'environnement de Render), puis relance le backend.",
            }
        etapes, produit_id = [], None

        def etape(titre: str, methode: str, chemin: str, corps: Optional[dict] = None):
            try:
                statut, contenu = self.appeler(methode, chemin, corps)
            except ErreurCardNexus as e:
                etapes.append({"etape": titre, "requete": f"{methode} {chemin}", "corps": corps,
                               "erreur": str(e)})
                return None
            etapes.append({"etape": titre, "requete": f"{methode} {chemin}", "corps": corps,
                           "statut": statut, "reponse": abreger(contenu)})
            return contenu if 200 <= statut < 300 else None

        for titre, corps in (("recherche par code", {"printNumber": code, "limit": 5}),
                             ("recherche par nom", {"name": nom, "limit": 5})):
            contenu = etape(titre, "POST", "/v1/products/search", corps)
            if produit_id is None and isinstance(contenu, dict):
                produits = contenu.get("data") or contenu.get("products") or []
                produit_id = next((i for i in map(_identifiant, produits) if i), None)

        if produit_id is not None:
            etape("prix du premier produit", "GET", f"/v1/products/{produit_id}/prices")
            etape("ventes du premier produit", "GET", f"/v1/products/{produit_id}/sales")

        resultat = {"cle_configuree": True, "code": code, "nom": nom,
                    "premier_produit": produit_id, "etapes": etapes}
        # Ceinture et bretelles : rien de ce qui sort ne contient la cle.
        return json.loads(self._masquer(json.dumps(resultat, ensure_ascii=False)))
