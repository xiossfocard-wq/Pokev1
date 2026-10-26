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
        # Renommage du 14/10/2026 vers is_popular_character : le champ
        # designe un personnage phare, le nom precedent nommait un jeu.
        # L'ancienne colonne reste en base sans gener (nullable, plus lue) ;
        # la nouvelle est ajoutee ici pour les bases deja deployees.
        ("is_popular_character", "BOOLEAN"),
        ("matched_card_id", "INTEGER"),
        ("manual_status", "VARCHAR(16)"),
        ("manual_reference_price", "DOUBLE PRECISION"),
        ("manual_reviewed_at", "TIMESTAMP"),
        # Cout reel d'un achat et etat declare sur Vinted (26/10/2026).
        ("price_incl_protection", "DOUBLE PRECISION"),
        ("seller_condition", "VARCHAR(64)"),
        ("purchase_cost_eur", "DOUBLE PRECISION"),
        ("purchase_cost_detail", "JSON"),
        # Mode collection : economie par rapport a la cote (26/10/2026).
        ("savings_eur", "DOUBLE PRECISION"),
        ("savings_ratio", "DOUBLE PRECISION"),
    ],
    # « Ma liste » : date de la derniere recherche Vinted (26/10/2026).
    "cartes_suivies": [
        ("derniere_recherche_at", "TIMESTAMP"),
    ],
    # Exploration du catalogue par theme + visuel de la carte (10/10/2026).
    "market_card_prices": [
        ("theme_slugs", "VARCHAR(512)"),
        ("search_key", "VARCHAR(512)"),
        ("image_url", "VARCHAR(1024)"),
        ("image_source", "VARCHAR(32)"),
        ("image_checked_at", "TIMESTAMP"),
        # Langue du nom affiche (22/10/2026).
        ("language", "VARCHAR(8)"),
    ],
}


# Contraintes NOT NULL a relacher sur les bases deja en service. Ajouter une
# colonne et relacher une contrainte sont deux operations differentes :
# `create_all` ne touche pas une table existante, donc une colonne passee a
# nullable=False -> nullable=True dans le modele reste NOT NULL en base, et
# l'insertion d'un NULL echoue en prod alors qu'elle passe en local sur une
# base neuve.
_CONTRAINTES_RELACHEES = {
    # 20/10/2026 : une carte peut etre inscrite au catalogue sans qu'on
    # connaisse son prix (voir le commentaire sur MarketCardPrice.price_eur).
    "market_card_prices": ["price_eur"],
}


def _relacher_contraintes_not_null():
    """Passe en nullable les colonnes listees dans _CONTRAINTES_RELACHEES.

    Postgres sait le faire en place. SQLite ne sait pas modifier une
    contrainte de colonne : il faut reconstruire la table. On ne la
    reconstruit que si la contrainte est encore la, pour que le demarrage
    normal ne recopie pas la table a chaque fois.
    """
    from sqlalchemy import inspect, text

    inspecteur = inspect(engine)
    tables = set(inspecteur.get_table_names())

    for table, colonnes in _CONTRAINTES_RELACHEES.items():
        if table not in tables:
            continue  # create_all vient de la creer deja nullable
        etat = {c["name"]: c for c in inspecteur.get_columns(table)}
        a_relacher = [
            nom for nom in colonnes
            if nom in etat and not etat[nom]["nullable"]
        ]
        if not a_relacher:
            continue

        if engine.dialect.name == "sqlite":
            _reconstruire_table_sqlite(table, set(etat))
            logger.info("Schema : table %s reconstruite pour relacher NOT NULL sur %s",
                        table, ", ".join(a_relacher))
        else:
            with engine.begin() as connexion:
                for nom in a_relacher:
                    connexion.execute(text(
                        f"ALTER TABLE {table} ALTER COLUMN {nom} DROP NOT NULL"
                    ))
                    logger.info("Schema : %s.%s passe en nullable", table, nom)


def _reconstruire_table_sqlite(table: str, colonnes_existantes: set):
    """Reconstruit une table SQLite d'apres le modele, en conservant les
    donnees. Seules les colonnes presentes des deux cotes sont recopiees :
    une colonne disparue du modele est abandonnee, une colonne nouvelle
    prend sa valeur par defaut.

    Les cles etrangeres sont desactivees le temps de l'echange, sinon le
    DROP de l'ancienne table ferait tomber les lignes qui la referencent.
    """
    from sqlalchemy import text

    cible = Base.metadata.tables[table]
    communes = [c.name for c in cible.columns if c.name in colonnes_existantes]
    liste = ", ".join(f'"{nom}"' for nom in communes)
    provisoire = f"{table}__ancienne"

    with engine.begin() as connexion:
        connexion.execute(text("PRAGMA foreign_keys=OFF"))
        connexion.execute(text(f'ALTER TABLE "{table}" RENAME TO "{provisoire}"'))

    try:
        cible.create(bind=engine)
        with engine.begin() as connexion:
            connexion.execute(text(
                f'INSERT INTO "{table}" ({liste}) SELECT {liste} FROM "{provisoire}"'
            ))
            connexion.execute(text(f'DROP TABLE "{provisoire}"'))
    except Exception:
        # Remettre la table d'origine en place : mieux vaut repartir avec
        # l'ancien schema qu'avec une table disparue.
        with engine.begin() as connexion:
            if engine.dialect.name == "sqlite":
                connexion.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
                connexion.execute(text(f'ALTER TABLE "{provisoire}" RENAME TO "{table}"'))
        raise
    finally:
        with engine.begin() as connexion:
            connexion.execute(text("PRAGMA foreign_keys=ON"))


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
    _relacher_contraintes_not_null()
