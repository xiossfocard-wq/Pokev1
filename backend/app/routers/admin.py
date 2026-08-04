from fastapi import APIRouter, BackgroundTasks

from app.config import settings
from app.database import SessionLocal
from app.pipeline import run_full_check
from app.collectors.vinted_scraper import VintedScraper

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _run_check_with_own_session():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


@router.post("/run-check-now")
def run_check_now(background_tasks: BackgroundTasks):
    """
    Déclenche un cycle de vérification immédiatement (utile pour tester
    sans attendre le prochain tick du scheduler). Lancé en tâche de fond
    pour ne pas bloquer la requête HTTP le temps du scraping.
    """
    background_tasks.add_task(_run_check_with_own_session)
    return {"status": "cycle de vérification lancé en arrière-plan"}


@router.get("/debug-vinted")
def debug_vinted(search_text: str = "carte pokemon"):
    """
    Diagnostic en lecture seule : fait la même requête que le scraper
    normal vers Vinted, mais retourne des infos sur la page obtenue
    au lieu d'essayer de parser des annonces.
    """
    scraper = VintedScraper(request_delay_seconds=settings.vinted_request_delay_seconds)
    return scraper.diagnostic_fetch(search_text=search_text)
