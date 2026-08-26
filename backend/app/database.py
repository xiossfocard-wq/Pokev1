import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

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


# Colonnes ajoutees apres la mise en service. `create_all` ne cree que les
# TABLES manquantes, jamais les colonnes manquantes d'une table existante :
# sans ce rattrapage, une nouvelle colonne n'existerait qu'en local et la
# prod planterait a la premiere lecture.
#
# C'est un pis-aller assume, pas un systeme de migration. Des que les
# changements de schema deviennent frequents ou moins triviaux qu'un ajout
# de colonne nullable, passer a Alembic.
_COLONNES_AJOUTEES = {
    "listings": [
        ("manual_status", "VARCHAR(16)"),
        ("manual_reference_price", "DOUBLE PRECISION"),
        ("manual_reviewed_at", "TIMESTAMP"),
    ],
}


def _ajouter_colonnes_manquantes():
    from sqlalchemy import inspect, text

    inspecteur = inspect(engine)
    tables = set(inspecteur.get_table_names())

    with engine.begin() as connexion:
        for table, colonnes in _COLONNES_AJOUTEES.items():
            if table not in tables:
                continue  # create_all vient de la creer avec tout dedans
            existantes = {c["name"] for c in inspecteur.get_columns(table)}
            for nom, type_sql in colonnes:
                if nom in existantes:
                    continue
                # SQLite ne connait pas DOUBLE PRECISION ni TIMESTAMP.
                type_final = type_sql
                if engine.dialect.name == "sqlite":
                    type_final = {"DOUBLE PRECISION": "REAL", "TIMESTAMP": "DATETIME"}.get(
                        type_sql, type_sql
                    )
                connexion.execute(text(f"ALTER TABLE {table} ADD COLUMN {nom} {type_final}"))
                logger.info("Schema : colonne %s.%s ajoutee", table, nom)


def init_db():
    """Crée les tables si elles n'existent pas, puis rattrape les colonnes
    ajoutées après coup. Suffisant pour le v1 ; pour des migrations plus
    fines en évolution du schéma, passer à Alembic."""
    from app import models  # noqa: F401  (assure l'enregistrement des modèles)
    Base.metadata.create_all(bind=engine)
    _ajouter_colonnes_manquantes()
