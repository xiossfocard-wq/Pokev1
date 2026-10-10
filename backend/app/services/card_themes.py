"""
Regroupement des cartes par THEME, pour construire une collection.

Pourquoi ce module existe
-------------------------
Demande du 10/10/2026 : « les cartes qui se ressemblent dans certains
secteurs pour faire une collection, donne-moi les cartes par theme ».

Un collectionneur ne cherche pas « une carte a 40 EUR », il cherche « la
ligne de Dracaufeu », « toutes les evolutions d'Evoli », « les Illustration
Rare de ce bloc ». L'index de prix (MarketCardPrice) ne connait que le nom,
le code, la serie et la rarete : ce module en deduit des regroupements
exploitables comme filtres.

Deux familles de themes, qui repondent a deux besoins differents :

- les themes de SUJET (quel Pokemon est dessus) : Pikachu, la ligne de
  Dracaufeu, les evolutions d'Evoli, les legendaires... c'est ce qui fait
  une collection thematique ;
- les themes de TYPE DE CARTE (comment elle est imprimee) : Illustration
  Rare, Full Art, Gold, les mecaniques ex/V/VMAX... c'est ce qui fait un
  budget et une difficulte.

Les deux se cumulent : une carte peut etre a la fois « ligne de Dracaufeu »
et « Illustration Rare ».

Limites assumees
----------------
C'est une heuristique sur le NOM de la carte, pas une base de donnees
Pokemon exhaustive. Les noms francais sont prioritaires (ZebraDex publie en
francais) avec les noms anglais en alias, parce que les deux circulent chez
les vendeurs. Un faux negatif n'enleve rien a la carte : elle reste
trouvable par la recherche libre et par les autres filtres. Mieux vaut un
theme qui ne rate presque rien de ce qu'il annonce qu'un theme large et
approximatif.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

# --- normalisation -------------------------------------------------------


def _sans_accents(texte: str) -> str:
    """« Évoli » et « Evoli » doivent tomber dans le meme theme : les
    vendeurs comme les sources ecrivent les deux."""
    decompose = unicodedata.normalize("NFD", texte or "")
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn").lower()


# --- definition d'un theme -----------------------------------------------


@dataclass(frozen=True)
class Theme:
    slug: str
    label: str
    description: str
    famille: str                      # "sujet" | "type"
    noms: tuple = ()                  # noms de Pokemon (mot entier, sans accents)
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
# normalise par _sans_accents.

_LIGNE_DRACAUFEU = ("salameche", "charmander", "reptincel", "charmeleon",
                    "dracaufeu", "charizard")
_LIGNE_TORTANK = ("carapuce", "squirtle", "carabaffe", "wartortle",
                  "tortank", "blastoise")
_LIGNE_FLORIZARRE = ("bulbizarre", "bulbasaur", "herbizarre", "ivysaur",
                     "florizarre", "venusaur")

_EVOLUTIONS_EVOLI = ("evoli", "eevee", "aquali", "vaporeon", "voltali",
                     "jolteon", "pyroli", "flareon", "noctali", "umbreon",
                     "mentali", "espeon", "phyllali", "leafeon", "givrali",
                     "glaceon", "nymphali", "sylveon")

_OISEAUX_LEGENDAIRES = ("artikodin", "articuno", "electhor", "zapdos",
                        "sulfura", "moltres")

_LEGENDAIRES = _OISEAUX_LEGENDAIRES + (
    "mewtwo", "lugia", "ho-oh", "hooh", "entei", "raikou", "suicune",
    "celebi", "groudon", "kyogre", "rayquaza", "regice", "regirock",
    "registeel", "latios", "latias", "jirachi", "deoxys", "dialga",
    "palkia", "giratina", "arceus", "darkrai", "cresselia", "reshiram",
    "zekrom", "kyurem", "xerneas", "yveltal", "zygarde", "solgaleo",
    "lunala", "necrozma", "zacian", "zamazenta", "ethernatos", "eternatus",
    "koraidon", "miraidon", "terapagos",
)

_DRAGONS = ("minidraco", "dratini", "draco", "dragonair", "dracolosse",
            "dragonite", "rayquaza", "latios", "latias", "drattak",
            "salamence", "carchacrok", "garchomp", "reshiram", "zekrom",
            "kyurem", "dialga", "palkia", "giratina", "koraidon", "miraidon")

_SPECTRES = ("fantominus", "gastly", "spectrum", "haunter", "ectoplasma",
             "gengar", "osselait", "cubone", "mimiqui", "mimikyu",
             "sepiatop", "spiritomb", "lugulabre", "chandelure")

_CHOUCHOUS = ("pikachu", "raichu", "pichu", "ronflex", "snorlax",
              "leviator", "gyarados", "lucario", "gardevoir", "greninja",
              "amphinobi", "mewtwo", "mew", "magicarpe", "magikarp")

THEMES_SUJET: tuple = (
    Theme(
        slug="pikachu",
        label="Pikachu & sa famille",
        description="Pichu, Pikachu, Raichu — la mascotte, et la carte la plus declinee de tout le jeu.",
        famille="sujet",
        noms=("pikachu", "raichu", "pichu"),
    ),
    Theme(
        slug="ligne-dracaufeu",
        label="Ligne de Dracaufeu",
        description="Salameche, Reptincel, Dracaufeu — la ligne la plus recherchee du jeu, et la plus chere.",
        famille="sujet",
        noms=_LIGNE_DRACAUFEU,
    ),
    Theme(
        slug="evolutions-evoli",
        label="Évoli et ses évolutions",
        description="Évoli et les huit evolutions : une collection complete et bornee, ideale a viser.",
        famille="sujet",
        noms=_EVOLUTIONS_EVOLI,
    ),
    Theme(
        slug="starters-kanto",
        label="Starters de Kanto",
        description="Les trois lignes de depart de la premiere generation, Dracaufeu compris.",
        famille="sujet",
        noms=_LIGNE_DRACAUFEU + _LIGNE_TORTANK + _LIGNE_FLORIZARRE,
    ),
    Theme(
        slug="oiseaux-legendaires",
        label="Oiseaux légendaires",
        description="Artikodin, Électhor, Sulfura — un trio, donc une collection qui se termine.",
        famille="sujet",
        noms=_OISEAUX_LEGENDAIRES,
    ),
    Theme(
        slug="legendaires",
        label="Légendaires",
        description="Les legendaires et fabuleux, toutes generations confondues.",
        famille="sujet",
        noms=_LEGENDAIRES,
    ),
    Theme(
        slug="dragons",
        label="Dragons",
        description="Les dragons, de Minidraco a Miraidon.",
        famille="sujet",
        noms=_DRAGONS,
    ),
    Theme(
        slug="spectres",
        label="Spectres",
        description="Les Pokemon fantomes, un secteur tres suivi cote illustrations.",
        famille="sujet",
        noms=_SPECTRES,
    ),
    Theme(
        slug="chouchous",
        label="Chouchous du public",
        description="Les Pokemon qui reviennent systematiquement en tete des sondages de la communaute.",
        famille="sujet",
        noms=_CHOUCHOUS,
    ),
)


# --- themes de TYPE DE CARTE ---------------------------------------------
# Testes sur le nom ET sur le champ rarity, parce que selon la serie
# l'information est tantot dans l'un, tantot dans l'autre.

THEMES_TYPE: tuple = (
    Theme(
        slug="illustration-rare",
        label="Illustration Rare",
        description="Les cartes a illustration pleine, le coeur du marche actuel.",
        famille="type",
        motifs=(r"\billustration\s+rare\b",),
        rarete_motifs=(r"illustration\s+rare",),
    ),
    Theme(
        slug="secret-rare",
        label="Secret / Special Illustration Rare",
        description="Le haut du panier moderne : numerotation au-dela du set.",
        famille="type",
        motifs=(r"\b(?:secret|special)\s+(?:illustration\s+)?rare\b", r"\bsir\b"),
        rarete_motifs=(r"(?:secret|special)\s+(?:illustration\s+)?rare",),
    ),
    Theme(
        slug="full-art",
        label="Full Art",
        description="Illustration sur toute la carte, sans cadre.",
        famille="type",
        motifs=(r"\bfull\s*art\b",),
        rarete_motifs=(r"full\s*art",),
    ),
    Theme(
        slug="gold-rainbow",
        label="Gold & Rainbow",
        description="Les finitions doree et arc-en-ciel, tres visibles en vitrine.",
        famille="type",
        motifs=(r"\bgold\b", r"\brainbow\b", r"\bdoree?\b"),
        rarete_motifs=(r"\bgold\b|\brainbow\b|hyper\s*rare",),
    ),
    Theme(
        slug="mecanique-ex",
        label="Cartes ex / EX",
        description="La mecanique ex, celle des series recentes.",
        famille="type",
        motifs=(r"\bex\b",),
    ),
    Theme(
        slug="mecanique-v",
        label="Cartes V / VMAX / VSTAR",
        description="Les mecaniques de l'ere Epee & Bouclier.",
        famille="type",
        motifs=(r"\bv\b", r"\bvmax\b", r"\bvstar\b"),
    ),
    Theme(
        slug="mecanique-gx",
        label="Cartes GX",
        description="La mecanique GX, ere Soleil & Lune.",
        famille="type",
        motifs=(r"\bgx\b",),
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

    Une carte appartient a autant de themes qu'elle en satisfait : « Évoli
    Illustration Rare » est a la fois dans « evolutions-evoli » et dans
    « illustration-rare ». C'est voulu — ce sont deux facons distinctes de
    chercher la meme carte.
    """
    nom = _sans_accents(display_name)
    rarete = _sans_accents(rarity or "")
    return [t.slug for t in TOUS_LES_THEMES if t.correspond(nom, rarete)]


# Les slugs sont stockes encadres de virgules (",pikachu,dragons,") pour que
# le filtre SQL `LIKE '%,pikachu,%'` soit EXACT. Sans les virgules de bord,
# chercher "ex" ramenerait aussi "mecanique-ex" et inversement. C'est
# volontairement un champ texte plutot qu'une table de jointure : portable
# entre SQLite et Postgres, et aucune migration a ecrire pour ce volume.
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
