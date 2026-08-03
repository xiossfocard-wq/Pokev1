import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.scheduler import start_scheduler
from app.routers import listings, settings_router, admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    missing = settings.missing_required_for_startup()
    if missing:
        logger.warning(
            "Démarrage avec des modules inactifs faute de configuration :\n- %s",
            "\n- ".join(missing),
        )
    start_scheduler()
    yield


app = FastAPI(title="Pokémon Deal Hunter API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # à restreindre à l'URL du frontend en production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router)
app.include_router(settings_router.router)
app.include_router(admin.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
