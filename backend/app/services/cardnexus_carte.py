"""
L'avis de CardNexus sur une carte du catalogue : la moins chere de ses
annonces en Europe (dans la langue de la carte si possible), combien il y
en a, ses ventes des 30 derniers jours, et le lien vers sa page.

Rapprochement, d'apres les reponses reelles de l'API (diagnostic) : on
cherche par code (« printNumber »), ce qui rend toutes les impressions de
ce code — l'originale, les promos, les reeditions, le manga d'un autre
coffret. On garde celle de la meme extension (« OP01 » / « Romance Dawn »)
et de la meme version : sans « variant » pour l'impression ordinaire, une
variante (parallele) sinon, « Manga » pour la seconde.

Trois requetes au plus par carte (recherche, prix, ventes), gardees une
heure en memoire : l'API compte ses requetes (600 par heure pour les prix).
"""
import re
import statistics
import time
from typing import Any, Dict, List, Optional, Tuple

from app.collectors.cardlist_fr import rang_de_parallele
from app.collectors.cardnexus import ClientCardNexus, ErreurCardNexus
from app.models import MarketCardPrice

DUREE_CACHE_SECONDES = 3600
_cache: Dict[Tuple[str, str, str], Tuple[float, dict]] = {}

# Ce qui n'est pas l'impression d'origine d'une carte.
_HORS_SERIE = re.compile(r"reprint|championship|serial|jumbo|winner|finalist|pre-?release|stamp", re.I)


def _norm(code: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _slug(texte: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", texte.lower().replace("'", "").replace("’", "")).strip("-")


def choisir_produit(produits: List[dict], carte: MarketCardPrice) -> Optional[dict]:
    """L'impression CardNexus qui correspond a notre fiche, ou None."""
    serie = _norm((carte.card_code or "").split("-")[0])
    rang = rang_de_parallele(carte.name_slug)
    produits = [p for p in produits if isinstance(p, dict) and p.get("productType", "card") == "card"]
    originaux = [p for p in produits if not _HORS_SERIE.search(p.get("name") or "")]

    def variante(p: dict) -> str:
        return (p.get("variant") or "").lower()

    # Par ordre de preference : la meme extension d'abord, puis n'importe
    # laquelle (le manga d'une carte est souvent reimprime dans un coffret).
    if rang == 0:
        criteres = [lambda p: not variante(p)]
    elif rang >= 2:
        criteres = [lambda p: "manga" in variante(p), lambda p: bool(variante(p))]
    else:
        criteres = [lambda p: bool(variante(p)) and "manga" not in variante(p)]

    meme_serie = [p for p in originaux if _norm((p.get("expansion") or {}).get("code")) == serie]
    for critere in criteres:
        for liste in (meme_serie, originaux):
            trouves = [p for p in liste if critere(p)]
            if trouves:
                return trouves[0]
    return None


def _prix_europe(prix: dict, langue: Optional[str]) -> dict:
    """La moins chere des annonces CardNexus en Europe, et combien il y en
    a ; dans la langue de la carte quand CardNexus le detaille."""
    for finition in (prix.get("pricesByFinish") or {}).values():
        bloc = ((finition or {}).get("cardnexus") or {}).get("regions", {}).get("eu") or {}
        if not bloc:
            continue
        resultat = {"plus_bas": bloc.get("low"), "annonces": bloc.get("listingCount") or 0,
                    "plus_bas_langue": None, "annonces_langue": 0}
        if langue:
            for etat in (bloc.get("byCondition") or {}).values():
                l = ((etat or {}).get("byLanguage") or {}).get(langue) or {}
                if isinstance(l, dict) and l.get("low") is not None:
                    if resultat["plus_bas_langue"] is None or l["low"] < resultat["plus_bas_langue"]:
                        resultat["plus_bas_langue"] = l["low"]
                    resultat["annonces_langue"] += l.get("listingCount") or 0
        cardmarket = (finition or {}).get("cardmarket") or {}
        if cardmarket:
            resultat["cardmarket"] = {k: cardmarket.get(k) for k in ("low", "mid", "marketValue")
                                      if cardmarket.get(k) is not None}
        return resultat
    return {"plus_bas": None, "annonces": 0, "plus_bas_langue": None, "annonces_langue": 0}


def _montant(vente: Any) -> Optional[float]:
    """Le prix d'une vente, quel que soit le champ qui le porte."""
    if not isinstance(vente, dict):
        return None
    for cle in ("priceEur", "price", "amount", "total"):
        v = vente.get(cle)
        if isinstance(v, dict):
            v = v.get("amount")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def avis_cardnexus(carte: MarketCardPrice, client: Optional[ClientCardNexus] = None) -> dict:
    client = client or ClientCardNexus()
    if not client.configure:
        return {"configure": False}
    if not carte.card_code:
        return {"configure": True, "trouve": False, "raison": "Carte sans code : impossible à chercher."}

    cle = (carte.card_code, carte.name_slug or "", carte.language or "")
    en_cache = _cache.get(cle)
    if en_cache and time.time() - en_cache[0] < DUREE_CACHE_SECONDES:
        return en_cache[1]

    try:
        statut, recherche = client.chercher(printNumber=carte.card_code, limit=20)
        if statut != 200:
            return {"configure": True, "trouve": False, "raison": f"CardNexus a répondu {statut}."}
        produit = choisir_produit((recherche or {}).get("data") or [], carte)
        if produit is None:
            resultat = {"configure": True, "trouve": False,
                        "raison": "Cette version n'a pas été trouvée sur CardNexus."}
        else:
            pid = produit.get("id")
            _, prix = client.prix(pid)
            _, ventes = client.ventes(pid)
            liste = (ventes or {}).get("data") or [] if isinstance(ventes, dict) else []
            montants = [m for m in map(_montant, liste) if m is not None]
            expansion = produit.get("expansion") or {}
            resultat = {
                "configure": True, "trouve": True,
                "nom": produit.get("name"),
                "extension": expansion.get("name"),
                "url": (f"https://cardnexus.com/fr/explore/onepiece/{_slug(expansion.get('name') or '')}"
                        f"/card/{produit.get('nameSlug')}-{pid}"),
                "europe": _prix_europe(prix if isinstance(prix, dict) else {}, carte.language),
                "ventes_30j": len(liste),
                "ventes_plus": bool(((ventes or {}).get("pagination") or {}).get("nextCursor"))
                if isinstance(ventes, dict) else False,
                "ventes_mediane": round(statistics.median(montants), 2) if montants else None,
            }
    except ErreurCardNexus as e:
        return {"configure": True, "trouve": False, "raison": str(e)}
    _cache[cle] = (time.time(), resultat)
    return resultat
