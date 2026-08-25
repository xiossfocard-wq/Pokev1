"""
Détection best-effort « cette annonce est-elle probablement une carte NON
française ? » à partir d'un texte libre (titre d'annonce, description...).

Principe (inchangé) : on suppose une annonce française SAUF indice
contraire. Sur Vinted.fr, la majorité des vendeurs ne précisent pas la
langue quand la carte est française — c'est l'implicite. Exiger un mot
« français » explicite exclurait donc à tort la majorité des annonces
réellement françaises.

Ce qui a changé le 25/08/2026
-----------------------------
La version précédente ne repérait qu'une déclaration explicite de langue
(« japonaise », « english »...) ou un alphabet non latin. Sur 500 annonces
réelles de la prod, elle laissait passer une grande partie des annonces
étrangères, car les vendeurs ne déclarent pas leur langue — ils écrivent
simplement dans leur langue :

- une trentaine d'annonces « Pokémon Karte <nom> Einzelkarte Sammelkarte »
  (allemand) ;
- une dizaine d'annonces italiennes (« Carta Pokemon », « promozionale »,
  « evoluzioni prismatiche ») ;
- des annonces néerlandaises (« graad 9.5 », « kaart ») ;
- et surtout des cartes anglaises reconnaissables au seul nom du Pokémon :
  « Charizard », « Gengar », « Psyduck », « Snorlax »... Une carte
  française s'appelle Dracaufeu, Ectoplasma, Psykokwak, Ronflex.

D'où trois familles de signaux, combinées par un petit score plutôt que
par un veto au premier mot croisé (un veto sur un mot ambigu comme « card »
rejetterait des annonces françaises tout à fait valables).

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
    "ja": ["japonaise", "japonais", "japan", "jap.", "jap ", "jp version",
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
           "spedizione", "condizioni", "gradazione", "cercasi", "evoluzioni",
           "ascesa", "gravita", "folgoranti", "ossidrica", "scintille",
           "prismatiche", "eroica", "contrappeso", "raro", "nuova",
           # Articles contractes : souvent le SEUL indice quand le nom du
           # Pokemon s'ecrit pareil dans les deux langues ("Mewtwo EX del
           # Team Rocket", "Pikachu Ex del set mega dream"). Verifie sur les
           # 500 annonces reelles : 6 titres concernes, tous italiens.
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
    "near mint", "mint condition", "trick or trade", "booster box",
    "sealed", "shipping", "brand new", "condition", "graded", "card lot",
    "single card", "very rare", "pack fresh", "please", "worldwide",
    # Vocabulaire de collectionneur anglophone. Chacun pris isolement est
    # employe par des vendeurs francais ("Base Set" comme nom de serie,
    # "Unlimited" comme edition) : c'est bien pour ca qu'ils sont FAIBLES et
    # qu'il en faut deux. Ajoutes apres avoir vu "Pikachu 58/102 Original
    # Base Set Unlimited Pokemon Card - Near Mint" arriver en tete des
    # resultats de recherche le 25/08/2026.
    "base set", "unlimited", "shadowless", "trading card", "pokemon card",
    "holo rare", "first edition", "original",
]

# ---------------------------------------------------------------------------
# 3. Noms de Pokémon dont la version française DIFFÈRE
# ---------------------------------------------------------------------------
# C'est le signal décisif pour les cartes anglaises qui ne déclarent rien.
# Liste volontairement PARTIELLE et conservatrice : n'y figurent que des
# noms dont je suis certain que le nom français est différent. Un nom
# identique dans les deux langues (Pikachu, Mewtwo, Lucario, Rayquaza,
# Gardevoir...) n'a rien à y faire — il ne prouverait rien.
#
# Facile à compléter : ajouter une ligne "anglais": "français".
_ENGLISH_ONLY_POKEMON = {
    # Starters et évolutions les plus vendus
    "bulbasaur": "Bulbizarre", "ivysaur": "Herbizarre", "venusaur": "Florizarre",
    "charmander": "Salamèche", "charmeleon": "Reptincel", "charizard": "Dracaufeu",
    "squirtle": "Carapuce", "wartortle": "Carabaffe", "blastoise": "Tortank",
    "chikorita": "Germignon", "cyndaquil": "Héricendre", "totodile": "Kaiminus",
    "treecko": "Arcko", "torchic": "Poussifeu", "blaziken": "Braségali",
    "mudkip": "Gobou", "turtwig": "Tortipouss", "chimchar": "Ouisticram",
    "piplup": "Tiplouf", "rowlet": "Brindibou", "litten": "Flamiaou",
    "popplio": "Otaquin", "grookey": "Ouistempo", "scorbunny": "Flambino",
    "sobble": "Larméléon", "sprigatito": "Poussacha", "delphox": "Goupelin",
    "greninja": "Amphinobi", "serperior": "Majaspic",
    # Gen 1 populaires
    "caterpie": "Chenipan", "butterfree": "Papilusion", "weedle": "Aspicot",
    "beedrill": "Dardargnan", "pidgey": "Roucool", "pidgeotto": "Roucoups",
    "pidgeot": "Roucarnage", "raticate": "Rattatac", "sandshrew": "Sabelette",
    "clefairy": "Mélofée", "clefable": "Mélodelfe", "vulpix": "Goupix",
    "ninetales": "Feunard", "jigglypuff": "Rondoudou", "wigglytuff": "Grodoudou",
    "zubat": "Nosferapti", "golbat": "Nosferalto", "oddish": "Mystherbe",
    "gloom": "Ortide", "vileplume": "Rafflesia", "venonat": "Mimitoss",
    "venomoth": "Aéromite", "diglett": "Taupiqueur", "dugtrio": "Triopikeur",
    "meowth": "Miaouss", "psyduck": "Psykokwak", "golduck": "Akwakwak",
    "mankey": "Férosinge", "primeape": "Colossinge", "growlithe": "Caninos",
    "arcanine": "Arcanin", "poliwag": "Ptitard", "machop": "Machoc",
    "machoke": "Machopeur", "machamp": "Mackogneur", "bellsprout": "Chétiflor",
    "geodude": "Racaillou", "graveler": "Gravalanch", "rapidash": "Galopa",
    "slowpoke": "Ramoloss", "slowbro": "Flagadoss", "farfetch": "Canarticho",
    "seel": "Otaria", "dewgong": "Lamantine", "grimer": "Tadmorv",
    "muk": "Grotadmorv", "shellder": "Kokiyas", "cloyster": "Crustabri",
    "gastly": "Fantominus", "haunter": "Spectrum", "gengar": "Ectoplasma",
    "drowzee": "Soporifik", "hypno": "Hypnomade", "voltorb": "Voltorbe",
    "exeggcute": "Noeunoeuf", "exeggutor": "Noadkoko", "cubone": "Osselait",
    "marowak": "Ossatueur", "hitmonlee": "Kicklee", "hitmonchan": "Tygnon",
    "lickitung": "Excelangue", "koffing": "Smogo", "weezing": "Smogogo",
    "rhyhorn": "Rhinocorne", "rhydon": "Rhinoféros", "chansey": "Leveinard",
    "tangela": "Saquedeneu", "kangaskhan": "Kangourex", "horsea": "Hypotrempe",
    "seadra": "Hypocéan", "goldeen": "Poissirène", "seaking": "Poissoroy",
    "staryu": "Stari", "starmie": "Staross", "scyther": "Insécateur",
    "jynx": "Lippoutou", "electabuzz": "Élektek", "pinsir": "Scarabrute",
    "magikarp": "Magicarpe", "gyarados": "Léviator", "lapras": "Lokhlass",
    "ditto": "Métamorph", "eevee": "Évoli", "vaporeon": "Aquali",
    "jolteon": "Voltali", "flareon": "Pyroli", "omanyte": "Amonita",
    "aerodactyl": "Ptéra", "snorlax": "Ronflex", "articuno": "Artikodin",
    "zapdos": "Électhor", "moltres": "Sulfura", "dratini": "Minidraco",
    "dragonair": "Draco", "dragonite": "Dracolosse",
    # Évolitions et modernes très recherchés
    "umbreon": "Noctali", "espeon": "Mentali", "leafeon": "Phyllali",
    "glaceon": "Givrali", "sylveon": "Nymphali", "mimikyu": "Mimiqui",
    "toxtricity": "Salarsen", "munchlax": "Goinfrex", "sudowoodo": "Simularbre",
    "wobbuffet": "Qulbutoké", "joltik": "Statitik", "gothita": "Scrutella",
    "salamence": "Drattak", "lurantis": "Floramantis", "garchomp": "Carchacrok",
}


def _compile_words(words) -> re.Pattern:
    """Motif qui n'accepte que des mots entiers, accents déjà retirés."""
    escaped = [re.escape(_strip_accents(w).lower()) for w in words]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(escaped) + r")(?![a-z0-9])")


_EXPLICIT_PATTERNS = {
    lang: _compile_words(words) for lang, words in _EXPLICIT_LANGUAGE.items()
}
_STRONG_PATTERNS = {
    lang: _compile_words(words) for lang, words in _STRONG_FOREIGN_MARKERS.items()
}
_WEAK_ENGLISH_PATTERN = _compile_words(_WEAK_ENGLISH_MARKERS)
_ENGLISH_POKEMON_PATTERN = _compile_words(_ENGLISH_ONLY_POKEMON.keys())

# Mots qui affirment le caractère français de la carte. Leur présence
# désarme les signaux faibles ET les noms anglais : un vendeur qui écrit
# « Dracaufeu carte française » alors que le titre contient « Charizard »
# vend bien la version française.
_FRENCH_ASSERTIONS = _compile_words([
    "francaise", "francais", "vf", "version francaise", "edition francaise",
    "carte fr", "en francais",
])

# Contrepoids indispensable au signal « nom anglais » : beaucoup de
# vendeurs francais ecrivent les DEUX noms pour etre trouves dans les
# recherches (« Dracaufeu Charizard Gold Metal 4/102 », « Ectoplasma ...
# Gengar »). Si un nom francais de Pokemon est present, le vendeur ecrit
# en francais — le nom anglais ne prouve plus rien.
_FRENCH_POKEMON_PATTERN = _compile_words(set(_ENGLISH_ONLY_POKEMON.values()))

# Sigles de langue que les vendeurs collent en fin de titre : "Pikachu Ex
# 044/193 JAP", "Vmax 046/184 S8B JPN", "Eevee 9.5 ITA". Repere en verifiant
# le dashboard en vrai le 25/08/2026 : la version precedente ne connaissait
# que "jp" et "kr", si bien que "JAP" et "JPN" — de loin les plus frequents —
# passaient au travers.
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
    french_name = _FRENCH_POKEMON_PATTERN.search(text)
    french_asserted = bool(_FRENCH_ASSERTIONS.search(text)) or bool(french_name)

    for lang, pattern in _EXPLICIT_PATTERNS.items():
        found = pattern.search(text)
        if found:
            return LanguageVerdict(False, lang, "high",
                                   [f"langue annoncee explicitement : « {found.group(0)} »"])

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

    english_names = _ENGLISH_POKEMON_PATTERN.findall(text)
    if english_names and not french_asserted:
        nom = english_names[0]
        return LanguageVerdict(
            False, "en", "high",
            [f"nom de Pokemon anglais « {nom} » (en francais : "
             f"{_ENGLISH_ONLY_POKEMON.get(nom, '?')})"],
        )

    weak = set(_WEAK_ENGLISH_PATTERN.findall(text))
    if len(weak) >= 2 and not french_asserted:
        mots = ", ".join(f"« {m} »" for m in sorted(weak)[:3])
        return LanguageVerdict(False, "en", "medium",
                               [f"plusieurs expressions anglaises : {mots}"])

    return LanguageVerdict(True, None, "low" if not french_asserted else "high",
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
