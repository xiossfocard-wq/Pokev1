"""
Regroupement des cartes ONE PIECE par THEME, pour construire une collection.

Pourquoi ce module existe
-------------------------
Un collectionneur ne cherche pas « une carte a 40 EUR », il cherche
« l'equipage du Chapeau de Paille », « toutes les Secret Rare de ce bloc »,
« les cartes de Law ». L'index de prix (MarketCardPrice) ne connait que le
nom, le code, la serie et la rarete : ce module en deduit des regroupements
exploitables comme filtres.

Deux familles de themes, qui repondent a deux besoins differents :

- les themes de SUJET (qui est sur la carte) : equipages, Marine,
  Grands Corsaires, Armee Revolutionnaire, Pires Generations... c'est ce qui
  fait une collection thematique, et c'est aussi la facon dont un joueur
  pense son deck ;
- les themes de TYPE (comment la carte est imprimee) : Secret Rare,
  Super Rare, Leader, alternative/parallele, Manga Rare... c'est ce qui fait
  un budget et une difficulte.

Les deux se cumulent : une carte peut etre a la fois « Chapeau de Paille »
et « Secret Rare ».

Ce qui n'est PAS deduit ici
---------------------------
La COULEUR (rouge, vert, bleu, violet, noir, jaune) et le TYPE DE CARTE
(Leader, Personnage, Evenement, Stage) sont deux axes majeurs du jeu, mais
ils ne se lisent pas dans le nom d'une carte : il faut que la source les
publie. Tant qu'aucune colonne ne les porte, les inventer a partir du nom
donnerait un filtre faux, ce qui est pire qu'un filtre absent. Seul le
Leader est reconnu, et uniquement quand la rarete le dit explicitement.

Limites assumees
----------------
C'est une heuristique sur le NOM de la carte, pas une base de donnees One
Piece exhaustive. Les graphies francaises et anglaises circulent toutes
deux chez les vendeurs (Zoro/Zorro, Usopp/Pipo, Barbe Blanche/Whitebeard),
donc les alias sont prevus. Un faux negatif n'enleve rien a la carte : elle
reste trouvable par la recherche libre et par les autres filtres. Mieux
vaut un theme qui ne rate presque rien de ce qu'il annonce qu'un theme
large et approximatif.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List, Optional

# --- normalisation -------------------------------------------------------


def _sans_accents(texte: str) -> str:
    """« Portgas D. Ace » et « Portgás D. Ace » doivent tomber dans le meme
    theme : les vendeurs comme les sources ecrivent les deux."""
    decompose = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn").lower()


def cle_de_recherche(display_name: str, card_code: Optional[str] = None) -> str:
    """Cle de recherche normalisee : minuscules, sans accents, espaces
    uniformes, nom et code reunis.

    Elle existe parce que chercher directement sur le nom affiche ne marche
    pas, pour deux raisons cumulees :

    - `lower()` de SQLite ne traite que l'ASCII : « Portgás » y reste
      « Portgás », alors que Python en fait « portgás ». Taper le nom exact,
      accent compris, ne rendait donc rien en developpement ;
    - personne ne tape les accents ni la ponctuation exacte. « portgas d
      ace » ne correspond ni au `name_slug` (avec des tirets) ni au nom
      affiche — y compris sous Postgres, ou `lower()` gere pourtant les
      accents.

    Normaliser des DEUX cotes, a l'ecriture et dans la requete, rend la
    recherche insensible a la casse ET aux accents, de facon identique sous
    SQLite et sous Postgres.
    """
    base = _sans_accents(f"{display_name or ''} {card_code or ''}")
    return " ".join(base.split())


# --- definition d'un theme -----------------------------------------------


@dataclass(frozen=True)
class Theme:
    slug: str
    label: str
    description: str
    famille: str                      # "sujet" | "type"
    noms: tuple = ()                  # noms de personnage (mot entier, sans accents)
    motifs: tuple = ()                # expressions regulieres brutes, deja sans accents
    rarete_motifs: tuple = ()         # teste contre le champ `rarity`

    def correspond(self, nom_normalise: str, rarete_normalisee: str) -> bool:
        for nom in self.noms:
            if re.search(rf"\b{re.escape(nom)}\b", nom_normalise):
                return True
        for motif in self.motifs:
            if re.search(motif, nom_normalise):
                return True
        for motif in self.rarete_motifs:
            if rarete_normalisee and re.search(motif, rarete_normalisee):
                return True
        return False


# --- themes de SUJET -----------------------------------------------------
# Les noms sont ecrits SANS ACCENTS : ils sont compares a du texte deja
# normalise par _sans_accents. Les variantes de traduction francaise les
# plus repandues sont incluses en alias (Zorro, Pipo, Baggy...).

_CHAPEAU_DE_PAILLE = (
    "luffy", "monkey d. luffy", "zoro", "zorro", "roronoa",
    "nami", "usopp", "pipo", "sanji", "chopper", "tony tony chopper",
    "robin", "nico robin", "franky", "brook", "jinbe", "jinbei",
)

_HEART = ("law", "trafalgar", "bepo", "shachi", "penguin", "jean bart")

_KID = ("kid", "eustass", "killer", "heat", "wire")

_ROUX = ("shanks", "beckman", "benn beckman", "yasopp", "lucky roux", "uta")

_BETES = (
    "kaido", "king", "queen", "jack", "ulti", "page one", "who's-who",
    "whos-who", "black maria", "sasaki", "yamato", "babanuki",
)

_BIG_MOM = (
    "linlin", "charlotte", "katakuri", "smoothie", "cracker", "perospero",
    "oven", "daifuku", "pudding", "brulee",
)

_BARBE_BLANCHE = (
    "newgate", "barbe blanche", "whitebeard", "marco", "ace", "portgas",
    "jozu", "vista", "izo", "thatch",
)

_BARBE_NOIRE = (
    "teach", "barbe noire", "blackbeard", "lafitte", "van augur",
    "burgess", "doc q", "shiryu", "catarina devon",
)

_MARINE = (
    "garp", "sengoku", "akainu", "sakazuki", "aokiji", "kuzan", "kizaru",
    "borsalino", "fujitora", "issho", "ryokugyu", "smoker", "tashigi",
    "coby", "koby", "helmeppo", "momonga", "hina", "tsuru", "bogard",
)

_CORSAIRES = (
    "mihawk", "dracule", "doflamingo", "crocodile", "hancock", "boa",
    "moria", "gecko moria", "kuma", "bartholomew", "buggy", "baggy",
    "weevil", "jinbe", "jinbei",
)

_REVOLUTIONNAIRES = (
    "dragon", "monkey d. dragon", "sabo", "ivankov", "koala", "inazuma",
    "belo betty", "karasu", "morley", "lindbergh",
)

_DONQUIXOTE = (
    "doflamingo", "trebol", "diamante", "pica", "vergo", "baby 5",
    "gladius", "lao g", "senor pink", "machvise", "dellinger", "monet",
)

_PIRES_GENERATIONS = (
    "luffy", "zoro", "zorro", "law", "trafalgar", "kid", "eustass",
    "killer", "hawkins", "apoo", "drake", "bonney", "capone", "urouge",
)

THEMES_SUJET: tuple = (
    Theme(
        slug="chapeau-de-paille",
        label="Équipage du Chapeau de Paille",
        description="Luffy et son équipage : la collection la plus suivie, et la plus déclinée du jeu.",
        famille="sujet",
        noms=_CHAPEAU_DE_PAILLE,
    ),
    Theme(
        slug="pires-generations",
        label="Pires Générations",
        description="Les onze supernovas : un groupe fermé, donc une collection qui se termine.",
        famille="sujet",
        noms=_PIRES_GENERATIONS,
    ),
    Theme(
        slug="equipage-heart",
        label="Équipage du Cœur",
        description="Trafalgar Law et les siens.",
        famille="sujet",
        noms=_HEART,
    ),
    Theme(
        slug="equipage-kid",
        label="Équipage de Kid",
        description="Eustass Kid, Killer et leur équipage.",
        famille="sujet",
        noms=_KID,
    ),
    Theme(
        slug="equipage-roux",
        label="Équipage du Roux",
        description="Shanks et son équipage, parmi les cartes les plus recherchées.",
        famille="sujet",
        noms=_ROUX,
    ),
    Theme(
        slug="cent-betes",
        label="Équipage aux Cent Bêtes",
        description="Kaido, les Trois Fléaux et les Tobi Roppo.",
        famille="sujet",
        noms=_BETES,
    ),
    Theme(
        slug="big-mom",
        label="Équipage de Big Mom",
        description="Charlotte Linlin et la famille Charlotte.",
        famille="sujet",
        noms=_BIG_MOM,
    ),
    Theme(
        slug="barbe-blanche",
        label="Équipage de Barbe Blanche",
        description="Edward Newgate, Marco, Ace et les commandants de division.",
        famille="sujet",
        noms=_BARBE_BLANCHE,
    ),
    Theme(
        slug="barbe-noire",
        label="Équipage de Barbe Noire",
        description="Marshall D. Teach et son équipage.",
        famille="sujet",
        noms=_BARBE_NOIRE,
    ),
    Theme(
        slug="marine",
        label="Marine",
        description="Amiraux, vice-amiraux et officiers de la Marine.",
        famille="sujet",
        noms=_MARINE,
    ),
    Theme(
        slug="grands-corsaires",
        label="Grands Corsaires",
        description="Les Sept Grands Corsaires, de Mihawk à Boa Hancock.",
        famille="sujet",
        noms=_CORSAIRES,
    ),
    Theme(
        slug="revolutionnaires",
        label="Armée Révolutionnaire",
        description="Dragon, Sabo et les cadres de l'Armée Révolutionnaire.",
        famille="sujet",
        noms=_REVOLUTIONNAIRES,
    ),
    Theme(
        slug="donquixote",
        label="Famille Donquixote",
        description="Doflamingo et ses officiers.",
        famille="sujet",
        noms=_DONQUIXOTE,
    ),
)


# --- themes de TYPE DE CARTE ---------------------------------------------
# Testes sur le nom ET sur le champ rarity, parce que selon la source
# l'information est tantot dans l'un, tantot dans l'autre. Les sigles du
# jeu (SEC, SR, L, P) sont cherches comme des mots entiers pour ne pas
# mordre sur un nom de personnage.

THEMES_TYPE: tuple = (
    Theme(
        slug="secret-rare",
        label="Secret Rare",
        description="Le haut du panier : numérotation au-delà du set.",
        famille="type",
        motifs=(r"\bsecret\s*rare\b", r"\bsec\b"),
        rarete_motifs=(r"secret\s*rare", r"\bsec\b"),
    ),
    Theme(
        slug="super-rare",
        label="Super Rare",
        description="Le palier au-dessus des Rare, très présent en vitrine.",
        famille="type",
        motifs=(r"\bsuper\s*rare\b",),
        rarete_motifs=(r"super\s*rare", r"\bsr\b"),
    ),
    Theme(
        slug="manga-rare",
        label="Manga Rare",
        description="Illustration en noir et blanc reprenant une planche du manga.",
        famille="type",
        motifs=(r"\bmanga\s*rare\b",),
        rarete_motifs=(r"manga\s*rare",),
    ),
    Theme(
        slug="alternative",
        label="Alternative / Parallèle",
        description="Illustration alternative d'une carte déjà parue : le cœur du marché.",
        famille="type",
        motifs=(r"\balt(?:ernative)?\s*art\b", r"\bparallele\b", r"\bparallel\b", r"\bfull\s*art\b"),
        rarete_motifs=(r"alt(?:ernative)?\s*art", r"parallel", r"full\s*art"),
    ),
    Theme(
        slug="leader",
        label="Cartes Leader",
        description="Les Leaders, point de départ de tout deck.",
        famille="type",
        motifs=(r"\bleader\b",),
        rarete_motifs=(r"\bleader\b", r"^l$"),
    ),
    Theme(
        slug="promo",
        label="Promotionnelles",
        description="Cartes de tournoi, de précommande ou d'événement, hors boosters.",
        famille="type",
        motifs=(r"\bpromo\b", r"\bpromotionnelle?\b"),
        rarete_motifs=(r"\bpromo\b", r"^p$"),
    ),
)


TOUS_LES_THEMES: tuple = THEMES_SUJET + THEMES_TYPE

_PAR_SLUG = {theme.slug: theme for theme in TOUS_LES_THEMES}


def theme_par_slug(slug: str) -> Optional[Theme]:
    return _PAR_SLUG.get((slug or "").strip().lower())


def slugs_connus() -> List[str]:
    return [theme.slug for theme in TOUS_LES_THEMES]


# --- classement ----------------------------------------------------------


def themes_de_la_carte(display_name: str, rarity: Optional[str] = None) -> List[str]:
    """Rend les slugs des themes auxquels une carte appartient.

    Une carte appartient a autant de themes qu'elle en satisfait :
    « Monkey D. Luffy (Secret Rare) » est a la fois dans
    « chapeau-de-paille », « pires-generations » et « secret-rare ». C'est
    voulu — ce sont des facons distinctes de chercher la meme carte.
    """
    nom = _sans_accents(display_name)
    rarete = _sans_accents(rarity or "")
    return [t.slug for t in TOUS_LES_THEMES if t.correspond(nom, rarete)]


# Les slugs sont stockes encadres de virgules (",marine,leader,") pour que
# le filtre SQL `LIKE '%,marine,%'` soit EXACT. Sans les virgules de bord,
# chercher "leader" ramenerait aussi un hypothetique "leader-parallele" et
# inversement. C'est volontairement un champ texte plutot qu'une table de
# jointure : portable entre SQLite et Postgres, et aucune migration a
# ecrire pour ce volume.
def encoder_themes(slugs: Iterable[str]) -> str:
    propres = [s for s in slugs if s]
    if not propres:
        return ","
    return "," + ",".join(propres) + ","


def decoder_themes(encode: Optional[str]) -> List[str]:
    if not encode:
        return []
    return [s for s in encode.split(",") if s]


def motif_like_pour_theme(slug: str) -> str:
    """Motif a passer a SQL `LIKE` pour filtrer sur un theme."""
    return f"%,{slug},%"
