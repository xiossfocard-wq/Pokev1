"""
Catalogue One Piece depuis le releve de la liste officielle.

POURQUOI CETTE PIECE
--------------------
Le catalogue etait vide, et un catalogue vide vide tout le reste : sans code
de carte il n'y a pas de visuel (il se deduit du code), sans carte il n'y a
pas de prix de reference, donc pas de marge et pas de score d'affaire.

La premiere source retenue (ZebraDex) s'est revelee ne pas couvrir One Piece
du tout. La lecon n'etait pas « mauvaise source » mais « une seule source » :
ce module en ouvre une troisieme, a cote de l'import de fichier.

CE QUE CETTE SOURCE EST, EXACTEMENT
-----------------------------------
Le paquet npm `one-piece-card-game-json` est un releve automatise de la liste
OFFICIELLE du jeu (onepiece-cardgame.com), republie a chaque changement par
son auteur. On ne lit donc pas une boutique ni un agregateur de prix : on lit
la liste des cartes qui existent.

On passe par le registre npm et non par le site officiel pour une raison
assumee : le registre est une API publique faite pour etre appelee par des
programmes (c'est ce que fait `npm install`), versionnee et immuable. Il n'y
a pas de page a explorer et donc pas de politique robots.txt a respecter —
l'URL `registry.npmjs.org/robots.txt` rend d'ailleurs le paquet npm NOMME
« robots.txt », ce qui dit bien que cet hote est un espace de noms d'API.

CE QU'ELLE DONNE ET CE QU'ELLE NE DONNE PAS
-------------------------------------------
Elle donne   : le code, le nom, la serie, la rarete, la variante.
Elle ne donne PAS de prix. Les cartes entrent donc au catalogue sans prix de
reference, et tout ce qui en derive s'abstient tant qu'une source de prix
n'est pas branchee. C'est dit dans le rapport d'import (`sans_prix`) plutot
que masque par un 0.00 EUR qui se lirait comme « cette carte ne vaut rien ».

LA LANGUE
---------
Le paquet publie deux locales : `en` et `jp`. Il n'y a pas de locale `fr`.
Les noms repris ici sont donc la romanisation INTERNATIONALE des noms de
personnages — celle qu'emploient aussi les vendeurs francais dans leurs
annonces (« Roronoa Zoro OP01-001 parallele »), ce qui est precisement
l'usage qu'on en fait : rapprocher un titre d'annonce d'une carte.

Ce qui est francais, en revanche, et verifiable :
  - les VISUELS, deduits du code sur `fr.onepiece-cardgame.com`
    (voir settings.card_image_base_url) ;
  - les ANNONCES collectees, qui viennent de places de marche francaises.

Si une carte porte un nom francais different sur l'impression FR, c'est la
liste FR officielle qui le dira : `display_name` est fait pour etre ecrase
par un enrichissement ulterieur, sans toucher au reste de la fiche.
"""
import gzip
import io
import json
import logging
import re
import tarfile
from pathlib import Path
from typing import List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

PAQUET = "one-piece-card-game-json"
REGISTRE = "https://registry.npmjs.org"

# L'archive fait ~500 Ko et le JSON decompresse ~4 Mo. Les plafonds sont la
# pour qu'une archive inattendue ne remplisse pas la memoire du conteneur.
MAX_ARCHIVE_OCTETS = 20 * 1024 * 1024
MAX_JSON_OCTETS = 64 * 1024 * 1024
DELAI = 60

# Instantane versionne dans le depot. Il existe pour que l'application
# fonctionne en local SANS reseau : le catalogue est la, dans le depot, et se
# charge hors ligne. Le reseau ne sert plus qu'a le rafraichir.
CHEMIN_INSTANTANE = Path(__file__).resolve().parent.parent / "data" / "catalogue_opcg.csv.gz"

# Raretes du jeu. Le code brut est conserve EN TETE du libelle parce que les
# motifs de card_themes.py le testent au mot entier (`\bsr\b`, `\bsec\b`) et
# que les vendeurs francais ecrivent eux aussi « SR », « SEC » dans leurs
# titres. Le libelle long suit, pour que la fiche reste lisible.
RARETES = {
    "C": "C (Common)",
    "UC": "UC (Uncommon)",
    "R": "R (Rare)",
    "SR": "SR (Super Rare)",
    "SEC": "SEC (Secret Rare)",
    "L": "L (Leader)",
    "P": "P (Promo)",
    "TR": "TR (Treasure Rare)",
    "SP CARD": "SP CARD (Special)",
}

# La variante va dans le NOM, pas dans la rarete. Deux raisons : le theme
# « Alternative / Parallele » de card_themes.py se declenche sur le motif
# `\bparallele\b` dans le nom, et surtout le slug obtenu
# (« roronoa-zoro-parallele ») est exactement celui que title_parser tire
# d'un titre d'annonce francais « Roronoa Zoro parallele OP01-001 ». Les deux
# bouts de la chaine se rencontrent sans table de correspondance.
MARQUE_ALTERNATIVE = "Parallèle"


def _nettoyer_serie(brut: Optional[str]) -> Optional[str]:
    """« -ROMANCE DAWN- [OP-01] » -> « Romance Dawn (OP-01) ».

    La liste officielle encadre le nom de tirets et met le code entre
    crochets. On garde les deux informations mais sous une forme lisible dans
    une interface.
    """
    if not brut or brut.strip() in ("", "-"):
        return None
    texte = brut.strip()

    code = None
    trouve = re.search(r"\[([^\]]+)\]\s*$", texte)
    if trouve:
        code = trouve.group(1).strip()
        texte = texte[: trouve.start()].strip()

    texte = texte.strip("-").strip()
    # Les noms sont tout en capitales. On les repasse en casse de titre, en
    # laissant les apostrophes tranquilles (« KAMI'S ISLAND » -> « Kami's »,
    # pas « Kami'S »).
    if texte and texte == texte.upper():
        texte = re.sub(r"[A-ZÀ-Þ][A-ZÀ-Þ’'ʼ]*",
                       lambda m: m.group(0).capitalize(), texte)
        # Les mots de liaison restent en minuscules, sauf en tete :
        # « Kingdoms of Intrigue », pas « Kingdoms Of Intrigue ».
        LIAISONS = {"of", "the", "in", "a", "an", "and", "to", "for", "on", "s"}
        mots = texte.split(" ")
        texte = " ".join(
            mot if i == 0 or mot.lower() not in LIAISONS else mot.lower()
            for i, mot in enumerate(mots)
        )
    if not texte:
        return code
    return f"{texte} ({code})" if code else texte


def _rarete_lisible(brut: Optional[str]) -> Optional[str]:
    if not brut:
        return None
    cle = brut.strip().upper()
    return RARETES.get(cle, brut.strip())


def version_publiee(session=None) -> Tuple[str, str]:
    """Rend (version, url_archive) de la derniere version publiee."""
    http = session or requests
    reponse = http.get(f"{REGISTRE}/{PAQUET}", timeout=DELAI)
    reponse.raise_for_status()
    meta = reponse.json()
    version = meta["dist-tags"]["latest"]
    return version, meta["versions"][version]["dist"]["tarball"]


def telecharger_cartes(locale: str = "en", session=None) -> Tuple[str, List[dict]]:
    """Rend (version, cartes brutes) depuis le registre npm.

    L'archive n'est jamais ecrite sur le disque ni extraite en bloc : on
    ouvre le seul membre attendu et on le lit en memoire. Cela ecarte d'un
    coup les traversees de chemin et les bombes d'extraction.
    """
    version, url = version_publiee(session=session)
    http = session or requests
    reponse = http.get(url, timeout=DELAI)
    reponse.raise_for_status()

    octets = reponse.content
    if len(octets) > MAX_ARCHIVE_OCTETS:
        raise ValueError(
            f"archive inattendue : {len(octets)} octets, plafond {MAX_ARCHIVE_OCTETS}"
        )

    attendu = f"package/{locale}/cards.json"
    with tarfile.open(fileobj=io.BytesIO(octets), mode="r:gz") as archive:
        membre = next((m for m in archive.getmembers() if m.name == attendu), None)
        if membre is None:
            noms = [m.name for m in archive.getmembers()][:10]
            raise ValueError(
                f"{attendu} absent de l'archive {PAQUET}@{version} "
                f"(contenu : {noms})"
            )
        if membre.size > MAX_JSON_OCTETS:
            raise ValueError(
                f"{attendu} fait {membre.size} octets, plafond {MAX_JSON_OCTETS}"
            )
        flux = archive.extractfile(membre)
        if flux is None:
            raise ValueError(f"{attendu} n'est pas un fichier regulier")
        cartes = json.loads(flux.read().decode("utf-8"))

    if not isinstance(cartes, list):
        raise ValueError(f"{attendu} ne contient pas une liste de cartes")
    logger.info("Jeu de donnees OPCG : %s@%s, %d entrees (%s)",
                PAQUET, version, len(cartes), locale)
    return version, cartes


def convertir(brutes: List[dict]) -> List[dict]:
    """Ramene les entrees brutes au contrat de catalog_import.

    Un point demande une decision : la liste officielle compte 4845 entrees
    pour 2785 codes, parce qu'une carte et son art alternatif PARTAGENT le
    code. Les laisser fusionner ferait disparaitre la distinction qui compte
    le plus sur ce marche — un art alternatif ne vaut pas le prix de la carte
    ordinaire.

    On produit donc deux fiches au plus par code : l'ordinaire, et la
    parallele. Les paralleles multiples d'un meme code (reimpressions dans
    des coffrets differents) sont regroupees sous une seule fiche, parce
    qu'une annonce francaise dit « parallele » et jamais de quel coffret elle
    vient : une distinction que le titre ne porte pas est une distinction
    qu'on ne saurait pas rapprocher.
    """
    vues = set()
    lignes: List[dict] = []

    for carte in brutes:
        code = (carte.get("card_number") or "").strip()
        nom = (carte.get("card_name") or "").strip()
        if not code or not nom:
            continue

        alternative = bool(carte.get("is_alternate_art"))
        cle = (code, alternative)
        if cle in vues:
            continue
        vues.add(cle)

        lignes.append({
            "card_code": code,
            "display_name": f"{nom} ({MARQUE_ALTERNATIVE})" if alternative else nom,
            "series_name": _nettoyer_serie(carte.get("card_sets")),
            "rarity": _rarete_lisible(carte.get("rarity")),
            # Pas de prix : cette source n'en publie pas. La colonne est
            # laissee vide plutot que remplie d'un zero (voir l'en-tete).
            "price_eur": "",
        })

    return lignes


# --- instantane local ----------------------------------------------------

COLONNES = ("card_code", "display_name", "series_name", "rarity", "price_eur")


def ecrire_instantane(lignes: List[dict], chemin: Optional[Path] = None) -> Path:
    """Ecrit l'instantane compresse lu par `charger_instantane`."""
    import csv

    cible = Path(chemin) if chemin else CHEMIN_INSTANTANE
    cible.parent.mkdir(parents=True, exist_ok=True)
    tampon = io.StringIO()
    graveur = csv.DictWriter(tampon, fieldnames=list(COLONNES), extrasaction="ignore")
    graveur.writeheader()
    for ligne in lignes:
        graveur.writerow({c: (ligne.get(c) if ligne.get(c) is not None else "")
                          for c in COLONNES})
    cible.write_bytes(gzip.compress(tampon.getvalue().encode("utf-8")))
    return cible


def charger_instantane(chemin: Optional[Path] = None) -> List[dict]:
    """Lit l'instantane versionne. Rend [] s'il n'est pas la."""
    import csv

    # Path() et non le defaut tel quel : l'appelant peut passer une chaine,
    # et un `str` n'a pas de .exists().
    source = Path(chemin or CHEMIN_INSTANTANE)
    if not source.exists():
        return []
    texte = gzip.decompress(source.read_bytes()).decode("utf-8")
    return list(csv.DictReader(io.StringIO(texte)))


def charger_catalogue(db, rafraichir: bool = False, locale: str = "en",
                      session=None) -> dict:
    """Remplit le catalogue depuis cette source. C'est le point d'entree.

    Par defaut on lit l'instantane du depot : c'est instantane, hors ligne,
    et c'est exactement ce que les tests ont valide. `rafraichir=True` va
    rechercher la derniere version publiee sur le registre et reecrit
    l'instantane au passage, pour que le depot ne derive pas de ce que
    l'application sert.

    Si le reseau echoue pendant un rafraichissement, on se rabat sur
    l'instantane en le DISANT, plutot que de laisser l'appel echouer et le
    catalogue vide.
    """
    from app.services.catalog_import import importer_catalogue

    origine, version, avertissement = "instantane", None, None

    if rafraichir:
        try:
            version, brutes = telecharger_cartes(locale=locale, session=session)
            lignes = convertir(brutes)
            ecrire_instantane(lignes)
            origine = f"registre npm ({PAQUET}@{version})"
        except Exception as erreur:          # noqa: BLE001 — on degrade, on ne casse pas
            logger.warning("Rafraichissement OPCG impossible (%s) : repli sur l'instantane",
                           erreur)
            avertissement = (
                f"rafraichissement impossible ({erreur}) — "
                f"l'instantane versionne a ete utilise a la place"
            )
            lignes = charger_instantane()
    else:
        lignes = charger_instantane()

    if not lignes:
        return {
            "origine": origine,
            "erreur": (
                "aucune carte a importer : l'instantane "
                f"{CHEMIN_INSTANTANE} est absent ou vide. "
                "Relancer avec rafraichir=true pour le reconstruire."
            ),
            "avertissement": avertissement,
        }

    rapport = importer_catalogue(db, lignes)
    rapport["origine"] = origine
    if version:
        rapport["version_source"] = version
    if avertissement:
        rapport["avertissement"] = avertissement
    # Dit explicitement ce que cette source ne fournit pas, pour qu'un
    # rapport « 3868 importees » ne se lise pas comme « catalogue complet ».
    rapport["prix"] = (
        "Cette source ne publie pas de prix : les cartes entrent sans prix de "
        "reference. Les marges et les scores d'affaire resteront vides tant "
        "qu'une source de prix n'est pas branchee (import de fichier avec une "
        "colonne prix, ou collecteur de place de marche)."
    )
    return rapport
