"""Détection best-effort "annonce probablement NON française" (voir titre)."""
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
    combined = " ".join(t for t in texts if t)
    if not combined:
        return False
    return bool(_KEYWORD_PATTERN.search(combined))
