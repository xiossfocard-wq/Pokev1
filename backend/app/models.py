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
    NEW = "new"                        # détectée, pas encore complètement scorée
    SCORED = "scored"                  # marge + qualité + score final calculés
    NOTIFIED = "notified"              # notification envoyée (score au-dessus du seuil)
    NO_PRICE_MATCH = "no_price_match"  # aucun prix de référence trouvé, mais À AFFICHER
                                        # quand même (comparaison manuelle possible) —
                                        # distinct de IGNORED depuis le 04/08/2026 (avant,
                                        # ce cas utilisait IGNORED par erreur, ce qui la
                                        # faisait disparaître du dashboard aussitôt scorée)
    IGNORED = "ignored"                # exclusion délibérée (ex: langue non française) —
                                        # celle-ci reste masquée du dashboard, à raison
    UNAVAILABLE = "unavailable"        # l'annonce n'existe plus chez le vendeur (vendue ou
                                        # supprimée). Masquée : cliquer dessus menait sur une
                                        # page d'erreur Vinted, signalé par l'utilisateur le
                                        # 25/08/2026
    REMOVED = "removed"                # annonce disparue lors d'un scan ultérieur


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    source = Column(Enum(SourcePlatform, native_enum=False), nullable=False, index=True)
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

    rarity_tier = Column(String(64), nullable=True)      # ex "Illustration Rare"
    is_vintage = Column(Boolean, default=False)
    is_popular_pokemon = Column(Boolean, default=False)
    condition_tier = Column(String(8), nullable=True)     # "NM" | "LP" | "MP" | "HP" | "DMG"

    # Prix de reference detaille (voir services/price_index.py). La
    # fourchette basse/haute est derivee de la volatilite 7 jours de
    # ZebraDex, PAS d'un historique de ventes conclues - a presenter
    # comme telle dans l'UI.
    price_low_eur = Column(Float, nullable=True)
    price_high_eur = Column(Float, nullable=True)
    price_match_confidence = Column(String(16), nullable=True)  # high|medium|low
    price_detail = Column(JSON, nullable=True)

    status = Column(Enum(ListingStatus, native_enum=False), default=ListingStatus.NEW, index=True)

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


class ZebraDexSeriesState(Base):
    """
    Suivi de synchronisation des series ZebraDex (158 series FR au
    04/08/2026, decouvertes automatiquement via /series - aucune config
    manuelle). La sync est PROGRESSIVE : quelques series par cycle plutot
    qu'un gros job bloquant, pour ne pas depasser les limites d'un
    hebergement gratuit ni marteler ZebraDex (1 req / 6s).
    """
    __tablename__ = "zebradex_series"

    id = Column(Integer, primary_key=True)
    series_id = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(256), nullable=False)
    code = Column(String(32), nullable=True)
    bloc = Column(String(128), nullable=True)
    url = Column(String(512), nullable=False)
    last_synced_at = Column(DateTime, nullable=True, index=True)
    card_count = Column(Integer, default=0)
    last_error = Column(String(512), nullable=True)


class MarketCardPrice(Base):
    """
    Index local des prix de reference, une ligne par carte (toutes series
    confondues). Alimente par ZebraDex ; concu pour accueillir d'autres
    sources plus tard (colonne `source`).

    IMPORTANT sur price_low / price_high : ce ne sont PAS des min/max de
    ventes reellement conclues (ZebraDex ne publie pas cette donnee, il
    publie un prix marche + une variation 7 jours). Ce sont des bornes
    derivees de la volatilite recente - a presenter comme telles.
    """
    __tablename__ = "market_card_prices"

    id = Column(Integer, primary_key=True)
    card_code = Column(String(32), nullable=True, index=True)      # "PAF 232"
    name_slug = Column(String(256), nullable=False, index=True)    # "mew-ex"
    display_name = Column(String(256), nullable=False)             # "Mew Ex"
    series_name = Column(String(256), nullable=True, index=True)
    rarity = Column(String(64), nullable=True, index=True)

    price_eur = Column(Float, nullable=False)
    price_low_eur = Column(Float, nullable=True)
    price_high_eur = Column(Float, nullable=True)
    variation_7d_eur = Column(Float, nullable=True)

    source = Column(String(32), default="zebradex")
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)
