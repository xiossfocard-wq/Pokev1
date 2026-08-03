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
- Intégrer l'API gratuite pokemontcg.io (ou tcgdex.dev) pour résoudre plus
  finement nom + set + numéro à partir du texte libre.
- Maintenir un dictionnaire de correspondance manuel pour les cartes que
  tu suis le plus souvent (rapide à faire, très fiable).
- Ne calculer un prix de référence que si un numéro de set (ex "4/102")
  est détecté dans le titre, pour éviter les faux positifs.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Mots à ignorer lors de l'extraction du nom de carte probable.
NOISE_WORDS = {
    "carte", "cartes", "pokemon", "pokémon", "fr", "français", "francaise",
    "vf", "tbe", "be", "occasion", "vente", "vend", "lot", "lots", "vintage",
    "rare", "holo", "reverse", "shiny", "edition", "1ere", "1ère", "neuve",
    "neuf", "the", "card", "trading",
}

SET_NUMBER_PATTERN = re.compile(r"\b(\d{1,3})\s*/\s*(\d{1,3})\b")


@dataclass
class CardMatch:
    card_name_guess: str
    set_number: Optional[str]   # ex "4/102"
    card_slug: str              # slug best-effort pour l'URL Cardmarket
    confidence: str             # "low" | "medium"


def slugify_card_name(text: str) -> str:
    """
    Slug normalisé (ex "Dracaufeu Vmax") partagé entre le matching
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

    # On retire le numéro de set et la ponctuation, puis les mots de bruit,
    # pour ne garder que ce qui ressemble le plus à un nom de carte.
    cleaned = SET_NUMBER_PATTERN.sub("", title)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned, flags=re.UNICODE)
    words = [w for w in cleaned.split() if w.lower() not in NOISE_WORDS]

    if not words:
        return None

    # Heuristique simple : les 1 à 3 premiers mots "significatifs" sont
    # généralement le nom du Pokémon (+ variante ex/vmax/gx).
    candidate_words = words[:3]
    card_name_guess = " ".join(candidate_words)
    card_slug = slugify_card_name(card_name_guess)

    confidence = "medium" if set_number else "low"

    return CardMatch(
        card_name_guess=card_name_guess,
        set_number=set_number,
        card_slug=card_slug,
        confidence=confidence,
    )
