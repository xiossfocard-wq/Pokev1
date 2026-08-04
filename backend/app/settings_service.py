"""
Lecture/fusion des réglages modifiables depuis le dashboard (`AppSettings`
en DB) avec leurs valeurs par défaut (issues de la config statique/.env).

Partagé entre `routers/settings_router.py` (API de lecture/écriture) et
`pipeline.py` (qui doit appliquer ces réglages au scoring et aux
notifications — voir la note dans pipeline.py sur le bug corrigé : avant
ce module, les réglages enregistrés depuis le dashboard étaient bien
sauvegardés en DB mais n'étaient jamais relus par le pipeline, qui
continuait à utiliser des valeurs figées. Centraliser la lecture ici évite
que ce genre d'écart réapparaisse.
"""
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.models import AppSettings

DEFAULTS = {
    "deal_score_threshold": app_settings.default_deal_score_threshold,
    "margin_weight": 0.5,
    "quality_weight": 0.3,
    "seller_weight": 0.2,
    "check_interval_minutes": app_settings.check_interval_minutes,
}


def load_app_settings(db: Session) -> dict:
    rows = db.query(AppSettings).all()
    values = dict(DEFAULTS)
    for row in rows:
        if row.key in values:
            values[row.key] = row.value
    return values
