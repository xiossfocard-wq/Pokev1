"""
Normalisation de la fiabilité vendeur en un score 0-100, quelle que soit
la source (eBay ou Vinted), pour pouvoir les combiner dans le deal score.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SellerReliabilityResult:
    score: float
    is_estimated: bool  # True si on manque de données (nouveau vendeur, etc.)
    detail: str

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "is_estimated": self.is_estimated,
            "detail": self.detail,
        }


NEUTRAL_SCORE_NEW_SELLER = 45.0  # légèrement en dessous de neutre : prudence


def score_ebay_seller(
    feedback_percentage: Optional[float],
    feedback_score: Optional[int],
) -> SellerReliabilityResult:
    """
    feedback_percentage : ex 99.2 (pourcentage d'évaluations positives)
    feedback_score : nombre total d'évaluations
    """
    if feedback_percentage is None or feedback_score is None:
        return SellerReliabilityResult(
            score=NEUTRAL_SCORE_NEW_SELLER,
            is_estimated=True,
            detail="Données vendeur eBay indisponibles",
        )

    base = max(0.0, min(100.0, feedback_percentage))

    # Un vendeur avec très peu d'évaluations est moins fiable même à 100%,
    # on applique une décote progressive en dessous de 20 évaluations.
    if feedback_score < 5:
        confidence = 0.5
    elif feedback_score < 20:
        confidence = 0.75
    else:
        confidence = 1.0

    score = NEUTRAL_SCORE_NEW_SELLER + (base - NEUTRAL_SCORE_NEW_SELLER) * confidence

    return SellerReliabilityResult(
        score=score,
        is_estimated=confidence < 1.0,
        detail=f"{feedback_percentage}% positif sur {feedback_score} évaluations",
    )


def score_vinted_seller(
    review_count: Optional[int],
    average_rating: Optional[float],  # attendu sur 5
) -> SellerReliabilityResult:
    if review_count is None or average_rating is None or review_count == 0:
        return SellerReliabilityResult(
            score=NEUTRAL_SCORE_NEW_SELLER,
            is_estimated=True,
            detail="Profil Vinted sans avis exploitable",
        )

    base = max(0.0, min(100.0, (average_rating / 5.0) * 100.0))

    if review_count < 5:
        confidence = 0.5
    elif review_count < 20:
        confidence = 0.75
    else:
        confidence = 1.0

    score = NEUTRAL_SCORE_NEW_SELLER + (base - NEUTRAL_SCORE_NEW_SELLER) * confidence

    return SellerReliabilityResult(
        score=score,
        is_estimated=confidence < 1.0,
        detail=f"{average_rating}/5 sur {review_count} avis",
    )
