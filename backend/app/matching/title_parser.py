"""
Analyse pure d'un titre d'annonce : extraction du code carte, du numero de
set et des noms de carte candidats.

Volontairement SANS dependance a SQLAlchemy ni au reseau, pour que cette
logique - la plus delicate et la plus susceptible de regresser - reste
testable en isolation (voir tests/test_title_parser.py). Le service
price_index.py se contente d'interroger la base avec ces candidats.
"""
import re
import unicodedata
from typing import List, Optional, Tuple

# "4/102", "232/193", "19/98"...
SET_NUMBER_PATTERN = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")
# Codes carte. Les codes ZebraDex reels observes sont du type "PAF 232"
# (lettres + numero zero-pade a 3 chiffres), mais les vendeurs ecrivent
# parfois un code de bloc contenant deja des chiffres ("EV01-045") : le
# groupe optionnel (?:\d{2})? rattache ces chiffres au prefixe plutot que
# de couper le code en deux (bug detecte par les tests).
CARD_CODE_PATTERN = re.compile(r"\b([A-Z]{2,6}(?:\d{2})?)[\s-]?(\d{1,3})\b")

# Mots frequents dans les titres d'annonces qui ne sont pas des noms de carte.
TITLE_NOISE = {
    "carte", "cartes", "pokemon", "lot", "holo", "rare", "neuve", "neuf",
    "fr", "francaise", "tres", "bon", "etat", "mint", "nm", "psa", "the",
    "de", "du", "des", "la", "le", "les", "un", "une", "et", "avec", "pour",
    "vends", "vend", "prix", "envoi", "protege", "sleeve", "toploader",
}

# Suffixes qui font partie du nom reel d'une carte : gardes dans les paires
# de mots (ex "mew-ex"), jamais utilises seuls.
NAME_SUFFIXES = {"ex", "gx", "v", "vmax", "vstar", "star", "prime", "lv", "x"}


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return normalized.lower()


def extract_card_codes(text: str) -> List[str]:
    """
    Codes carte normalises au format ZebraDex ("PAF 232"). Le numero est
    complete a 3 chiffres car ZebraDex zero-pad ses codes (PAF 005, pas
    PAF 5).
    """
    out = []
    for match in CARD_CODE_PATTERN.finditer((text or "").upper()):
        prefix, number = match.groups()
        candidate = f"{prefix} {number.zfill(3)}"
        if candidate not in out:
            out.append(candidate)
    return out


def extract_set_number(text: str) -> Optional[Tuple[str, str]]:
    """Retourne (numero, total) zero-paddes, ex ("004", "102")."""
    match = SET_NUMBER_PATTERN.search(text or "")
    if not match:
        return None
    number, total = match.groups()
    return number.zfill(3), total.zfill(3)


def extract_name_candidates(text: str) -> List[str]:
    """
    Slugs candidats depuis le titre, ordonnes du plus specifique au moins
    specifique : d'abord les paires de mots consecutifs (pour attraper
    "mew-ex", "dracaufeu-ex"), puis les mots isoles hors bruit.

    Les suffixes type "ex"/"gx" sont exclus comme mot isole (sinon toute
    annonce contenant "ex" matcherait n'importe quelle carte "ex") mais
    conserves dans les paires, car ils font partie du nom reel.
    """
    normalized = normalize(text)
    words = [w for w in re.split(r"[^a-z0-9]+", normalized) if len(w) > 1]

    candidates: List[str] = []
    for i, word in enumerate(words):
        if i + 1 < len(words):
            pair = f"{word}-{words[i + 1]}"
            if pair not in candidates:
                candidates.append(pair)
    for word in words:
        if word in TITLE_NOISE or word in NAME_SUFFIXES or word.isdigit():
            continue
        if word not in candidates:
            candidates.append(word)
    return candidates
