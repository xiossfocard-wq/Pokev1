"""
Import du catalogue depuis un fichier, quelle que soit sa provenance.

POURQUOI CETTE PIECE
--------------------
Le catalogue n'avait qu'une seule facon d'etre rempli : la synchronisation
ZebraDex. Quand cette source s'est reveleee ne pas couvrir One Piece, il
n'est rien reste — pas de catalogue, donc pas de prix de reference, pas de
score d'affaire, pas de visuels (ils se deduisent du code carte).

Le defaut n'etait pas le choix de ZebraDex, c'etait qu'il n'y avait qu'un
seul chemin. Ce module en ouvre un second, independant du reseau et de la
forme des pages : on donne un fichier, il remplit le catalogue.

Cela vaut quelle que soit la source retenue ensuite. Une liste officielle,
une boutique, un export fait a la main : il suffit de la ramener a ce
contrat.

LE CONTRAT
----------
CSV (separateur « ; » ou « , ») ou JSON (liste d'objets). Par carte :

    card_code      OBLIGATOIRE  « OP01-120 », « OP01 120 », « OP01-4 »
    display_name   OBLIGATOIRE  le nom FRANCAIS imprime sur la carte
    price_eur      OBLIGATOIRE  « 12,50 € », « 12.50 », « 1 234,56 »
    series_name    facultatif   « Romance Dawn »
    rarity         facultatif   « Secret Rare »

Rien d'autre n'est demande : les themes, la cle de recherche et le visuel
sont DERIVES. Le visuel en particulier se deduit du code et se remplit tout
seul au passage suivant de l'enrichissement.

CE QUI EST REFUSE EST DIT
-------------------------
Chaque ligne rejetee est rendue avec son numero et sa raison. Un import qui
avalerait silencieusement la moitie d'un fichier serait pire qu'un import
qui echoue : c'est exactement le genre de silence qui a laisse croire que
le catalogue se remplissait alors qu'il restait vide.
"""
import csv
import io
import json
import logging
import re
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.collectors.card_images import code_canonique
from app.matching.title_parser import normalize as normaliser_titre
from app.models import MarketCardPrice
from app.services.card_themes import (
    cle_de_recherche, encoder_themes, themes_de_la_carte,
)

logger = logging.getLogger(__name__)

SOURCE = "import"

# Noms de colonnes tolerés. Une source exportee a la main n'utilisera pas
# forcement nos intitules : autant accepter les evidences plutot que de
# renvoyer un fichier entier pour un en-tete.
ALIAS = {
    "card_code": ("card_code", "code", "numero", "num", "card number", "cardnumber"),
    "display_name": ("display_name", "nom", "name", "carte", "card", "titre"),
    "price_eur": ("price_eur", "prix", "price", "prix_eur", "tarif", "montant"),
    "series_name": ("series_name", "serie", "série", "series", "set", "extension"),
    "rarity": ("rarity", "rarete", "rareté", "raretè"),
}

# Limite de securite : un fichier enorme bloquerait la requete et la base.
MAX_LIGNES = 20000


def _nettoyer_prix(brut) -> Optional[float]:
    """« 12,50 € », « 1 234,56 », « €12.50 » -> 12.5

    La virgule decimale francaise est le cas NORMAL ici, pas l'exception :
    la source de prix visee est une boutique francaise.
    """
    if brut is None:
        return None
    if isinstance(brut, (int, float)):
        return float(brut)

    texte = str(brut).strip()
    if not texte:
        return None

    # Retire la devise, les espaces (y compris insecables) et tout ce qui
    # n'est ni chiffre ni separateur.
    texte = re.sub(r"[^\d,.\-]", "", texte.replace(" ", "").replace(" ", ""))
    if not texte:
        return None

    # Si les deux separateurs sont presents, le DERNIER est le decimal.
    if "," in texte and "." in texte:
        if texte.rfind(",") > texte.rfind("."):
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", "")
    elif "," in texte:
        texte = texte.replace(",", ".")

    try:
        valeur = float(texte)
    except ValueError:
        return None
    return valeur if valeur >= 0 else None


def slug_de_nom(nom: str) -> str:
    """Slug d'un nom de carte, DANS LA MEME FORME que les candidats tires
    d'un titre d'annonce.

    C'est ce qui rend le rapprochement par nom complet possible. Une
    decoupe differente des deux cotes casse ce niveau en silence : le
    prix retombe alors sur le nom usuel, moins sur, sans que rien ne le
    signale.

    Le piege concret, trouve en important de vraies cartes : «  Monkey D.
    Luffy » donnait « monkey-d.-luffy » avec le point, la ou le parseur de
    titre produit « monkey-d-luffy ». Les deux ne se rencontraient jamais.

    `normalize` vient du parseur lui-meme : une seule definition de ce
    qu'est un nom normalise, pas deux qui peuvent diverger.
    """
    return re.sub(r"[^a-z0-9]+", "-", normaliser_titre(nom)).strip("-")


def _colonne(ligne: dict, champ: str) -> Optional[str]:
    """Valeur d'un champ, quel que soit l'intitule utilise par la source."""
    normalise = {str(k).strip().lower(): v for k, v in ligne.items() if k is not None}
    for alias in ALIAS[champ]:
        if alias in normalise:
            valeur = normalise[alias]
            if valeur is not None and str(valeur).strip():
                return str(valeur).strip()
    return None


def analyser(contenu: str) -> Tuple[List[dict], Optional[str]]:
    """Lit un CSV ou un JSON et rend ses lignes. (lignes, erreur)."""
    texte = (contenu or "").strip()
    if not texte:
        return [], "fichier vide"

    if texte[0] in "[{":
        try:
            charge = json.loads(texte)
        except ValueError as exc:
            return [], f"JSON illisible : {exc}"
        if isinstance(charge, dict):
            # Tolerance : {"cartes": [...]} ou {"data": [...]}.
            for cle in ("cartes", "cards", "data", "results"):
                if isinstance(charge.get(cle), list):
                    charge = charge[cle]
                    break
        if not isinstance(charge, list):
            return [], "JSON attendu : une liste d'objets, un par carte"
        return [l for l in charge if isinstance(l, dict)], None

    premiere = texte.split("\n", 1)[0]
    separateur = ";" if premiere.count(";") > premiere.count(",") else ","
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=separateur)
    if not lecteur.fieldnames:
        return [], "CSV sans ligne d'en-tete"
    return list(lecteur), None


def importer_catalogue(db: Session, lignes: List[dict]) -> dict:
    """Remplit le catalogue depuis des lignes deja analysees.

    Les cartes existantes sont mises a jour, les nouvelles creees. La cle
    est (code canonique, nom) : la meme qu'ailleurs, pour qu'un import et
    une synchronisation ne creent pas deux fois la meme carte.
    """
    if len(lignes) > MAX_LIGNES:
        return {
            "lues": len(lignes),
            "importees": 0,
            "erreur": f"fichier trop grand ({len(lignes)} lignes, maximum {MAX_LIGNES})",
        }

    creees, mises_a_jour = 0, 0
    rejets: List[dict] = []

    for numero, ligne in enumerate(lignes, start=1):
        code_brut = _colonne(ligne, "card_code")
        nom = _colonne(ligne, "display_name")
        prix = _nettoyer_prix(_colonne(ligne, "price_eur"))

        code = code_canonique(code_brut) if code_brut else None

        if not code:
            rejets.append({"ligne": numero, "raison": (
                f"code de carte absent ou non reconnu ({code_brut!r}) — "
                f"attendu « OP01-120 », « ST01-001 », « EB01-012 » ou « P-001 »"
            )})
            continue
        if not nom:
            rejets.append({"ligne": numero, "code": code,
                           "raison": "nom de carte absent"})
            continue
        if prix is None:
            rejets.append({"ligne": numero, "code": code,
                           "raison": f"prix absent ou illisible "
                                     f"({_colonne(ligne, 'price_eur')!r})"})
            continue

        serie = _colonne(ligne, "series_name")
        rarete = _colonne(ligne, "rarity")
        name_slug = slug_de_nom(nom)

        valeurs = dict(
            display_name=nom,
            series_name=serie,
            rarity=rarete,
            price_eur=prix,
            source=SOURCE,
            # Derives, recalcules a chaque import : les listes de themes
            # evoluent, et une carte importee avant l'ajout d'un theme doit
            # le rejoindre au passage suivant.
            theme_slugs=encoder_themes(themes_de_la_carte(nom, rarete)),
            search_key=cle_de_recherche(nom, code),
        )

        existante = (
            db.query(MarketCardPrice)
            .filter_by(card_code=code, name_slug=name_slug)
            .first()
        )
        if existante:
            for cle, valeur in valeurs.items():
                setattr(existante, cle, valeur)
            mises_a_jour += 1
        else:
            db.add(MarketCardPrice(card_code=code, name_slug=name_slug, **valeurs))
            creees += 1

    db.commit()

    logger.info(
        "Import catalogue : %d lue(s), %d creee(s), %d mise(s) a jour, %d rejet(s)",
        len(lignes), creees, mises_a_jour, len(rejets),
    )
    return {
        "lues": len(lignes),
        "creees": creees,
        "mises_a_jour": mises_a_jour,
        "importees": creees + mises_a_jour,
        "rejetees": len(rejets),
        # Toutes les raisons, pas un echantillon : un rejet silencieux est
        # exactement ce qu'on cherche a ne plus jamais avoir.
        "rejets": rejets,
        "suite": (
            "Les visuels se deduisent du code et se rempliront au passage "
            "suivant de l'enrichissement, ou tout de suite avec "
            "POST /api/admin/enrich-card-images."
        ),
    }
