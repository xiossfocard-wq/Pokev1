from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    url: str
    price: float
    shipping_price: float
    currency: str
    photo_urls: list
    seller_username: Optional[str] = None
    seller_reliability_score: Optional[float] = None
    reference_price: Optional[float] = None
    reference_price_source: Optional[str] = None
    margin_net: Optional[float] = None
    margin_ratio: Optional[float] = None
    quality_text_score: Optional[float] = None
    quality_vision_score: Optional[float] = None
    quality_vision_detail: Optional[dict] = None
    deal_score: Optional[float] = None
    rarity_tier: Optional[str] = None
    is_vintage: bool = False
    is_popular_pokemon: bool = False
    condition_tier: Optional[str] = None
    price_low_eur: Optional[float] = None
    price_high_eur: Optional[float] = None
    price_match_confidence: Optional[str] = None
    price_detail: Optional[dict] = None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    # Corrections saisies a la main depuis le dashboard
    manual_status: Optional[str] = None
    manual_reference_price: Optional[float] = None
    manual_reviewed_at: Optional[datetime] = None


class ListingCorrection(BaseModel):
    """
    Correction saisie par l'utilisateur sur une annonce.

    - "wrong_card" : la carte identifiee n'est pas la bonne. On efface le
      prix et on ne retente plus rien automatiquement.
    - "set_price"  : l'utilisateur donne lui-meme le prix du marche.
    - "hide"       : masquer cette annonce du dashboard.
    - "reset"      : oublier la correction, revenir a l'automatique.
    """
    action: str
    price: Optional[float] = None


class SettingsUpdate(BaseModel):
    deal_score_threshold: Optional[float] = None
    margin_weight: Optional[float] = None
    quality_weight: Optional[float] = None
    seller_weight: Optional[float] = None
    check_interval_minutes: Optional[int] = None
    min_listing_price: Optional[float] = None


class SettingsOut(BaseModel):
    deal_score_threshold: float
    margin_weight: float
    quality_weight: float
    seller_weight: float
    check_interval_minutes: int
    min_listing_price: float
