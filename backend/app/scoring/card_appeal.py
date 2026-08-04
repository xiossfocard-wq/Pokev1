"""
Détection heuristique (mots-clés du titre/description) de trois signaux
d'attrait pour un collectionneur, indépendants de l'état physique :
- la RARETÉ moderne (Illustration Rare, Secret/Special Illustration Rare...)
- le caractère VINTAGE (sets WOTC 1999-2003 : Base Set, Jungle, Fossil...)
- la POPULARITÉ du Pokémon représenté (Pikachu, Mewtwo, Dracaufeu...)

Recherche faite le 04/08/2026 pour établir ces listes (terminologie standard
de l'industrie, cohérente entre Cardmarket/TCGplayer/eBay/communauté FR) :
- Échelle de rareté moderne (du plus commun au plus recherché) : Rare <
  Double Rare < Ultra Rare (UR) < Illustration Rare (IR) < Special/Secret
  Illustration Rare (SIR) < Hyper Rare. Une carte SIR/IR se reconnaît
  presque toujours par ces mots explicites dans le titre (les vendeurs
  savent que ça vend, donc ils le précisent).
- "Vintage" au sens collection Pokémon FR désigne généralement les sets de
  l'ère Wizards of the Coast (1999-2003) : Set de Base, Jungle, Fossile,
  Team Rocket, Gym, Neo Genesis/Découverte/Révélation/Destinée.

Ce n'est PAS une base de données de cartes exhaustive — juste un signal
supplémentaire ajouté au score final (voir pipeline.py). Un faux négatif
(carte réellement rare mais titre imprécis) n'empêche pas l'annonce d'être
remontée, juste de bénéficier du bonus.
"""
import re

# Du plus recherché au moins recherché — le score reflète cet ordre.
_RARITY_TIER_SCORES = [
    (r"\bsecret\s+illustration\s+rare\b|\bspecial\s+illustration\s+rare\b|\bsir\b", "Special/Secret Illustration Rare", 30),
    (r"\bhyper\s+rare\b", "Hyper Rare", 26),
    (r"\billustration\s+rare\b|\bir\b(?!\w)", "Illustration Rare", 22),
    (r"\bsecret\s+rare\b|\bsr\b(?!\w)", "Secret Rare", 20),
    (r"\bultra\s+rare\b|\bur\b(?!\w)", "Ultra Rare", 14),
    (r"\bdouble\s+rare\b", "Double Rare", 8),
    (r"\bfull\s+art\b", "Full Art", 6),
    (r"\bgold\b.{0,15}\bcard\b|\brainbow\b", "Gold/Rainbow", 18),
]

_VINTAGE_KEYWORDS = [
    "set de base", "base set", "jungle", "fossile", "fossil",
    "team rocket", "gym heroes", "gym challenge", "gym défi", "gym conquete",
    "neo genesis", "neo découverte", "neo decouverte", "neo révélation",
    "neo revelation", "neo destinée", "neo destinee",
    "wizards of the coast", "1ère édition", "1ere edition", "first edition",
    "1999", "2000", "2001", "2002", "shadowless",
]

# Pokémon régulièrement cités comme favoris de la communauté FR (starters
# iconiques, légendaires les plus recherchés, et Pikachu/Mewtwo qui reviennent
# systématiquement en tête des sondages communautaires) — liste volontairement
# courte et non-exhaustive, à ajuster si besoin plutôt qu'une prétention
# d'exhaustivité.
_POPULAR_POKEMON = [
    "pikachu", "mewtwo", "mew", "dracaufeu", "charizard", "evoli", "eevee",
    "lugia", "rayquaza", "ronflex", "snorlax", "leviator", "gyarados",
    "salameche", "charmander", "bulbizarre", "bulbasaur", "carapuce",
    "squirtle", "florizarre", "venusaur", "tortank", "blastoise",
    "umbreon", "sylveon", "gardevoir", "lucario", "greninja",
]

_POPULAR_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(p)}\b" for p in _POPULAR_POKEMON), re.IGNORECASE
)
_VINTAGE_PATTERN = re.compile(
    "|".join(re.escape(k) for k in _VINTAGE_KEYWORDS), re.IGNORECASE
)
_RARITY_PATTERNS = [(re.compile(pat, re.IGNORECASE), label, score) for pat, label, score in _RARITY_TIER_SCORES]


def detect_card_appeal(title: str, description: str = "") -> dict:
    """
    Retourne un bonus 0-30 à ajouter au deal_score (voir pipeline.py), plus
    le détail de ce qui a été détecté pour affichage dans le dashboard.
    """
    text = f"{title or ''} {description or ''}"

    rarity_label = None
    rarity_bonus = 0
    for pattern, label, score in _RARITY_PATTERNS:
        if pattern.search(text):
            rarity_label = label
            rarity_bonus = score
            break  # la première correspondance = la plus rare de la liste

    is_vintage = bool(_VINTAGE_PATTERN.search(text))
    popular_match = _POPULAR_PATTERN.search(text)
    is_popular = bool(popular_match)

    bonus = rarity_bonus
    if is_vintage:
        bonus += 12
    if is_popular:
        bonus += 6
    bonus = min(bonus, 30)  # plafonné pour ne pas écraser marge/qualité dans le score final

    return {
        "appeal_bonus": bonus,
        "rarity_tier": rarity_label,
        "is_vintage": is_vintage,
        "is_popular_pokemon": is_popular,
        "popular_pokemon_matched": popular_match.group(0).lower() if popular_match else None,
    }
