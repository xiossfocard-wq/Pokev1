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
from sqlalchemy import nullslast, select

from app.config import settings
from app.collectors.cardmarket_prices import CardmarketPriceClient
from app.collectors.ebay_browse import EbayBrowseClient
from app.collectors.vinted_scraper import VintedScraper, VintedBlockedError
from app.core.language_filter import looks_non_french
from app.models import Listing, SourcePlatform, ListingStatus, PriceReference, NotificationSent
from app.scoring.margin import calculate_margin, normalize_margin_ratio
from app.scoring.quality_text import analyze_text_quality
from app.scoring.card_appeal import detect_card_appeal
from app.services.price_index import find_price_for_listing, sync_series_batch
from app.scoring.deal_score import calculate_deal_score, QualityBlend
from app.scoring.seller_reliability import score_ebay_seller, score_vinted_seller
from app.vision.quality_vision import analyze_card_photos
from app.notifications.telegram import send_telegram_message, format_deal_alert
from app.notifications.email_notif import send_email_notification, format_deal_alert_html

logger = logging.getLogger(__name__)

PRICE_CACHE_MAX_AGE = timedelta(days=1)

# Plafond de score des annonces dont le prix de reference n'est PAS fiable.
# Le score brut est ramene dans la bande 0-60 plutot que simplement coupe :
# l'ordre entre ces annonces est conserve (qualite du texte, fiabilite du
# vendeur et rarete continuent de les departager), mais aucune ne peut plus
# passer devant une annonce dont le prix est verifie, ni franchir le seuil
# de notification (70 par defaut). Un radar ne doit pas crier "pepite" sur
# une annonce dont il est incapable d'etablir la valeur.
UNCERTAIN_SCORE_CAP = 60.0

_cardmarket_client = CardmarketPriceClient()
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


def _get_or_fetch_reference_price(db: Session, title: str, description: str = "") -> tuple:
    """
    Resout le prix de reference depuis l'index local (voir
    services/price_index.py). Retourne (prix, libelle_source, detail_dict)
    ou (None, None, None).

    Change le 04/08/2026 : avant, chaque annonce declenchait une requete
    Cardmarket carte-par-carte qui echouait presque toujours (l'URL exige
    l'extension exacte, indevinable depuis un titre Vinted). Desormais
    l'index ZebraDex complet est construit en tache de fond et le matching
    se fait en local, sans requete reseau par annonce.
    """
    match = find_price_for_listing(db, title, description)
    if match is None:
        return None, None, None
    detail = match.to_dict()
    label = f"zebradex ({detail['confidence']})"
    return match.row.price_eur, label, detail


def _score_listing(db: Session, listing: Listing, skip_vision: bool = False):
    """`skip_vision=True` sert au repassage des annonces sans prix : on
    reutilise le score vision deja calcule au lieu de rappeler (et de
    repayer) l'API pour une photo qu'on a deja analysee."""
    # Filtre langue (activé par défaut, voir FRENCH_ONLY dans .env) : le
    # plus tôt possible, avant même de dépenser un appel Cardmarket/vision,
    # pour ne pas payer à analyser des annonces qu'on ignorera de toute
    # façon. Ne détecte que les indices EXPLICITES de langue étrangère dans
    # le titre (voir app/core/language_filter.py) — un titre qui ne dit
    # rien est traité comme probablement français, pas comme suspect.
    if settings.french_only and looks_non_french(listing.title, listing.description):
        listing.status = ListingStatus.IGNORED
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    reference_price, source_label, price_detail = _get_or_fetch_reference_price(
        db, listing.title, listing.description or ""
    )

    text_quality = analyze_text_quality(listing.title, listing.description)
    listing.quality_text_score = text_quality.score
    listing.condition_tier = text_quality.condition_tier

    appeal = detect_card_appeal(listing.title, listing.description)
    listing.rarity_tier = appeal["rarity_tier"]
    listing.is_vintage = appeal["is_vintage"]
    listing.is_popular_pokemon = appeal["is_popular_pokemon"]

    # NB coût : contrairement à la version précédente, l'analyse vision
    # tourne maintenant pour toute annonce avec photos dès que la clé est
    # configurée — même si le titre seul n'a pas suffi à trouver un prix —
    # car elle sert aussi de filet de rattrapage OCR juste en dessous. Sur
    # gros volume d'annonces au titre vague, ça peut augmenter le nombre
    # d'appels à l'API Anthropic (donc le coût). Si ça devient un souci,
    # la façon la plus simple de limiter la casse est de réduire
    # CHECK_INTERVAL_MINUTES/le volume de mots-clés de recherche plutôt que
    # de complexifier cette logique.
    vision_score = listing.quality_vision_score
    vision_result = None
    if not skip_vision and settings.anthropic_api_key and listing.photo_urls:
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

    # Second filtre langue, cette fois basé sur ce que la vision a
    # réellement lu sur la carte (plus fiable que le titre pour les
    # annonces qui ne précisent rien) — s'applique même si le titre seul
    # n'avait rien détecté. On ne rejette que sur un signal net (pas de
    # français), pas sur une lecture vide/incertaine.
    if (
        settings.french_only
        and vision_result
        and vision_result.printed_language
        and vision_result.printed_language not in ("français", "francais", "french")
    ):
        listing.status = ListingStatus.IGNORED
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    # Filet de rattrapage : si le titre de l'annonce n'a pas suffi à trouver
    # un prix de référence (ex: "Lot cartes pokémon TBE" très générique) mais
    # que l'analyse vision a pu lire un nom/numéro directement sur la carte
    # avec une confiance correcte, on retente avec cette identification —
    # souvent plus fiable qu'un titre écrit à la va-vite par un particulier.
    if reference_price is None and vision_result and vision_result.ocr_confidence in ("medium", "high"):
        ocr_text = f"{vision_result.printed_name} {vision_result.printed_set_number}".strip()
        if ocr_text:
            reference_price, source_label, price_detail = _get_or_fetch_reference_price(db, ocr_text)
            if reference_price is not None:
                source_label = f"{source_label} (via OCR photo)"

    if reference_price is None:
        # NB (04/08/2026) : avant, ce cas utilisait IGNORED, ce qui faisait
        # disparaître l'annonce du dashboard (routers/listings.py exclut
        # IGNORED) — corrigé suite à un retour : l'utilisateur veut voir ces
        # annonces quand même pour comparer manuellement au prix du marché,
        # même sans marge calculée automatiquement.
        listing.status = ListingStatus.NO_PRICE_MATCH
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    listing.reference_price = reference_price
    listing.reference_price_source = source_label
    if price_detail:
        listing.price_detail = price_detail
        listing.price_low_eur = price_detail.get("price_low_eur")
        listing.price_high_eur = price_detail.get("price_high_eur")
        listing.price_match_confidence = price_detail.get("confidence")
        # La rarete officielle ZebraDex est plus fiable que la detection
        # par mots-cles du titre : elle a la priorite quand disponible.
        if price_detail.get("rarity"):
            listing.rarity_tier = price_detail["rarity"]

    margin_result = calculate_margin(
        listing_price=listing.price,
        listing_shipping=listing.shipping_price or 0.0,
        reference_price=reference_price,
        resale_channel="cardmarket",
    )
    listing.margin_net = margin_result.net_margin
    listing.margin_ratio = margin_result.margin_ratio

    # Une marge calculee sur un prix de reference douteux n'est pas une
    # information : c'est un chiffre inventé. Quand le rapprochement est
    # incertain (nom seul, plusieurs cartes homonymes aux prix tres
    # differents, variante qui ne correspond pas), la marge reste AFFICHEE
    # a titre indicatif mais ne pese plus dans le score - sinon ce sont
    # justement les rapprochements les plus fragiles qui trustent le haut
    # du classement, avec des "+63 EUR" qui n'existent pas.
    prix_doute = bool(price_detail and price_detail.get("uncertain"))
    margin_score = 50.0 if prix_doute else normalize_margin_ratio(margin_result.margin_ratio)

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

    score_brut = min(100.0, calculate_deal_score(
        margin_score_0_100=margin_score,
        quality_blend=quality_blend,
        seller_score_0_100=listing.seller_reliability_score or 50.0,
    ) + appeal["appeal_bonus"])
    listing.deal_score = (
        round(score_brut * UNCERTAIN_SCORE_CAP / 100.0, 1) if prix_doute else score_brut
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

    # Deux passes avec des tris différents plutôt qu'une seule : "newest_first"
    # seul ratait les bonnes affaires plus anciennes toujours en vente (retour
    # utilisateur du 04/08/2026). "price_low_to_high" n'a pas pu être vérifié
    # en conditions réelles (paramètre standard chez Vinted mais pas testé
    # spécifiquement sur ce catalogue) — si cette 2e passe ne remonte rien de
    # nouveau, vérifier avec /api/admin/debug-vinted en changeant le tri.
    results = []
    try:
        results += _vinted_scraper.search_pokemon_listings(
            search_text=settings.vinted_search_text, sort_order="newest_first"
        )
        results += _vinted_scraper.search_pokemon_listings(
            search_text=settings.vinted_search_text, sort_order="price_low_to_high"
        )
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


def _existing_by_external_id(db: Session, source, external_ids: list) -> dict:
    """Recupere en UNE requete les annonces deja connues, au lieu d'une
    requete par annonce. Sur Neon (base distante), chaque aller-retour coute
    ~100 ms : sur 50 annonces ca faisait plusieurs secondes pour rien."""
    if not external_ids:
        return {}
    rows = (
        db.query(Listing)
        .filter(Listing.source == source, Listing.external_id.in_(external_ids))
        .all()
    )
    return {row.external_id: row for row in rows}


def run_targeted_search(db: Session, query: str, limit: int = 60, on_progress=None) -> list:
    """
    Recherche A LA DEMANDE sur un terme precis (ex: "Pikachu", "Dracaufeu
    ex", un code de set...), contrairement a run_ebay_check/run_vinted_check
    qui tournent en tache de fond sur le terme generique de config.

    Duree typique : 1 a 5 minutes. C'est pour cette raison qu'elle n'est PAS
    appelee directement depuis la requete HTTP mais via un job de fond (voir
    app/services/search_jobs.py). `on_progress` recoit des messages d'etape
    a afficher a l'utilisateur pendant l'attente.
    """
    query = (query or "").strip()
    if not query:
        return []

    def progress(message: str):
        if on_progress:
            on_progress(message)

    matched_keys = set()

    if settings.vinted_enabled:
        progress("Recherche sur Vinted…")
        try:
            vinted_results = _vinted_scraper.search_pokemon_listings(
                search_text=query, sort_order="newest_first"
            )
        except VintedBlockedError as exc:
            logger.warning("Recherche ciblee Vinted: %s", exc)
            vinted_results = []
        except Exception as exc:
            logger.error("Recherche ciblee Vinted echouee (%s)", exc)
            vinted_results = []

        known = _existing_by_external_id(
            db, SourcePlatform.VINTED, [item.item_id for item in vinted_results]
        )
        seen_at = datetime.utcnow()
        new_items = []
        for item in vinted_results:
            matched_keys.add((SourcePlatform.VINTED, item.item_id))
            existing = known.get(item.item_id)
            if existing:
                existing.last_seen_at = seen_at
            else:
                new_items.append(item)
        db.commit()  # un seul commit pour tous les "deja vus"

        for position, item in enumerate(new_items, start=1):
            progress(f"Vinted : analyse de l'annonce {position}/{len(new_items)}…")
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
                shipping_price=0.0,
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

    if settings.ebay_client_id and settings.ebay_client_secret:
        progress("Recherche sur eBay…")
        try:
            client = EbayBrowseClient(
                client_id=settings.ebay_client_id,
                client_secret=settings.ebay_client_secret,
                marketplace_id=settings.ebay_marketplace_id,
                use_sandbox=settings.ebay_use_sandbox,
            )
            ebay_results = client.search_pokemon_listings(keywords=f"pokemon carte {query}")
        except Exception as exc:
            logger.error("Recherche ciblee eBay echouee (%s)", exc)
            ebay_results = []

        known = _existing_by_external_id(
            db, SourcePlatform.EBAY, [item.item_id for item in ebay_results]
        )
        seen_at = datetime.utcnow()
        new_items = []
        for item in ebay_results:
            matched_keys.add((SourcePlatform.EBAY, item.item_id))
            existing = known.get(item.item_id)
            if existing:
                existing.last_seen_at = seen_at
            else:
                new_items.append(item)
        db.commit()

        for position, item in enumerate(new_items, start=1):
            progress(f"eBay : analyse de l'annonce {position}/{len(new_items)}…")
            seller_result = score_ebay_seller(
                feedback_percentage=item.seller_feedback_percentage,
                feedback_score=item.seller_feedback_score,
            )
            listing = Listing(
                source=SourcePlatform.EBAY,
                external_id=item.item_id,
                title=item.title,
                description="",
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

    if not matched_keys:
        return []

    progress("Mise en forme des resultats…")
    conditions = [
        (Listing.source == src) & (Listing.external_id == ext_id)
        for src, ext_id in matched_keys
    ]
    combined = conditions[0]
    for cond in conditions[1:]:
        combined = combined | cond

    return (
        db.query(Listing)
        .filter(combined)
        .filter(Listing.status != ListingStatus.IGNORED)
        .order_by(nullslast(Listing.deal_score.desc()))
        .limit(limit)
        .all()
    )


def rescore_unpriced_listings(
    db: Session, limit: int = 120, include_uncertain: bool = True
) -> dict:
    """
    Repasse sur les annonces mal loties et retente le rapprochement :
    - celles restees SANS prix de reference ;
    - avec `include_uncertain`, celles dont le prix a ete trouve en
      confiance "faible" (nom seul, plusieurs cartes homonymes) : ce sont
      souvent des prix carrement FAUX, pas juste imprecis, et sans ce
      repassage ils ne se corrigeaient jamais.

    Indispensable pour deux raisons : l'index de prix se construit
    progressivement (une annonce collectee avant sa serie n'avait aucune
    chance d'etre reconnue), et le moteur de matching s'ameliore avec le
    temps. Sans ce repassage, une annonce mal identifiee une fois l'etait
    pour toujours - alors que le bandeau du dashboard promet exactement
    l'inverse ("les annonces sans prix seront recalculees au fur et a
    mesure").

    Les annonces les plus anciennement scorees passent en premier : ca fait
    tourner la file au lieu de reexaminer sans cesse les memes.

    L'analyse vision est sautee (deja faite, et facturee) : ce repassage ne
    coute rien d'autre que des requetes en base.
    """
    condition = Listing.reference_price.is_(None)
    if include_uncertain:
        condition = condition | (Listing.price_match_confidence == "low")

    listings = (
        db.query(Listing)
        .filter(condition, Listing.status != ListingStatus.IGNORED)
        .order_by(Listing.scored_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )

    before = [(l.reference_price, l.price_match_confidence) for l in listings]

    recovered, corrected = 0, 0
    for listing, (old_price, _old_confidence) in zip(listings, before):
        try:
            _score_listing(db, listing, skip_vision=True)
        except Exception as exc:
            db.rollback()
            logger.error("Repassage de l'annonce %s echoue (%s)", listing.id, exc)
            continue
        if old_price is None and listing.reference_price is not None:
            recovered += 1
        elif old_price is not None and listing.reference_price != old_price:
            corrected += 1

    logger.info(
        "Repassage : %d annonce(s) reexaminee(s), %d ont trouve un prix, "
        "%d ont vu leur prix corrige",
        len(listings), recovered, corrected,
    )
    return {"examined": len(listings), "recovered": recovered, "corrected": corrected}


def refilter_language(db: Session, limit: int = 2000) -> dict:
    """
    Repasse le filtre de langue sur les annonces DEJA en base.

    Necessaire parce que le filtre s'ameliore avec le temps, alors qu'une
    annonce n'est evaluee qu'une fois, a la collecte. Sans ce passage, une
    carte japonaise ou anglaise entree avant l'amelioration reste affichee
    pour toujours - y compris en tete des resultats, ce qui est le pire cas
    (constate le 25/08/2026 : une carte anglaise arrivait n1 avec un score
    de 97).

    Tres bon marche : aucune requete reseau, aucun scoring, on ne lit que le
    titre et la description deja stockes.
    """
    listings = (
        db.query(Listing)
        .filter(Listing.status != ListingStatus.IGNORED)
        .limit(limit)
        .all()
    )

    exclues = 0
    for listing in listings:
        if looks_non_french(listing.title, listing.description):
            listing.status = ListingStatus.IGNORED
            exclues += 1
    db.commit()

    logger.info(
        "Filtre langue : %d annonce(s) reexaminee(s), %d ecartee(s) comme non francaises",
        len(listings), exclues,
    )
    return {"examined": len(listings), "excluded": exclues}


def check_vinted_availability(db: Session, limit: int = 10, pool: int = 200) -> dict:
    """
    Verifie que les MEILLEURES annonces Vinted sont toujours en ligne, et
    masque celles qui ont disparu.

    Pourquoi seulement les meilleures : verifier chaque annonce coute une
    requete HTTP, avec 8 s de politesse entre chacune. Sur 1 200 annonces
    ce serait presque 3 heures par cycle - intenable, et discourtois. Or ce
    sont les annonces les mieux classees qu'on clique : ce sont donc elles
    qui doivent etre vivantes. On prend donc les `pool` meilleures, et dans
    ce vivier les `limit` moins recemment verifiees — de sorte que la file
    tourne pour de bon et que le vivier entier soit couvert en une
    vingtaine de cycles.

    Ne concerne que Vinted : eBay garde ses annonces terminees en ligne,
    leurs liens restent donc valides.
    """
    # Deux etages, et non un simple tri par score : trier uniquement par
    # score ferait reverifier les 10 MEMES annonces a chaque cycle, sans
    # jamais descendre plus bas. On constitue donc un vivier des
    # `pool` meilleures annonces, puis on y prend les moins recemment
    # verifiees — la file tourne vraiment, et le vivier entier est couvert
    # en une vingtaine de cycles.
    vivier = (
        select(Listing.id)
        .where(
            Listing.source == SourcePlatform.VINTED,
            Listing.status.notin_([ListingStatus.IGNORED, ListingStatus.UNAVAILABLE]),
        )
        .order_by(nullslast(Listing.deal_score.desc()))
        .limit(pool)
    )
    listings = (
        db.query(Listing)
        .filter(Listing.id.in_(vivier))
        .order_by(Listing.last_seen_at.asc())
        .limit(limit)
        .all()
    )

    # On retient (id, url) plutot que les objets : entre deux verifications
    # il s'ecoule 8 s, et on commite au fil de l'eau — les objets seraient
    # expires a chaque tour.
    cibles = [(listing.id, listing.url) for listing in listings]

    disparues, verifiees = 0, 0
    for listing_id, url in cibles:
        online = _vinted_scraper.is_listing_online(url)
        if online is None:
            continue  # doute : on ne masque rien

        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if listing is None:
            continue

        verifiees += 1
        if online:
            listing.last_seen_at = datetime.utcnow()
        else:
            listing.status = ListingStatus.UNAVAILABLE
            disparues += 1

        # Un commit par annonce, et NON un seul a la fin. Chaque
        # verification prend 8 s (politesse envers Vinted) : une passe de
        # 40 annonces laisserait la connexion Neon inactive plus de cinq
        # minutes, Neon la fermerait, et le commit final partirait en
        # erreur 500 — exactement ce qui s'est produit le 25/08/2026, meme
        # famille de panne que le commit 88fa2dc. Commiter au fil de l'eau
        # garde la connexion vivante et conserve le travail deja fait si la
        # passe est interrompue.
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Disponibilite : ecriture echouee sur %s (%s)", listing_id, exc)

    logger.info(
        "Disponibilite Vinted : %d annonce(s) verifiee(s), %d disparue(s)",
        verifiees, disparues,
    )
    return {"checked": verifiees, "gone": disparues, "examined": len(listings)}


def run_full_check(db: Session):
    logger.info("=== Debut du cycle de verification ===")

    # NB (05/08/2026) : collecte (eBay/Vinted) D'ABORD, index de prix
    # ZebraDex ENSUITE. L'ordre precedent retardait Vinted/eBay de
    # plusieurs heures tant que l'index progressif (6 series/cycle sur
    # 158) n'avait pas avance. Les annonces sans prix restent visibles et
    # seront recalculees au fur et a mesure.
    run_ebay_check(db)
    run_vinted_check(db)

    try:
        summary = sync_series_batch(db, batch_size=settings.zebradex_batch_size)
        logger.info(
            "Index prix : +%d serie(s), %d cartes en base, %d serie(s) restantes",
            summary["series_synced"], summary["total_prices_in_index"],
            summary["series_never_synced_remaining"],
        )
    except Exception as exc:
        db.rollback()
        logger.error("Index prix : synchronisation echouee (%s) - collecte poursuivie", exc)

    # Apres avoir enrichi l'index, on retente les annonces restees sans
    # prix : c'est ce qui rend visible l'avancement de l'indexation sur les
    # annonces deja collectees.
    try:
        rescore_unpriced_listings(db)
    except Exception as exc:
        db.rollback()
        logger.error("Repassage des annonces sans prix echoue (%s)", exc)

    # Le filtre de langue s'ameliore avec le temps, mais une annonce n'est
    # evaluee qu'a la collecte : sans ce passage, les cartes etrangeres
    # entrees avant une amelioration resteraient affichees indefiniment.
    if settings.french_only:
        try:
            refilter_language(db)
        except Exception as exc:
            db.rollback()
            logger.error("Repassage du filtre de langue echoue (%s)", exc)

    # Les annonces les mieux classees sont celles qu'on clique : on verifie
    # qu'elles sont toujours en ligne, pour ne pas envoyer l'utilisateur sur
    # une page d'erreur Vinted.
    if settings.vinted_enabled:
        try:
            check_vinted_availability(db)
        except Exception as exc:
            db.rollback()
            logger.error("Verification de disponibilite echouee (%s)", exc)

    logger.info("=== Fin du cycle de verification ===")
