"""
Apparier les illustrations alternatives entre les deux sources.

LE PROBLEME, ETABLI PAR CONSTAT
-------------------------------
La liste officielle declare bien les illustrations alternatives : les
identifiants « OP17-001_p1 », « OP17-005_p2 », « EB04-061_p2 » sont releves
sur sa page OP17. Des fiches existent donc pour elles, et elles sont vides.

En face, la source des prix donne « (Parallele) » et « (Manga) » pour un
meme code — a 5,80 EUR et 500 EUR. Les effectifs concordent : trois
impressions declarees d'un cote, trois chiffrees de l'autre.

Ce qui manque est l'APPARIEMENT. Et dans les champs releves sur la page
officielle — code, rarete, type, nom — les deux parallèles sont
rigoureusement identiques. Rien n'y designe celui qui porte l'illustration
manga. Seul le fichier image differe.

CE MODULE NE DECIDE RIEN, IL MESURE
-----------------------------------
Decreter que « (Manga) » est la deuxieme alternative plutot que la premiere
poserait 500 EUR sur une carte qui en vaut 5,80. C'est exactement l'erreur
que tout ce rapprochement cherche a empecher, et une hypothese commode ne
vaut pas mieux ici qu'ailleurs.

La seule information qui distingue reellement les deux parallèles etant
l'image, on compare les images, et on RAPPORTE l'appariement qu'elles
suggerent avec sa MARGE. Il sera applique quand la mesure l'aura etabli.

POURQUOI UNE MARGE, ET PAS UN SIMPLE « PLUS PROCHE »
---------------------------------------------------
Prendre le plus proche rend toujours une reponse, y compris quand les
images ne se ressemblent pas du tout. La marge — l'ecart entre le meilleur
appariement et le suivant — dit si la reponse tient a quelque chose. Une
marge nulle signifie que les deux appariements sont aussi defendables, donc
qu'on ne sait pas, et c'est une conclusion legitime.
"""
import hashlib
import io
import itertools
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:  # Pillow est optionnel : sans lui, la comparaison binaire fonctionne.
    from PIL import Image
except ImportError:  # pragma: no cover - depend de l'installation
    Image = None

COTE = 8                 # 8x8 pixels -> empreinte de 64 bits
BITS = COTE * COTE

# En-dessous de cette distance, deux images sont tenues pour la meme
# illustration. Valeur usuelle pour une empreinte de 64 bits : au-dela, les
# differences ne sont plus celles d'un recadrage ou d'un reencodage.
DISTANCE_IDENTIQUE = 10


def pillow_disponible() -> bool:
    """Dit si la comparaison perceptive est possible.

    Rendu dans le compte rendu : sans cette information, un rapport vide se
    lirait comme « les images ne se ressemblent pas » alors qu'il signifie
    « rien n'a pu etre compare ».
    """
    return Image is not None


def empreinte_binaire(donnees: Optional[bytes]) -> Optional[str]:
    """Empreinte des OCTETS. Egalite = fichier rigoureusement identique.

    Premiere chose a verifier, et la moins couteuse : si la boutique reheberge
    le fichier officiel tel quel, l'appariement est exact et il n'y a aucune
    comparaison d'image a faire.
    """
    if not donnees:
        return None
    return hashlib.sha256(donnees).hexdigest()[:16]


def empreinte_perceptive(donnees: Optional[bytes]) -> Optional[int]:
    """Empreinte de l'IMAGE, insensible a la taille et au reencodage.

    Moyenne des 64 pixels d'une reduction en niveaux de gris, puis un bit
    par pixel selon qu'il est au-dessus ou en-dessous. Deux rendus de la
    meme illustration restent proches ; deux illustrations differentes non.

    Rend None si l'image est illisible ou Pillow absent : une empreinte
    inventee serait pire que pas d'empreinte, parce qu'elle apparierait.
    """
    if Image is None or not donnees:
        return None
    try:
        with Image.open(io.BytesIO(donnees)) as image:
            petite = image.convert("L").resize((COTE, COTE))
            pixels = list(petite.getdata())
    except Exception as erreur:  # noqa: BLE001 - toute image illisible
        logger.debug("Image illisible : %s", erreur)
        return None

    if len(pixels) != BITS:
        return None
    moyenne = sum(pixels) / len(pixels)
    empreinte = 0
    for rang, pixel in enumerate(pixels):
        if pixel > moyenne:
            empreinte |= 1 << rang
    return empreinte


def distance(a: Optional[int], b: Optional[int]) -> Optional[int]:
    """Nombre de bits qui diffèrent. None si l'une des empreintes manque."""
    if a is None or b is None:
        return None
    return bin(a ^ b).count("1")


def apparier(officielles: Dict[int, Optional[int]],
             boutique: Dict[str, Optional[int]]) -> dict:
    """Quel rang officiel correspond a quelle mention de la boutique ?

    Cherche l'appariement COMPLET de moindre distance totale, en essayant
    toutes les permutations — leur nombre est minuscule (trois impressions
    au plus) et l'optimum exact evite les pieges d'un appariement glouton,
    ou le premier choix condamne les suivants.
    """
    rangs = sorted(officielles)
    marques = list(boutique)

    if not rangs or not marques:
        return {"verdict": "rien a comparer", "fiable": False, "couples": []}

    if len(rangs) != len(marques):
        return {
            "verdict": f"effectifs differents : {len(rangs)} rang(s) officiel(s) "
                       f"contre {len(marques)} mention(s)",
            "fiable": False, "couples": [],
        }

    if any(officielles[r] is None for r in rangs) or \
       any(boutique[m] is None for m in marques):
        return {"verdict": "au moins une image n'a pas pu etre lue",
                "fiable": False, "couples": []}

    totaux: List[tuple] = []
    for permutation in itertools.permutations(marques):
        total = sum(distance(officielles[r], boutique[m])
                    for r, m in zip(rangs, permutation))
        totaux.append((total, permutation))
    totaux.sort(key=lambda c: c[0])

    meilleur, permutation = totaux[0]
    # La MARGE : de combien le meilleur appariement devance le suivant. Un
    # seul appariement possible (une seule impression) ne se compare a rien,
    # et n'a donc rien a departager.
    marge = (totaux[1][0] - meilleur) if len(totaux) > 1 else None

    couples = [
        {"rang_officiel": r, "mention": m,
         "distance": distance(officielles[r], boutique[m])}
        for r, m in zip(rangs, permutation)
    ]
    pire = max(c["distance"] for c in couples)

    # FIABLE demande les DEUX : que chaque couple se ressemble vraiment, et
    # qu'aucun autre appariement ne soit aussi defendable. Le premier sans
    # le second decrirait un appariement ou tout ressemble a tout.
    fiable = pire <= DISTANCE_IDENTIQUE and (marge is None or marge > pire)

    return {
        "verdict": "appariement etabli" if fiable else "appariement incertain",
        "fiable": fiable,
        "couples": couples,
        "distance_totale": meilleur,
        "marge": marge,
        "pire_distance": pire,
    }
