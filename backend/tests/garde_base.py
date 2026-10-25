"""
Garde-fou : un test qui vide des tables ne vise JAMAIS la base de travail.

POURQUOI CE FICHIER EXISTE
--------------------------
Le moteur SQLAlchemy est cree a l'IMPORT de app.database, a partir de
DATABASE_URL. Les modules de tests qui touchent la base fixent donc cette
variable sur un fichier temporaire avant tout import applicatif. Mais le
premier module a importer app.database l'emporte pour toute la suite : si un
module classe avant eux l'importe sans avoir fixe la variable, le moteur
pointe sur dev.db — et leurs setUp, qui commencent par vider les tables,
vident la base de travail.

C'est arrive le 24/10/2026 : un fichier de tests nouvellement ajoute,
classe avant les autres, a fait effacer un catalogue complet. Sur un poste
ou tourne la vraie application, ce serait le catalogue de l'utilisateur,
ses prix et ses annonces.

Le garde-fou ne repare pas l'ordre d'import : il le rend INOFFENSIF. Une
base mal choisie fait echouer le test, bruyamment, au lieu d'effacer des
donnees en silence.
"""
import os
import tempfile


def verifier_base_de_test() -> None:
    """Leve une erreur si la base courante n'est pas une base de test."""
    from app.database import engine

    if engine.url.get_backend_name() != "sqlite":
        raise RuntimeError(
            f"Les tests visent une base {engine.url.get_backend_name()} : refus de "
            "vider ses tables. Les tests ne tournent que sur SQLite temporaire."
        )

    chemin = engine.url.database or ""
    if chemin in ("", ":memory:"):
        return

    temporaire = os.path.realpath(tempfile.gettempdir())
    if os.path.realpath(chemin).startswith(temporaire + os.sep):
        return

    raise RuntimeError(
        f"Les tests visent {chemin}, qui n'est pas une base temporaire : refus "
        "de vider ses tables. Un module importe plus tot a sans doute charge "
        "app.database avant que DATABASE_URL ne soit fixee — voir "
        "tests/garde_base.py."
    )
