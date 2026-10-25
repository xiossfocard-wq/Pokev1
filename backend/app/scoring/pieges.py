"""
Les pieges qu'un collectionneur repere au premier coup d'oeil.

POURQUOI CE MODULE EXISTE
-------------------------
Passees dans l'algorithme de notation, des annonces realistes ont donne :

    « … proxy fan art »              2,48 EUR   score 82 — en tete du radar
    « Lot de 50 cartes dont … »      36 EUR     comparee au prix d'UNE carte
    « … PSA 10 »                     6,65 EUR   comparee au prix d'une carte brute

Une contrefacon classee meilleure affaire, un lot juge sur une seule carte,
une carte gradee comparee a une carte nue : trois erreurs qu'aucun
collectionneur ne ferait, et que l'application faisait avec assurance.

CE QUE CHAQUE PIEGE ENTRAINE
----------------------------
Contrefacon : l'annonce est ecartee. Ce n'est jamais une affaire, et le
radar n'a pas a la montrer.

Lot, carte gradee : l'annonce reste visible — un lot peut contenir la carte
qu'on cherche, une carte gradee peut interesser — mais SANS marge. Le prix
d'une carte brute a l'unite ne dit rien de leur valeur, et une marge
calculee dessus serait inventee.

LES MOTS RETENUS
----------------
Seulement des termes sans ambiguite dans une annonce de cartes. Un faux
positif sur la contrefacon ecarte une vraie carte en silence : la liste est
donc courte, et chaque mot a ete choisi pour ne pas apparaitre dans une
annonce honnete. « booster » n'y est pas, par exemple : « sortie de
booster » est un gage de bon etat, pas un produit scelle.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


def _normaliser(texte: str) -> str:
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte or "")
                           if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents.lower())


def _motif(termes) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(termes) + r")(?![a-z0-9])")


_CONTREFACON = _motif([
    r"proxy", r"proxies", r"fan ?art", r"fan ?made", r"orica", r"oricas",
    r"carte custom", r"custom card", r"replique", r"reproduction",
    r"copie", r"fake", r"contrefacon", r"non officiel(?:le)?",
    r"unofficial", r"not official",
])

_LOT = _motif([
    r"lots?", r"bundle", r"playset", r"classeur", r"collection complete",
    r"set complet", r"(?:[2-9]|\d{2,}) ?cartes", r"x ?(?:[2-9]|\d{2,}) cartes",
])

# Une note de gradation suit le nom de la societe : « PSA 10 », « BGS 9.5 ».
# « PSA » seul n'est pas retenu — « prete pour PSA » decrit une carte brute.
# PCA est la societe de gradation francaise.
_GRADEE = _motif([
    r"(?:psa|bgs|cgc|pca|sgc|beckett) ?\d+(?:[.,]5)?", r"gradee?", r"gradees?",
    r"graded", r"slab", r"slabbed",
])


@dataclass
class Pieges:
    contrefacon: Optional[str] = None
    lot: Optional[str] = None
    gradee: Optional[str] = None

    @property
    def non_comparable(self) -> Optional[str]:
        """La raison pour laquelle le prix d'une carte brute ne s'applique pas."""
        if self.gradee:
            return (f"Carte gradée (« {self.gradee} ») : le prix d'une carte brute "
                    "ne dit rien de sa valeur.")
        if self.lot:
            return (f"Lot (« {self.lot} ») : le prix d'une seule carte ne dit rien "
                    "de la valeur de l'ensemble.")
        return None


def detecter(*textes: Optional[str]) -> Pieges:
    """Les pieges presents dans le titre et la description d'une annonce."""
    texte = _normaliser(" ".join(t for t in textes if t))
    trouve = lambda motif: (motif.search(texte).group(0) if motif.search(texte) else None)
    return Pieges(contrefacon=trouve(_CONTREFACON), lot=trouve(_LOT),
                  gradee=trouve(_GRADEE))
