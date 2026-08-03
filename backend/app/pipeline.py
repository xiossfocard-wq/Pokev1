"""
Orchestration d'un cycle complet de vérification : collecte des annonces
(eBay + Vinted), résolution du prix de référence, scoring, persistance en
DB, et notification si le score dépasse le seuil configuré.

Appelé périodiquement par le scheduler (app/scheduler.py), mais reste
appelable manuellement (endpoint /admin/run-check-now) pour débogage.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.collectors.cardmarket_prices import CardmarketPriceClient
from app.collectors.ebay_browse import EbayBrowseClient
from app.collectors.vinted_scraper import VintedScraper, VintedBlockedError
from app.collectors.zebradex_prices import ZebraDexPriceClient
from app.matching.card_matcher import guess_card_from_title
from app.models import Listing, SourcePlatform, ListingStatus, PriceReference, NotificationSent
from app.scoring.margin import calculate_margin, normalize_margin_ratio
from app.scoring.quality_text import analyze_text_quality
from app.scoring.deal_score import calculate_deal_score, QualityBlend
from app.scoring.seller_reliability import score_ebay_seller, score_vinted_seller
from app.vision.quality_vision import analyze_card_photos
from app.notifications.telegram import send_telegram_message, format_deal_alert
from app.notifications.email_notif import send_email_notification, format_deal_alert_html

logger = logging.getLogger(__name__)

PRICE_CACHE_MAX_AGE = timedelta(days=1)

_cardmarket_client = CardmarketPriceClient()
_zebradex_client = ZebraDexPriceClient()
_vinted_scraper = VintedScraper(request_delay_seconds=settings.vinted_request_delay_seconds)

# Cache en mémoire du price guide en masse (voir collectors/cardmarket_prices.py
# > fetch_bulk_price_guide). Chargé une fois par process et rafraîchi au plus
# 1x/jour ; reste vide (et donc simplement ignoré) si
# CARDMARKET_BULK_PRICE_GUIDE_URL n'est pas configuré.
_bulk_price_guide: dict = {}
_bulk_price_guide_loaded_at: Optional[datetime] = None

# Cache équivalent pour ZebraDex (voir collectors/zebradex_prices.py) :
# fusion de toutes les pages série configurées dans ZEBRADEX_SERIES_URLS.
# Vide (et donc ignoré) si non configuré.
_zebradex_prices: dict = {}
_zebradex_prices_loaded_at: Optional[datetime] = None


def _maybe_refresh_bulk_price_guide():
    global _bulk_price_guide, _bulk_price_guide_loaded_at
    if not settings.cardmarket_bulk_price_guide_url:
        return
    if (
        _bulk_price_guide_loaded_at
        and datetime.utcnow() - _bulk_price_guide_loaded_at < PRICE_CACHE_MAX_AGE
    ):
        return
    prices = _cardmarket_client.fetch_bulk_price_guide(settings.cardmarket_bulk_price_guide_url)
    if prices:
        _bulk_price_guide = prices
        _bulk_price_guide_loaded_at = datetime.utcnow()
        logger.info("Cardmarket: price guide en masse rechargé (%d cartes)", len(prices))


def _maybe_refresh_zebradex_cache():
    global _zebradex_prices, _zebradex_prices_loaded_at
    if not settings.zebradex_series_urls:
        return
    if (
        _zebradex_prices_loaded_at
        and datetime.utcnow() - _zebradex_prices_loaded_at < PRICE_CACHE_MAX_AGE
    ):
        return
    merged: dict = {}
    for url in settings.zebradex_series_urls:
        merged.update(_zebradex_client.fetch_series_prices(url))
    if merged:
        _zebradex_prices = merged
        _zebradex_prices_loaded_at = datetime.utcnow()
        logger.info("ZebraDex: %d cartes chargées depuis %d série(s)",
                     len(merged), len(settings.zebradex_series_urls))


def _lookup_cardmarket_price(match) -> Optional[float]:
    """Price guide en masse si dispo, sinon lookup carte par carte."""
    _maybe_refresh_bulk_price_guide()
    if match.card_slug in _bulk_price_guide:
        return _bulk_price_guide[match.card_slug]

    price_result = _cardmarket_client.fetch_reference_price(expansion_slug="", card_slug=match.card_slug)
    if price_result is None:
        return None
    return price_result.trend_price_eur or price_result.avg_30d_price_eur


def _lookup_zebradex_price(match) -> Optional[float]:
    _maybe_refresh_zebradex_cache()
    return _zebradex_prices.get(match.card_slug)


def _get_or_fetch_reference_price(db: Session, title: str) -> tuple:
    """
    Retourne (reference_price, source_label) ou (None, None). Combine
    Cardmarket et ZebraDex quand les deux sont disponibles (moyenne simple,
    label "cardmarket+zebradex") ; utilise celui des deux qui est
    disponible sinon. Le résultat combiné est mis en cache 1 jour en DB
    sous la même clé que précédemment (le format ne change pas).
    """
    match = guess_card_from_title(title)
    if match is None:
        return None, None

    cached = db.query(PriceReference).filter_by(card_slug=match.card_slug).first()
    if cached and cached.fetched_at and datetime.utcnow() - cached.fetched_at < PRICE_CACHE_MAX_AGE:
        price = cached.trend_price_eur or cached.avg_30d_price_eur
        return price, (cached.price_source or "cardmarket") + " (cache)"

    cardmarket_price = _lookup_cardmarket_price(match)
    zebradex_price = _lookup_zebradex_price(match)

    if cardmarket_price is not None and zebradex_price is not None:
        price = (cardmarket_price + zebradex_price) / 2
        source_label = "cardmarket+zebradex"
    elif cardmarket_price is not None:
        price = cardmarket_price
        source_label = "cardmarket"
    elif zebradex_price is not None:
        price = zebradex_price
        source_label = "zebradex"
    else:
        return None, None

    if cached:
        cached.trend_price_eur = price
        cached.fetched_at = datetime.utcnow()
        cached.price_source = source_label
    else:
        db.add(PriceReference(
            card_slug=match.card_slug,
            trend_price_eur=price,
            price_source=source_label,
            fetched_at=datetime.utcnow(),
        ))
    db.commit()

    return price, source_label


def _score_listing(db: Session, listing: Listing):
    reference_price, source_label = _get_or_fetch_reference_price(db, listing.title)

    text_quality = analyze_text_quality(listing.title, listing.description)
    listing.quality_text_score = text_quality.score

    # NB coût : contrairement à la version précédente, l'analyse vision
    # tourne maintenant pour toute annonce avec photos dès que la clé est
    # configurée — même si le titre seul n'a pas suffi à trouver un prix —
    # car elle sert aussi de filet de rattrapage OCR juste en dessous. Sur
    # gros volume d'annonces au titre vague, ça peut augmenter le nombre
    # d'appels à l'API Anthropic (donc le coût). Si ça devient un souci,
    # la façon la plus simple de limiter la casse est de réduire
    # CHECK_INTERVAL_MINUTES/le volume de mots-clés de recherche plutôt que
    # de complexifier cette logique.
    vision_score = None
    vision_result = None
    if settings.anthropic_api_key and listing.photo_urls:
        vision_result = analyze_card_photos(
            api_key=settings.anthropic_api_key,
            photo_urls=listing.photo_urls,
            title=listing.title,
            description=listing.description,
            model=settings.vision_model,
        )
        if vision_result:
            vision_score = vision_result.score
            listing.quality_vision_score = vision_result.score
            listing.quality_vision_detail = vision_result.to_dict()

    # Filet de rattrapage : si le titre de l'annonce n'a pas suffi à trouver
    # un prix de référence (ex: "Lot cartes pokémon TBE" très générique) mais
    # que l'analyse vision a pu lire un nom/numéro directement sur la carte
    # avec une confiance correcte, on retente avec cette identification —
    # souvent plus fiable qu'un titre écrit à la va-vite par un particulier.
    if reference_price is None and vision_result and vision_result.ocr_confidence in ("medium", "high"):
        ocr_text = f"{vision_result.printed_name} {vision_result.printed_set_number}".strip()
        if ocr_text:
            reference_price, source_label = _get_or_fetch_reference_price(db, ocr_text)
            if reference_price is not None:
                source_label = f"{source_label} (via OCR photo)"

    if reference_price is None:
        listing.status = ListingStatus.IGNORED
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    listing.reference_price = reference_price
    listing.reference_price_source = source_label

    margin_result = calculate_margin(
        listing_price=listing.price,
        listing_shipping=listing.shipping_price or 0.0,
        reference_price=reference_price,
        resale_channel="cardmarket",
    )
    listing.margin_net = margin_result.net_margin
    listing.margin_ratio = margin_result.margin_ratio
    margin_score = normalize_margin_ratio(margin_result.margin_ratio)

    quality_blend = QualityBlend(text_score=text_quality.score, vision_score=vision_score)

    if listing.source == SourcePlatform.EBAY:
        seller_result = score_ebay_seller(
            feedback_percentage=None,  # renseigné directement dans la collecte, voir run_ebay_check
            feedback_score=None,
        )
    else:
        seller_result = score_vinted_seller(review_count=None, average_rating=None)

    if listing.seller_reliability_score is not None:
        # déjà calculé lors de la collecte (on a les vraies données là-bas)
        pass
    else:
        listing.seller_reliability_score = seller_result.score
        listing.seller_reliability_detail = seller_result.detail

    listing.deal_score = calculate_deal_score(
        margin_score_0_100=margin_score,
        quality_blend=quality_blend,
        seller_score_0_100=listing.seller_reliability_score or 50.0,
    )
    listing.status = ListingStatus.SCORED
    listing.scored_at = datetime.utcnow()
    db.commit()


def _maybe_notify(db: Session, listing: Listing, threshold: float):
    if listing.deal_score is None or listing.deal_score < threshold:
        return
    if listing.status == ListingStatus.NOTIFIED:
        return

    sent_any = False

    if settings.telegram_bot_token and settings.telegram_chat_id:
        text = format_deal_alert(listing)
        ok = send_telegram_message(settings.telegram_bot_token, settings.telegram_chat_id, text)
        db.add(NotificationSent(listing_id=listing.id, channel="telegram", success=ok))
        sent_any = sent_any or ok

    if settings.smtp_host and settings.notification_email_to:
        ok = send_email_notification(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_password=settings.smtp_password,
            to_address=settings.notification_email_to,
            subject=f"🔥 Bonne affaire Pokémon (score {listing.deal_score:.0f})",
            body=format_deal_alert_html(listing),
        )
        db.add(NotificationSent(listing_id=listing.id, channel="email", success=ok))
        sent_any = sent_any or ok

    if sent_any:
        listing.status = ListingStatus.NOTIFIED
    db.commit()


def run_ebay_check(db: Session):
    if not settings.ebay_client_id or not settings.ebay_client_secret:
        logger.info("eBay: clés absentes, module désactivé pour ce cycle")
        return

    client = EbayBrowseClient(
        client_id=settings.ebay_client_id,
        client_secret=settings.ebay_client_secret,
        marketplace_id=settings.ebay_marketplace_id,
        use_sandbox=settings.ebay_use_sandbox,
    )
    try:
        results = client.search_pokemon_listings(keywords="pokemon carte francais")
    except Exception as exc:  # on isole les pannes d'une source de l'autre
        logger.error("eBay: cycle de collecte échoué (%s)", exc)
        return

    for item in results:
        existing = db.query(Listing).filter_by(
            source=SourcePlatform.EBAY, external_id=item.item_id
        ).first()
        if existing:
            existing.last_seen_at = datetime.utcnow()
            db.commit()
            continue

        seller_result = score_ebay_seller(
            feedback_percentage=item.seller_feedback_percentage,
            feedback_score=item.seller_feedback_score,
        )

        listing = Listing(
            source=SourcePlatform.EBAY,
            external_id=item.item_id,
            title=item.title,
            description="",  # Browse API search results n'incluent pas la description complète
            url=item.item_web_url,
            price=item.price,
            shipping_price=item.shipping_cost or 0.0,
            currency=item.currency,
            photo_urls=[item.image_url] if item.image_url else [],
            seller_username=item.seller_username,
            seller_reliability_score=seller_result.score,
            seller_reliability_detail=seller_result.detail,
        )
        db.add(listing)
        db.commit()
        _score_listing(db, listing)
        _maybe_notify(db, listing, threshold=settings.default_deal_score_threshold)


def run_vinted_check(db: Session):
    if not settings.vinted_enabled:
        logger.info("Vinted: désactivé par config")
        return

    try:
        results = _vinted_scraper.search_pokemon_listings(search_text=settings.vinted_search_text)
    except VintedBlockedError as exc:
        logger.warning("Vinted: %s", exc)
        return
    except Exception as exc:
        logger.error("Vinted: cycle de collecte échoué (%s)", exc)
        return

    for item in results:
        existing = db.query(Listing).filter_by(
            source=SourcePlatform.VINTED, external_id=item.item_id
        ).first()
        if existing:
            existing.last_seen_at = datetime.utcnow()
            db.commit()
            continue

        seller_result = score_vinted_seller(
            review_count=item.seller_review_count,
            average_rating=item.seller_average_rating,
        )

        listing = Listing(
            source=SourcePlatform.VINTED,
            external_id=item.item_id,
            title=item.title,
            description=item.description or "",
            url=item.url,
            price=item.price,
            shipping_price=0.0,  # à affiner : Vinted affiche le port au niveau du panier, pas de l'item
            currency=item.currency,
            photo_urls=item.photo_urls,
            seller_username=item.seller_username,
            seller_reliability_score=seller_result.score,
            seller_reliability_detail=seller_result.detail,
        )
        db.add(listing)
        db.commit()
        _score_listing(db, listing)
        _maybe_notify(db, listing, threshold=settings.default_deal_score_threshold)


def run_full_check(db: Session):
    logger.info("=== Début du cycle de vérification ===")
    run_ebay_check(db)
    run_vinted_check(db)
    logger.info("=== Fin du cycle de vérification ===")
