"""
Analyse heuristique du texte d'une annonce (titre + description) pour en
tirer un signal de qualité complémentaire à l'analyse visuelle.

Important : ceci reste un signal *indicatif*, basé sur la présence de
mots-clés. Ce n'est pas une compréhension sémantique fine (une description
qui dit "aucune rayure" contient quand même le mot "rayure" — on essaie de
gérer les négations simples les plus fréquentes, mais ça reste imparfait,
d'où le poids modéré donné à ce signal dans le score final).

Échelle d'état détectée (recherche faite le 04/08/2026) : le marché de la
carte à l'unité (Cardmarket, TCGplayer, eBay, communauté FR) utilise une
échelle standard, du meilleur au pire : NM (Near Mint / quasi neuf) > LP
(Lightly Played / légers défauts) > MP (Moderately Played / état moyen) >
HP (Heavily Played / très usée) > DMG (Damaged / endommagée). C'est
différent du grading professionnel numérique (PSA/BGS/CGC 1-10), qui
s'applique à une carte déjà scellée dans un boîtier certifié — la plupart
des annonces d'occasion sur Vinted/eBay utilisent l'échelle NM/LP/MP/HP,
pas une note PSA.
"""
import re
from dataclasses import dataclass, field
from typing import List


# Mots-clés indiquant un bon état / une carte gradée haut de gamme.
POSITIVE_KEYWORDS = [
    "near mint", "nm", "mint", "psa 10", "psa10", "psa 9", "psa9",
    "comme neuf", "parfait état", "parfait etat", "aucun défaut",
    "aucun defaut", "état impeccable", "etat impeccable", "jamais joué",
    "jamais joue", "sortie de booster", "gem mint", "bgs 9.5", "cgc 9.5",
]

# Mots-clés indiquant un défaut visible / un état dégradé.
NEGATIVE_KEYWORDS = [
    "rayure", "rayures", "scratch", "scratched", "défaut", "defaut",
    "pli", "plié", "plie", "corner", "coin abimé", "coin abîmé",
    "écorné", "ecorne", "joué", "joue", "played", "taché", "tache",
    "usure", "usée", "usee", "whitening", "jauni", "jauni(e)", "abimé",
    "abime", "endommagé", "endommage", "eclat", "éclat", "moisissure",
]

# Négations fréquentes en français qui, précédant un mot-clé négatif de
# près, inversent son sens ("sans rayure", "pas de défaut", ...).
# « jamais » : « jamais joué » est un gage d'état, pas l'aveu d'une carte jouée.
NEGATION_PATTERNS = ["sans ", "pas de ", "aucun ", "aucune ", "no ", "jamais "]

_NEGATION_WINDOW = 12  # nb de caractères avant le mot-clé où chercher une négation

# Échelle d'état standard du marché carte à l'unité, du meilleur au pire —
# voir docstring du module. Ordre de la liste = ordre de priorité de
# détection (si plusieurs correspondent, on garde la meilleure trouvée).
_CONDITION_TIERS = [
    ("NM", ["near mint", "nm", "mint", "quasi neuf", "comme neuf"]),
    ("LP", ["lightly played", "legers defauts", "légers défauts", "lp", "excellent"]),
    ("MP", ["moderately played", "etat moyen", "état moyen", "mp"]),
    ("HP", ["heavily played", "tres usee", "très usée", "hp"]),
    ("DMG", ["damaged", "endommagée", "endommagee", "abimée", "abimee", "dmg"]),
]
_CONDITION_PATTERNS = [
    (tier, re.compile("|".join(rf"\b{re.escape(kw)}\b" for kw in kws), re.IGNORECASE))
    for tier, kws in _CONDITION_TIERS
]

# « MP » est aussi le « message privé » de toutes les annonces Vinted
# (« contactez-moi en MP », « envoyez un mp ») : lu comme « Moderately
# Played », il decotait la carte de 30 % sans raison. Precede de en / par /
# un / mon, c'est un message.
_MP_MESSAGE = re.compile(r"\b(?:en|par|un|mon|ton|votre|en\s+priv[ée])\s+mp\b", re.IGNORECASE)


def _mot(kw: str) -> re.Pattern:
    """Le mot-cle comme mot ENTIER. Cherche en sous-chaine, « tache »
    trouvait « détachée », « pli » « remplie », « joue » « jouet »."""
    return re.compile(rf"(?<!\w){re.escape(kw)}(?!\w)")


_POSITIFS = [(kw, _mot(kw)) for kw in POSITIVE_KEYWORDS]
_NEGATIFS = [(kw, _mot(kw)) for kw in NEGATIVE_KEYWORDS]


@dataclass
class TextQualityResult:
    score: float  # 0-100, 50 = neutre (pas assez d'info)
    matched_positive: List[str] = field(default_factory=list)
    matched_negative: List[str] = field(default_factory=list)
    negated_negative: List[str] = field(default_factory=list)  # ex: "sans rayure"
    condition_tier: str = None  # "NM" | "LP" | "MP" | "HP" | "DMG" | None si indétecté

    @property
    def informatif(self) -> bool:
        """Le texte dit-il quelque chose de l'etat ? Sinon le score reste a
        50 — une absence d'information, pas une carte « moyenne »."""
        return bool(self.matched_positive or self.matched_negative
                    or self.negated_negative or self.condition_tier)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "matched_positive": self.matched_positive,
            "matched_negative": self.matched_negative,
            "negated_negative": self.negated_negative,
            "condition_tier": self.condition_tier,
        }


def _is_negated(text_lower: str, match_start: int) -> bool:
    window_start = max(0, match_start - _NEGATION_WINDOW)
    window = text_lower[window_start:match_start]
    return any(neg in window for neg in NEGATION_PATTERNS)


def analyze_text_quality(title: str, description: str) -> TextQualityResult:
    """
    Score heuristique 0-100 basé sur les mots-clés trouvés dans le titre +
    la description. 50 = neutre (aucun mot-clé pertinent trouvé).
    """
    full_text = f"{title or ''} {description or ''}".lower()

    matched_positive: List[str] = []
    matched_negative: List[str] = []
    negated_negative: List[str] = []

    for kw, motif in _POSITIFS:
        # « mint » dans « near mint » : un seul constat, pas deux points.
        if motif.search(full_text) and not any(kw in deja for deja in matched_positive):
            matched_positive.append(kw)

    for kw, motif in _NEGATIFS:
        for m in motif.finditer(full_text):
            if _is_negated(full_text, m.start()):
                negated_negative.append(kw)
            else:
                matched_negative.append(kw)
            break  # une seule occurrence comptée par mot-clé

    score = 50.0
    score += min(len(matched_positive), 4) * 8.0    # jusqu'à +32
    score -= min(len(matched_negative), 4) * 10.0   # jusqu'à -40
    score += min(len(negated_negative), 3) * 3.0    # léger bonus si défauts explicitement niés
    score = max(0.0, min(100.0, score))

    condition_tier = None
    texte_sans_messages = _MP_MESSAGE.sub(" ", full_text)
    for tier, pattern in _CONDITION_PATTERNS:
        if pattern.search(texte_sans_messages):
            condition_tier = tier
            break

    return TextQualityResult(
        score=score,
        matched_positive=matched_positive,
        matched_negative=matched_negative,
        negated_negative=negated_negative,
        condition_tier=condition_tier,
    )
