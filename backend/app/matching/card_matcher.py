"""
Résolution (best-effort) d'une annonce vers un nom de carte / slug
Cardmarket exploitable pour aller chercher un prix de référence.

⚠️ C'est le maillon le plus fragile du pipeline : les titres d'annonces
Vinted/eBay sont écrits librement par des particuliers (fautes, argot,
abréviations : "drattak", "dracofeu", "holo", "1ère ed", etc.). Cette
première version reste volontairement simple (extraction de mots-clés +
slugification) plutôt que de prétendre à une reconnaissance fiable.

Pistes d'amélioration concrètes pour la suite (à faire une fois le reste
du pipeline validé en conditions réelles) :
- Intégrer une API de cartes One Piece pour résoudre plus
  finement nom + set + numéro à partir du texte libre.
- Maintenir un dictionnaire de correspondance manuel pour les cartes que
  tu suis le plus souvent (rapide à faire, très fiable).
- Ne calculer un prix de référence que si un code de carte (ex "OP01-120")
  est détecté dans le titre, pour éviter les faux positifs.

⚠️ ÉTAT RÉEL : dans l'application, seul `slugify_card_name` est appelé
(par collectors/cardmarket_prices.py). `guess_card_from_title` n'a plus
d'appelant : le rapprochement annonce -> carte passe désormais par
services/price_index.py, qui s'appuie sur matching/title_parser.py et qui
est nettement plus fin. La fonction est conservée parce qu'elle reste
correcte et testée, pas parce qu'elle tourne.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Mots à ignorer lors de l'extraction du nom de carte probable.
#
# Le nom du JEU doit en faire partie : presque toutes les annonces le citent,
# et sans lui le nom deviné devenait « One-Piece-Monkey » au lieu de
# « Monkey-D-Luffy ». Le vocabulaire de rareté propre au jeu (SEC, SR,
# alternative, manga rare…) y figure pour la même raison.
NOISE_WORDS = {
    # vocabulaire d'annonce, commun à tous les jeux
    "carte", "cartes", "fr", "français", "francaise", "francais",
    "vf", "tbe", "be", "occasion", "vente", "vend", "lot", "lots", "vintage",
    "rare", "holo", "reverse", "shiny", "edition", "édition", "1ere", "1ère",
    "neuve", "neuf", "mint", "nm", "the", "card", "trading", "tcg", "booster",
    # nom du jeu
    "one", "piece", "onepiece",
    # raretés et traitements One Piece
    # « leader » n'y figure PAS : contrairement a « SEC » ou « SR », qui
    # qualifient le tirage, il designe une carte differente — un Leader et
    # un Personnage du meme nom ont des prix sans rapport.
    "sec", "sr", "ur", "alt", "alternative", "parallele", "parallèle",
    "parallel", "manga", "promo", "full", "art",
}

SET_NUMBER_PATTERN = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")

# Code de carte One Piece : « OP01-120 », « ST01-001 », « EB01-012 »,
# « P-001 ». C'est LE signal de confiance du jeu. Tant que la confiance ne
# dependait que du format « X/Y », qui n'existe pas ici, toute annonce One
# Piece ressortait en confiance basse, quelle que soit sa precision.
CARD_CODE_PATTERN = re.compile(r"\b([A-Z]{1,4}\d{0,2})[\s\-_.]*(\d{1,4})\b", re.I)


@dataclass
class CardMatch:
    card_name_guess: str
    set_number: Optional[str]   # format "X/Y", inutilise par One Piece
    card_slug: str              # slug best-effort pour l'URL Cardmarket
    confidence: str             # "low" | "medium"
    card_code: Optional[str] = None   # ex "OP01-120", normalise


def slugify_card_name(text: str) -> str:
    """
    Slug normalisé (ex "Monkey D. Luffy") partagé entre le matching
    annonce -> carte et le parsing du price guide Cardmarket en masse
    (collectors/cardmarket_prices.py), pour que les deux se rejoignent sur
    la même clé.
    """
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-")
    return "-".join(part.capitalize() for part in normalized.split("-") if part)


def guess_card_from_title(title: str) -> Optional[CardMatch]:
    if not title:
        return None

    set_match = SET_NUMBER_PATTERN.search(title)
    set_number = set_match.group(0).replace(" ", "") if set_match else None

    code_match = CARD_CODE_PATTERN.search(title)
    card_code = (
        f"{code_match.group(1).upper()}-{code_match.group(2).zfill(3)}"
        if code_match else None
    )

    # On retire le numéro de set, le code carte et la ponctuation, puis les
    # mots de bruit, pour ne garder que ce qui ressemble à un nom de carte.
    cleaned = SET_NUMBER_PATTERN.sub("", title)
    cleaned = CARD_CODE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    words = [w for w in cleaned.split() if w.lower() not in NOISE_WORDS]

    if not words:
        return None

    # Heuristique simple : les premiers mots "significatifs" sont
    # généralement le nom du personnage, suivi le cas échéant du type de
    # carte. Quatre et non trois : les noms à initiale en consomment déjà
    # trois ("Monkey", "D", "Luffy"), et il n'en resterait aucun pour
    # distinguer un Leader d'un Personnage. Même plafond que
    # title_parser.MAX_NAME_WORDS, pour que les deux modules coupent au
    # même endroit.
    candidate_words = words[:4]
    card_name_guess = " ".join(candidate_words)
    card_slug = slugify_card_name(card_name_guess)

    confidence = "medium" if (card_code or set_number) else "low"

    return CardMatch(
        card_name_guess=card_name_guess,
        set_number=set_number,
        card_code=card_code,
        card_slug=card_slug,
        confidence=confidence,
    )
