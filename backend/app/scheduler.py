import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.pipeline import run_full_check

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _job():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


def start_scheduler():
    scheduler.add_job(
        _job,
        "interval",
        minutes=settings.check_interval_minutes,
        id="deal_check",
        replace_existing=True,
        next_run_time=None,  # on laisse APScheduler programmer le premier run après l'intervalle
    )
    scheduler.start()
    logger.info(
        "Scheduler démarré : vérification toutes les %d minutes",
        settings.check_interval_minutes,
    )
