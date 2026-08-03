from fastapi import APIRouter, BackgroundTasks

from app.database import SessionLocal
from app.pipeline import run_full_check

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _run_check_with_own_session():
    # Important : on ouvre une session dédiée ici plutôt que de réutiliser
    # une session injectée par Depends(get_db), qui serait déjà fermée au
    # moment où la tâche de fond s'exécute réellement (la fermeture de la
    # session via le générateur de dépendance a lieu avant l'exécution des
    # BackgroundTasks dans le cycle de vie FastAPI/Starlette).
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
