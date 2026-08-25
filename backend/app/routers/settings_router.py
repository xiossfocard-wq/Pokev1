from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import settings as app_settings
from app.models import AppSettings
from app.schemas import SettingsOut, SettingsUpdate
# DEFAULTS etait duplique ici ET dans settings_service.py : ajouter un
# reglage d'un seul cote suffisait a le rendre invisible de l'autre.
# Une seule definition, dans settings_service.
from app.settings_service import DEFAULTS, load_app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _load_all(db: Session) -> dict:
    return load_app_settings(db)


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
