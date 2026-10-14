"""
Détection heuristique (mots-clés du titre/description) de trois signaux
d'attrait pour un collectionneur ONE PIECE, indépendants de l'état physique :
- la RARETÉ (Manga Rare, Secret Rare, alternative, Super Rare...)
- le caractère PRÉCOCE (OP-01 « Romance Dawn » et les premiers tirages)
- la POPULARITÉ du personnage représenté (Luffy, Zoro, Law, Shanks...)

Échelle de rareté du jeu, du plus commun au plus recherché : C < UC < R <
SR < SEC, avec en plus les traitements qui se superposent à ce barème
(alternative/parallèle, et Manga Rare, qui est le palier le plus convoité
des séries récentes). Un vendeur qui détient une de ces cartes l'écrit
presque toujours dans son titre : ça se vend, donc ça se précise.

« Précoce » désigne ici OP-01 « Romance Dawn » et les tout premiers
produits : ce jeu date de 2022, il n'a pas encore de vintage au sens où
l'entendent les collectionneurs d'autres TCG. Le champ garde son nom
`is_vintage` pour ne pas casser le schéma de base, mais il faut le lire
comme « édition précoce ».

Ce n'est PAS une base de données de cartes exhaustive — juste un signal
supplémentaire ajouté au score final (voir pipeline.py). Un faux négatif
(carte réellement rare mais titre imprécis) n'empêche pas l'annonce d'être
remontée, juste de bénéficier du bonus.
"""
import re

# Du plus recherché au moins recherché — le score reflète cet ordre.
_RARITY_TIER_SCORES = [
    (r"\bmanga\s*rare\b", "Manga Rare", 30),
    (r"\bsecret\s*rare\b|\bsec\b(?!\w)", "Secret Rare", 26),
    (r"\balt(?:ernative)?\s*art\b|\bparall[eè]le?\b|\bparallel\b", "Alternative", 22),
    (r"\bspecial\s*card\b|\bcarte\s*sp[eé]ciale\b", "Special Card", 18),
    (r"\bsuper\s*rare\b|\bsr\b(?!\w)", "Super Rare", 14),
    (r"\bleader\b|\bl\b(?!\w)", "Leader", 10),
    (r"\bpromo\b|\bpromotionnelle?\b", "Promo", 8),
    (r"\brare\b|\br\b(?!\w)", "Rare", 4),
]

_VINTAGE_KEYWORDS = [
    "romance dawn", "op-01", "op01", "op 01",
    "paramount war", "op-02", "op02",
    "1ere edition", "1ère édition", "1st edition", "premiere edition",
    "première édition", "edition limitee", "édition limitée",
    "2022", "japonais 2022",
]

# Personnages qui reviennent systématiquement en tête des ventes et des
# sondages de la communauté One Piece — liste volontairement courte et
# non-exhaustive, à ajuster si besoin plutôt qu'une prétention
# d'exhaustivité. Les graphies françaises anciennes sont incluses.
_PERSONNAGES_PHARES = [
    "luffy", "zoro", "zorro", "law", "trafalgar", "shanks", "mihawk",
    "ace", "portgas", "sabo", "nami", "robin", "sanji", "chopper",
    "yamato", "hancock", "boa", "katakuri", "doflamingo", "kaido",
    "newgate", "barbe blanche", "whitebeard", "teach", "barbe noire",
    "kid", "eustass", "garp", "rayleigh", "roger", "gol d. roger", "uta",
]

_POPULAR_PATTERN = re.compile(
    "|".join(rf"\b{re.escape(p)}\b" for p in _PERSONNAGES_PHARES), re.IGNORECASE
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
        "is_popular_character": is_popular,
        "popular_character_matched": popular_match.group(0).lower() if popular_match else None,
    }
