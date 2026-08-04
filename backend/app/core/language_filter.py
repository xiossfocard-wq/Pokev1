"""
Détection best-effort "cette annonce est-elle probablement une carte NON
française ?" à partir d'un texte libre (titre d'annonce, condition, etc.).

Approche volontairement en LISTE NOIRE plutôt qu'en liste blanche : on
suppose qu'une annonce est française sauf si elle indique explicitement le
contraire. C'est un choix assumé, pas un oubli — sur une marketplace
française (Vinted.fr), la grande majorité des vendeurs ne précisent pas la
langue quand la carte est française (c'est l'implicite), et ne la précisent
que pour signaler une carte étrangère (JAP, EN, etc.). Une approche en
liste blanche (exiger un mot "français"/"FR" explicite) exclurait donc à
tort la majorité des annonces réellement françaises.

Volontairement PAS de sigles courts (EN, DE, IT, ES, US...) dans la liste :
ce sont des mots français ordinaires ("EN très bon état", etc.) et leur
utiliser comme signal produirait énormément de faux positifs. On se limite
à des mots/expressions longs et non ambigus.

Complément prévu (voir app/vision/quality_vision.py) : quand l'analyse
photo par IA est activée, elle lit aussi la langue réellement imprimée sur
la carte — un filet de rattrapage plus fiable que le texte de l'annonce
pour les cas où le vendeur n'a rien précisé mais où la carte n'est en fait
pas française.
"""
import re

_NON_FRENCH_KEYWORDS = [
    "anglaise", "anglais", "english",
    "japonaise", "japonais", "japan", "jap.", "jap ",
    "allemande", "allemand", "german", "deutsch",
    "italienne", "italien", "italian",
    "espagnole", "espagnol", "spanish",
    "coréenne", "coreenne", "coréen", "coreen", "korean",
    "chinoise", "chinois", "chinese",
    "version us", "version anglaise", "import us", "import usa", "us version",
    "néerlandaise", "neerlandaise", "dutch",
    "portugaise", "portugais", "portuguese",
]

_KEYWORD_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in _NON_FRENCH_KEYWORDS), re.IGNORECASE
)


def looks_non_french(*texts) -> bool:
    """
    True si un des textes fournis (titre, condition, description...)
    contient un indice clair de langue non-française. Ignore les valeurs
    None/vides. Ne garantit PAS l'inverse : un retour False ne prouve pas
    que la carte est française, juste qu'aucun signal contraire n'a été vu.
    """
    combined = " ".join(t for t in texts if t)
    if not combined:
        return False
    return bool(_KEYWORD_PATTERN.search(combined))
