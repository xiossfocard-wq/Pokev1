from fastapi import APIRouter, BackgroundTasks, Query
from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.pipeline import run_full_check, rescore_unpriced_listings
from app.core.language_filter import detect_language
from app.collectors.vinted_scraper import VintedScraper
from app.collectors.zebradex_prices import ZebraDexClient
from app.services.price_index import (
    sync_series_batch, refresh_series_catalog, index_stats, find_price_for_listing,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _run_check_with_own_session():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


def _sync_prices_with_own_session(batch_size: int):
    db = SessionLocal()
    try:
        sync_series_batch(db, batch_size=batch_size)
    finally:
        db.close()


@router.post("/run-check-now")
def run_check_now(background_tasks: BackgroundTasks):
    """Declenche un cycle de collecte immediatement, en tache de fond."""
    background_tasks.add_task(_run_check_with_own_session)
    return {"status": "cycle de verification lance en arriere-plan"}


@router.post("/sync-prices")
def sync_prices(background_tasks: BackgroundTasks, batch_size: int = Query(6, ge=1, le=30)):
    """
    Synchronise un lot de series ZebraDex vers l'index local de prix.
    Progressif par design : a 6s par requete, 30 series = 3 min. Appeler
    plusieurs fois (ou laisser le scheduler faire) pour couvrir les 169
    series.
    """
    background_tasks.add_task(_sync_prices_with_own_session, batch_size)
    return {"status": f"synchronisation de {batch_size} serie(s) lancee en arriere-plan"}


@router.post("/rescore-unpriced")
def rescore_unpriced(
    limit: int = Query(120, ge=1, le=2000),
    include_uncertain: bool = Query(True, description="Inclure aussi les prix en confiance faible"),
):
    """
    Retente le rapprochement sur les annonces sans prix de reference et,
    par defaut, sur celles dont le prix a ete trouve en confiance faible.
    Tourne aussi automatiquement a chaque cycle ; cet endpoint sert a voir
    l'effet tout de suite apres une amelioration du moteur de matching.
    """
    db = SessionLocal()
    try:
        return {"status": "ok", **rescore_unpriced_listings(
            db, limit=limit, include_uncertain=include_uncertain
        )}
    finally:
        db.close()


@router.post("/refresh-series-catalog")
def refresh_catalog():
    """Redecouvre la liste des series ZebraDex (169 au 04/08/2026)."""
    db = SessionLocal()
    try:
        added = refresh_series_catalog(db)
        return {"status": "ok", "nouvelles_series": added, **index_stats(db)}
    finally:
        db.close()


@router.get("/price-index-status")
def price_index_status():
    """Avancement de la construction de l'index de prix."""
    db = SessionLocal()
    try:
        return index_stats(db)
    finally:
        db.close()


@router.get("/test-price-match")
def test_price_match(title: str = Query(..., description="Titre d'annonce a tester")):
    """
    Teste le matching d'un titre contre l'index, sans rien enregistrer.
    Utile pour comprendre pourquoi une annonce n'a pas de prix.
    """
    db = SessionLocal()
    try:
        match = find_price_for_listing(db, title)
        if match is None:
            return {"matched": False, "title": title,
                    "hint": "aucune carte de l'index ne correspond - index peut-etre incomplet, voir /price-index-status"}
        return {"matched": True, "title": title, **match.to_dict()}
    finally:
        db.close()


@router.get("/test-language")
def test_language(title: str = Query(..., description="Titre d'annonce a tester")):
    """
    Explique pourquoi une annonce est jugee francaise ou non. Sans ca, une
    annonce ecartee disparait du dashboard sans qu'on sache pourquoi.
    """
    verdict = detect_language(title)
    return {"title": title, **verdict.to_dict()}


@router.get("/debug-vinted")
def debug_vinted(search_text: str = "carte pokemon"):
    """Diagnostic lecture seule du scraper Vinted."""
    scraper = VintedScraper(request_delay_seconds=settings.vinted_request_delay_seconds)
    return scraper.diagnostic_fetch(search_text=search_text)


@router.get("/debug-zebradex")
def debug_zebradex(series_url: Optional[str] = None):
    """
    Diagnostic lecture seule de ZebraDex. Sans parametre : teste la page
    listant les series. Avec `series_url` : teste le parsing d'une serie.
    """
    return ZebraDexClient().diagnostic_fetch(series_url=series_url)
