import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.pipeline import run_full_check, enrich_card_images
from app.services.card_catalog import enregistrer_releve_du_jour

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _job():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


def _job_releve_quotidien():
    """Un releve de prix par jour, pour tout le catalogue.

    C'est ce qui rend les tendances de fond possibles : la source ne publie
    qu'un prix instantane et une variation 7 jours, et le passe ne se
    reconstitue pas apres coup. Chaque jour manque est un trou definitif
    dans la courbe, d'ou une tache dediee plutot qu'un calcul a la demande.
    """
    db = SessionLocal()
    try:
        enregistrer_releve_du_jour(db)
    except Exception:  # noqa: BLE001 - une tache de fond ne doit pas tuer le scheduler
        logger.exception("Releve de prix quotidien echoue")
    finally:
        db.close()


def _job_images():
    """Complete le visuel des cartes, par petits lots.

    Separe du cycle principal parce qu'il interroge une autre source a un
    autre rythme : le catalogue compte des milliers de cartes, les images se
    remplissent sur plusieurs heures sans bloquer la chasse aux annonces.
    """
    db = SessionLocal()
    try:
        enrich_card_images(db, limit=40)
    except Exception:  # noqa: BLE001
        logger.exception("Enrichissement des visuels echoue")
    finally:
        db.close()


def start_scheduler():
    if not settings.scheduler_enabled:
        logger.info(
            "Scheduler desactive (SCHEDULER_ENABLED=false) : aucune collecte "
            "automatique. Les routes /api/admin/* restent utilisables pour "
            "declencher un passage a la main."
        )
        return

    scheduler.add_job(
        _job,
        "interval",
        minutes=settings.check_interval_minutes,
        id="deal_check",
        replace_existing=True,
        next_run_time=None,  # on laisse APScheduler programmer le premier run après l'intervalle
    )

    # 03:00 : creux d'activite, et apres la synchronisation nocturne des
    # prix, donc le releve porte sur des valeurs fraiches.
    scheduler.add_job(
        _job_releve_quotidien,
        "cron",
        hour=3,
        minute=0,
        id="card_price_snapshot",
        replace_existing=True,
    )

    scheduler.add_job(
        _job_images,
        "interval",
        minutes=30,
        id="card_images",
        replace_existing=True,
        next_run_time=None,
    )

    scheduler.start()
    logger.info(
        "Scheduler demarre : verification toutes les %d minutes, releve de "
        "prix quotidien a 03:00, visuels toutes les 30 minutes",
        settings.check_interval_minutes,
    )
