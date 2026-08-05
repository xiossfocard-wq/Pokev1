from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLite a besoin de cet argument en usage multi-thread (utilisé seulement
# en dev local ; en prod on utilise Postgres via DATABASE_URL).
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Crée les tables si elles n'existent pas. Suffisant pour le v1 ;
    pour des migrations plus fines en évolution du schéma, passer à Alembic."""
    from app import models  # noqa: F401  (assure l'enregistrement des modèles)
    Base.metadata.create_all(bind=engine)
