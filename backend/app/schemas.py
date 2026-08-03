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
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


class SettingsUpdate(BaseModel):
    deal_score_threshold: Optional[float] = None
    margin_weight: Optional[float] = None
    quality_weight: Optional[float] = None
    seller_weight: Optional[float] = None
    check_interval_minutes: Optional[int] = None


class SettingsOut(BaseModel):
    deal_score_threshold: float
    margin_weight: float
    quality_weight: float
    seller_weight: float
    check_interval_minutes: int
