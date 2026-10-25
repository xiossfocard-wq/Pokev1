"""
Détection best-effort « cette annonce est-elle probablement une carte NON
française ? » à partir d'un texte libre (titre d'annonce, description...).

Principe : on suppose une annonce française SAUF indice contraire. Sur
Vinted.fr, la majorité des vendeurs ne précisent pas la langue quand la
carte est française — c'est l'implicite. Exiger un mot « français »
explicite exclurait donc à tort la majorité des annonces réellement
françaises.

Trois familles de signaux, combinées par un petit score plutôt que par un
veto au premier mot croisé (un veto sur un mot ambigu comme « card »
rejetterait des annonces françaises tout à fait valables) :

1. déclaration explicite de langue, ou sigle collé en fin de titre
   (« japonaise », « ENG », « JAP ») — le signal le plus sûr ;
2. mots qui n'existent QUE dans une langue étrangère (« Karte »,
   « carta », « kaart ») ;
3. vocabulaire de collectionneur anglophone, faible pris isolément : il en
   faut deux, et aucun indice français à côté.

⚠️ CE FILTRE EST PLUS FAIBLE SUR ONE PIECE QUE SUR UN JEU TRADUIT
-----------------------------------------------------------------
Le signal le plus décisif, sur un jeu dont les noms sont traduits, est le
nom lui-même : une carte dont le nom imprimé n'existe que dans une langue
ne peut pas venir d'une autre édition. Ce signal n'existe
PAS ici. One Piece ne traduit pas ses personnages : Monkey D. Luffy,
Roronoa Zoro, Nami s'écrivent pareil en français, en anglais et en
italien. Un titre « Monkey D. Luffy OP01-120 » ne dit rien de sa langue.

Conséquence assumée : une carte anglaise dont le vendeur ne déclare rien
et n'emploie aucun vocabulaire anglophone PASSERA. On ne peut pas la
distinguer d'une française sur le texte seul — il faudrait lire la photo.
C'est pour ça que la liste de vocabulaire anglais (3) est plus fournie ici
qu'elle ne le serait sur un jeu traduit : elle doit porter seule une
charge qu'elle partageait ailleurs.

Les cartes japonaises, elles, restent bien attrapées : alphabet non latin,
sigles « JAP »/« JPN », ou déclaration explicite.

Aucune clé API n'est nécessaire : tout est lexical et tourne en local.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()


# ---------------------------------------------------------------------------
# 1. Déclarations explicites de langue (signal le plus sûr)
# ---------------------------------------------------------------------------

_EXPLICIT_LANGUAGE = {
    "en": ["anglaise", "anglais", "english", "version us", "version anglaise",
           "import us", "import usa", "us version", "eng version",
           "english version"],
    "ja": ["japonaise", "japonais", "japan", "jap", "jp version",
           "ver. jap", "ver jap"],
    "de": ["allemande", "allemand", "german", "deutsch"],
    "it": ["italienne", "italien", "italian", "italiana", "italiano"],
    "es": ["espagnole", "espagnol", "spanish", "espanol"],
    "ko": ["coreenne", "coreen", "korean"],
    "zh": ["chinoise", "chinois", "chinese"],
    "nl": ["neerlandaise", "dutch", "nederlands", "nederlandse"],
    "pt": ["portugaise", "portugais", "portuguese"],
}

# ---------------------------------------------------------------------------
# 2. Mots qui n'existent QUE dans une langue étrangère
# ---------------------------------------------------------------------------
# Critère d'entrée dans cette liste : le mot ne doit jamais apparaître
# naturellement dans une annonce française. « carta » (it/es) oui,
# « carte » (fr) non. « karte » (de) oui, « kaart » (nl) oui.

_STRONG_FOREIGN_MARKERS = {
    "de": ["karte", "karten", "einzelkarte", "einzelkarten", "sammelkarte",
           "sammelkarten", "sammlung", "zustand", "neuwertig", "geprueft",
           "seltene", "glurak", "unbespielt", "originalverpackt", "kaufen",
           "versand", "sehr gut"],
    "it": ["carta", "carte da collezione", "collezione", "promozionale",
           "spedizione", "condizioni", "gradazione", "cercasi", "raro",
           "nuova", "rarissima", "originale", "perfetta",
           # Articles contractes : souvent le SEUL indice utilisable, les
           # noms de personnages s'ecrivant pareil dans les deux langues
           # (« Rufy del Mare », « Zoro della Marina »). Ils portent donc
           # plus de poids ici que sur un jeu dont les noms sont traduits.
           "del", "della", "dello", "dei", "delle",
           "ottime", "ottimo", "nuovo", "nuove"],
    "nl": ["kaart", "kaarten", "verzamelkaart", "graad", "zeldzaam",
           "nieuwstaat"],
    "es": ["brillante", "envio", "coleccion", "raras", "nueva"],
    "pt": ["colecao", "raro brilhante"],
}

# Mots anglais que des vendeurs FRANÇAIS emploient couramment (« near
# mint », « holo », « full art »...). Un seul ne prouve rien ; on n'agit
# qu'à partir de deux, et seulement en l'absence de marqueur français.
_WEAK_ENGLISH_MARKERS = [
    "near mint", "mint condition", "booster box", "sealed", "shipping",
    "brand new", "condition", "graded", "ungraded", "card lot", "lot of",
    "single card", "very rare", "pack fresh", "please", "worldwide",
    "trading card", "holo rare", "first edition", "original", "playset",
    "pre owned", "preowned", "free shipping", "fast shipping", "bundle",
    "collectible", "collectable", "slabbed",
    # Termes de jeu ecrits a l'anglaise. La frontiere de mot evite les faux
    # positifs sur leurs equivalents francais : « parallel » n'attrape pas
    # « parallele », « alternate » n'attrape pas « alternative ».
    "alternate art", "alternate", "parallel", "leader card", "character card",
    "starter deck", "booster pack",
]

def _compile_words(words) -> re.Pattern:
    """Motif qui n'accepte que des mots entiers, accents déjà retirés."""
    escaped = [re.escape(_strip_accents(w).lower()) for w in words]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(escaped) + r")(?![a-z0-9])")


def _compile_prefixes(words) -> re.Pattern:
    """
    Comme `_compile_words`, mais SANS frontière à droite : la terminaison
    du mot est libre.

    Indispensable pour les déclarations de langue, dont la racine se
    décline : « japan » doit attraper « japanese » et « japanisch »,
    « italian » doit attraper « italiano ». Sans ça, un titre comme
    « Dialga G LV79 galactics conquest 065096 japanese » passait sans être
    inquiété — régression introduite le 25/08/2026 en remplaçant la
    recherche par sous-chaîne d'origine par une recherche par mot entier.
    """
    escaped = [re.escape(_strip_accents(w).lower()) for w in words]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(escaped) + r")")


_EXPLICIT_PATTERNS = {
    lang: _compile_prefixes(words) for lang, words in _EXPLICIT_LANGUAGE.items()
}
_STRONG_PATTERNS = {
    lang: _compile_words(words) for lang, words in _STRONG_FOREIGN_MARKERS.items()
}
_WEAK_ENGLISH_PATTERN = _compile_words(_WEAK_ENGLISH_MARKERS)

# Mots qui affirment le caractère français de la carte. Leur présence
# désarme même les marqueurs forts : un vendeur qui écrit « carte
# française » dans un titre par ailleurs bilingue vend bien la française.
_FRENCH_ASSERTIONS = _compile_words([
    "francaise", "francais", "vf", "version francaise", "edition francaise",
    "carte fr", "en francais",
])

# Vocabulaire de vendeur FRANÇAIS, plus faible que ci-dessus. Il ne désarme
# que les signaux anglais faibles, jamais un marqueur étranger fort : un
# « état » isolé dans un titre allemand ne fait pas de la carte une
# française, alors qu'il rend improbable qu'un titre truffé de vocabulaire
# anglophone vienne d'un vendeur anglophone.
#
# Ce contrepoids remplace celui qu'on avait sur un jeu aux noms traduits,
# où la présence du nom français suffisait à prouver que le vendeur écrit
# en français. One Piece ne traduisant pas ses personnages, il fallait le
# reconstruire sur du vocabulaire — d'où cette liste.
#
# Critère d'entrée : le mot ne doit exister dans AUCUNE des autres langues
# surveillées. « état » oui ; « carte » non, c'est aussi le pluriel italien
# de « carta ».
_FRENCH_VOCABULARY = _compile_words([
    "etat", "neuve", "envoi", "soigne", "livraison", "pochette",
    "jamais joue", "lot de", "frais de port", "vendue", "achat",
    "parfait", "sous blister", "protege carte", "collectionneur",
    "classeur", "tres bon", "debarras", "cadeau",
])

# Sigles de langue que les vendeurs collent en fin de titre : "Luffy
# OP01-120 JAP", "Zoro OP01-025 JPN Mint", "Nami 9.5 ITA". Repere en
# verifiant le dashboard en vrai le 25/08/2026 : la version precedente ne
# connaissait que "jp" et "kr", si bien que "JAP" et "JPN" — de loin les plus
# frequents — passaient au travers.
#
# N'y figurent QUE des sigles qui ne sont pas aussi des mots francais. "EN",
# "DE", "IT", "US" en sont volontairement absents : "carte EN très bon état",
# "lot DE 10 cartes" declencheraient le filtre a tort.
_LANGUAGE_CODES = {
    "jp": "ja", "jpn": "ja", "jap": "ja",
    "kr": "ko", "kor": "ko",
    "eng": "en",
    "ita": "it",
    "esp": "es",
    "ger": "de", "deu": "de",
    "chn": "zh",
    "ned": "nl",
}

_SHORT_TOKEN_PATTERN = re.compile(
    r"(?<![a-z0-9])(" + "|".join(sorted(_LANGUAGE_CODES, key=len, reverse=True)) + r")(?![a-z0-9])"
)

# Sigles lus en MAJUSCULES, sur le texte d'ORIGINE.
#
# « EN » et « US » ne peuvent pas entrer dans _LANGUAGE_CODES, qui travaille
# sur le texte passe en minuscules : « en » est l'un des mots les plus
# frequents du francais (« carte en tres bon etat »). Resultat, deux titres
# releves sur Vinted le 25/10/2026 passaient pour francais :
#
#     « Carte one piece Katakuri op03-099 alt art EN psa 10 »
#     « Buggy SP Wanted US »
#
# C'est la CASSE qui les distingue : un vendeur qui ecrit « Katakuri EN »
# etiquette une langue, pas une preposition. Deux garde-fous : un titre ecrit
# tout en capitales ne dit rien de sa casse, et « EN BON ETAT » reste la
# preposition meme en capitales.
_SIGLES_MAJUSCULES = re.compile(r"(?<![A-Za-z0-9])(EN|ENG|US|USA|UK)(?![A-Za-z0-9])")
_SUITE_DE_PREPOSITION = re.compile(
    r"\s+(?:BON|BONNE|TRES|TRÈS|PARFAIT|PARFAITE|EXCELLENT|EXCELLENTE|ETAT|ÉTAT|"
    r"VENTE|FRANCAIS|FRANÇAIS|STOCK|LOT|PLUS|NEUF|NEUVE|FR)\b",
    re.IGNORECASE,
)
# Un titre « crie » quand la plupart de ses MOTS ORDINAIRES sont en
# capitales : sa casse n'est alors plus un indice. On ne compte pas les codes
# de carte ni les raretes (« ST01 », « OP03-099 », « SEC », « SP ») : ils sont
# en capitales par nature, et sur un titre court comme « Zoro ST01-001 EN »
# ils faisaient passer le titre pour crie.
_MOT_ORDINAIRE = re.compile(r"(?<![\w-])[^\W\d_]{4,}(?![\w-])")
_PART_MAJUSCULES_MAX = 0.6


def _sigle_en_majuscules(texte: str) -> Optional[str]:
    """Le premier sigle de langue ecrit en capitales dans un titre en casse
    normale, ou None."""
    mots = _MOT_ORDINAIRE.findall(texte)
    if mots and sum(m.isupper() for m in mots) / len(mots) > _PART_MAJUSCULES_MAX:
        return None
    for trouve in _SIGLES_MAJUSCULES.finditer(texte):
        sigle = trouve.group(1)
        if sigle == "EN" and _SUITE_DE_PREPOSITION.match(texte, trouve.end()):
            continue
        return sigle
    return None


_NON_LATIN_SCRIPT_PATTERN = re.compile(
    "["
    "぀-ヿ"
    "一-鿿"
    "가-힣"
    "]"
)


@dataclass
class LanguageVerdict:
    """Verdict détaillé, pour pouvoir expliquer une exclusion (voir
    l'endpoint /api/admin/test-language) plutôt que de faire disparaître
    une annonce sans dire pourquoi."""
    is_french: bool
    language: Optional[str] = None      # "de", "it", "en", "nl"... ou None
    confidence: str = "low"             # "high" | "medium" | "low"
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_french": self.is_french,
            "language": self.language,
            "confidence": self.confidence,
            "reasons": self.reasons,
        }


def detect_language(*texts) -> LanguageVerdict:
    combined_raw = " ".join(t for t in texts if t)
    if not combined_raw.strip():
        return LanguageVerdict(is_french=True, confidence="low",
                               reasons=["texte vide"])

    if _NON_LATIN_SCRIPT_PATTERN.search(combined_raw):
        return LanguageVerdict(False, "ja/ko/zh", "high",
                               ["alphabet non latin dans le titre"])

    text = _strip_accents(combined_raw).lower()
    french_asserted = bool(_FRENCH_ASSERTIONS.search(text))
    french_vocabulary = french_asserted or bool(_FRENCH_VOCABULARY.search(text))

    for lang, pattern in _EXPLICIT_PATTERNS.items():
        found = pattern.search(text)
        if found:
            return LanguageVerdict(False, lang, "high",
                                   [f"langue annoncee explicitement : « {found.group(0)} »"])

    # Sur chaque texte separement : un titre en casse normale et une
    # description tout en capitales ne se jugent pas a la meme aune.
    for texte in texts:
        majuscule = _sigle_en_majuscules(texte or "")
        if majuscule:
            return LanguageVerdict(False, "en", "high",
                                   [f"sigle de langue « {majuscule} » ecrit en capitales"])

    sigle = _SHORT_TOKEN_PATTERN.search(text)
    if sigle:
        code = sigle.group(1)
        return LanguageVerdict(False, _LANGUAGE_CODES[code], "high",
                               [f"sigle de langue « {code.upper()} » dans le titre"])

    for lang, pattern in _STRONG_PATTERNS.items():
        found = pattern.findall(text)
        if found:
            mots = ", ".join(f"« {m} »" for m in sorted(set(found))[:3])
            if french_asserted:
                return LanguageVerdict(
                    True, None, "low",
                    [f"mots {lang} ({mots}) mais l'annonce comporte aussi "
                     f"un indice francais net"],
                )
            return LanguageVerdict(False, lang, "high",
                                   [f"mot(s) exclusivement {lang} : {mots}"])

    # Sur un jeu aux noms traduits, un nom anglais trancherait ici. One Piece
    # n'en offre pas : « Monkey D. Luffy » s'ecrit pareil dans toutes les
    # langues. Le vocabulaire anglophone porte donc seul la detection des
    # cartes anglaises non declarees, et il en faut toujours deux : un seul
    # ("original", "condition") sort de la plume de vendeurs francais.
    weak = set(_WEAK_ENGLISH_PATTERN.findall(text))
    if len(weak) >= 2 and not french_vocabulary:
        mots = ", ".join(f"« {m} »" for m in sorted(weak)[:3])
        return LanguageVerdict(False, "en", "medium",
                               [f"plusieurs expressions anglaises : {mots}"])

    return LanguageVerdict(True, None, "high" if french_vocabulary else "low",
                           ["aucun indice de langue etrangere"])


def looks_non_french(*texts) -> bool:
    """
    True si un des textes fournis (titre, description...) contient un
    indice clair de langue non française. Ignore les valeurs None/vides.
    Ne garantit PAS l'inverse : une annonce sans aucun indice est traitée
    comme probablement française.
    """
    verdict = detect_language(*texts)
    return not verdict.is_french and verdict.confidence in ("high", "medium")
