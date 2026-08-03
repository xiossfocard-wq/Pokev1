import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Integer, String, Text, JSON,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SourcePlatform(str, enum.Enum):
    EBAY = "ebay"
    VINTED = "vinted"


class ListingStatus(str, enum.Enum):
    NEW = "new"                # détectée, pas encore complètement scorée
    SCORED = "scored"          # marge + qualité + score final calculés
    NOTIFIED = "notified"      # notification envoyée (score au-dessus du seuil)
    IGNORED = "ignored"        # ne matche aucune carte connue / prix ref manquant
    REMOVED = "removed"        # annonce disparue lors d'un scan ultérieur


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    source = Column(Enum(SourcePlatform), nullable=False, index=True)
    external_id = Column(String(128), nullable=False, index=True)

    title = Column(String(512), nullable=False)
    description = Column(Text, default="")
    url = Column(String(1024), nullable=False)

    price = Column(Float, nullable=False)
    shipping_price = Column(Float, default=0.0)
    currency = Column(String(8), default="EUR")

    photo_urls = Column(JSON, default=list)

    seller_username = Column(String(256), nullable=True)
    seller_reliability_score = Column(Float, nullable=True)
    seller_reliability_detail = Column(String(512), nullable=True)

    card_name_guess = Column(String(256), nullable=True)  # meilleure estimation du nom de carte

    reference_price = Column(Float, nullable=True)
    reference_price_source = Column(String(64), nullable=True)  # "cardmarket" etc.

    margin_net = Column(Float, nullable=True)
    margin_ratio = Column(Float, nullable=True)

    quality_text_score = Column(Float, nullable=True)
    quality_vision_score = Column(Float, nullable=True)
    quality_vision_detail = Column(JSON, nullable=True)  # explication du modèle vision

    deal_score = Column(Float, nullable=True, index=True)

    status = Column(Enum(ListingStatus), default=ListingStatus.NEW, index=True)

    first_seen_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    scored_at = Column(DateTime, nullable=True)

    notifications = relationship("NotificationSent", back_populates="listing")

    def __repr__(self):
        return f"<Listing {self.source}:{self.external_id} score={self.deal_score}>"


class PriceReference(Base):
    """Cache des prix de référence par carte, pour éviter de retaper
    Cardmarket/ZebraDex à chaque annonce (rafraîchi au plus 1x/jour par carte)."""
    __tablename__ = "price_references"

    id = Column(Integer, primary_key=True)
    card_slug = Column(String(256), nullable=False, index=True, unique=True)
    expansion_slug = Column(String(256), nullable=True)
    trend_price_eur = Column(Float, nullable=True)
    avg_30d_price_eur = Column(Float, nullable=True)
    price_source = Column(String(64), nullable=True)  # "cardmarket" | "zebradex" | "cardmarket+zebradex"
    fetched_at = Column(DateTime, default=datetime.utcnow)


class NotificationSent(Base):
    __tablename__ = "notifications_sent"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    channel = Column(String(32), nullable=False)  # "telegram" | "email"
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_detail = Column(String(512), nullable=True)

    listing = relationship("Listing", back_populates="notifications")


class AppSettings(Base):
    """Réglages modifiables depuis le dashboard (seuil de notif, poids du
    score, etc.), stockés en DB pour ne pas nécessiter de redéploiement."""
    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
