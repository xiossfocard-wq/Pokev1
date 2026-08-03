"""
Combine marge + qualité (texte + vision) + fiabilité vendeur en un score
final de "bonne affaire" sur 100.

Les poids sont volontairement externalisés (DealScoreWeights) pour être
ajustables depuis les settings de l'app sans toucher au code, et pour
pouvoir être testés indépendamment.
"""
from dataclasses import dataclass


@dataclass
class DealScoreWeights:
    margin: float = 0.5
    quality: float = 0.3
    seller: float = 0.2

    def normalized(self) -> "DealScoreWeights":
        total = self.margin + self.quality + self.seller
        if total <= 0:
            raise ValueError("La somme des poids doit être positive")
        return DealScoreWeights(
            margin=self.margin / total,
            quality=self.quality / total,
            seller=self.seller / total,
        )


@dataclass
class QualityBlend:
    """Combine le score texte (mots-clés) et le score vision (photos)."""
    text_score: float
    vision_score: float | None  # None si l'analyse vision n'a pas encore tourné
    vision_weight: float = 0.65  # la vision est jugée plus fiable que le texte seul

    def combined(self) -> float:
        if self.vision_score is None:
            return self.text_score
        return (
            self.vision_score * self.vision_weight
            + self.text_score * (1 - self.vision_weight)
        )


def calculate_deal_score(
    margin_score_0_100: float,
    quality_blend: QualityBlend,
    seller_score_0_100: float,
    weights: DealScoreWeights | None = None,
) -> float:
    """
    Retourne un score final 0-100. Toutes les entrées doivent déjà être
    normalisées sur 0-100 (voir margin.normalize_margin_ratio pour la marge).
    """
    for name, value in [
        ("margin_score_0_100", margin_score_0_100),
        ("seller_score_0_100", seller_score_0_100),
    ]:
        if not (0 <= value <= 100):
            raise ValueError(f"{name} doit être compris entre 0 et 100 (reçu {value})")

    w = (weights or DealScoreWeights()).normalized()
    quality_score = quality_blend.combined()

    score = (
        w.margin * margin_score_0_100
        + w.quality * quality_score
        + w.seller * seller_score_0_100
    )
    return max(0.0, min(100.0, score))
