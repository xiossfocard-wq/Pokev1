"""
Analyse heuristique du texte d'une annonce (titre + description) pour en
tirer un signal de qualité complémentaire à l'analyse visuelle.

Important : ceci reste un signal *indicatif*, basé sur la présence de
mots-clés. Ce n'est pas une compréhension sémantique fine (une description
qui dit "aucune rayure" contient quand même le mot "rayure" — on essaie de
gérer les négations simples les plus fréquentes, mais ça reste imparfait,
d'où le poids modéré donné à ce signal dans le score final).
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
NEGATION_PATTERNS = ["sans ", "pas de ", "aucun ", "aucune ", "no "]

_NEGATION_WINDOW = 12  # nb de caractères avant le mot-clé où chercher une négation


@dataclass
class TextQualityResult:
    score: float  # 0-100, 50 = neutre (pas assez d'info)
    matched_positive: List[str] = field(default_factory=list)
    matched_negative: List[str] = field(default_factory=list)
    negated_negative: List[str] = field(default_factory=list)  # ex: "sans rayure"

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "matched_positive": self.matched_positive,
            "matched_negative": self.matched_negative,
            "negated_negative": self.negated_negative,
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

    for kw in POSITIVE_KEYWORDS:
        if re.search(re.escape(kw), full_text):
            matched_positive.append(kw)

    for kw in NEGATIVE_KEYWORDS:
        for m in re.finditer(re.escape(kw), full_text):
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

    return TextQualityResult(
        score=score,
        matched_positive=matched_positive,
        matched_negative=matched_negative,
        negated_negative=negated_negative,
    )
