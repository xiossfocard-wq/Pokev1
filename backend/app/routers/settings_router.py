from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings as app_settings
from app.models import AppSettings
from app.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "deal_score_threshold": app_settings.default_deal_score_threshold,
    "margin_weight": 0.5,
    "quality_weight": 0.3,
    "seller_weight": 0.2,
    "check_interval_minutes": app_settings.check_interval_minutes,
}


def _load_all(db: Session) -> dict:
    rows = db.query(AppSettings).all()
    values = dict(DEFAULTS)
    for row in rows:
        if row.key in values:
            values[row.key] = row.value
    return values


@router.get("", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _load_all(db)


@router.put("", response_model=SettingsOut)
def update_settings(update: SettingsUpdate, db: Session = Depends(get_db)):
    updates = update.model_dump(exclude_none=True)
    for key, value in updates.items():
        row = db.query(AppSettings).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.add(AppSettings(key=key, value=value))
    db.commit()
    return _load_all(db)
