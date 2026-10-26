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
from app.models import Listing, SourcePlatform, ListingStatus, PriceReference, NotificationSent, MarketCardPrice
from app.scoring.margin import (
    DECOTE_PAR_ETAT, calculate_margin, cout_d_achat, etat_retenu, etat_vinted,
    normalize_margin_ratio,
)
from app.scoring.pieges import detecter as detecter_pieges
from app.scoring.quality_text import analyze_text_quality
from app.scoring.card_appeal import detect_card_appeal
from app.services.price_index import find_price_for_listing
from app.services import suivi as suivi_service
from app.scoring.deal_score import calculate_deal_score, DealScoreWeights, QualityBlend
from app.scoring.seller_reliability import score_ebay_seller, score_vinted_seller
from app.collectors.card_images import (
    MARQUE_DEDUITE, SOURCE_EN, ClientImagesCartes, base_de_source,
    code_canonique, suffixe_de_rang,
)
from app.vision.quality_vision import analyze_card_photos
from app.notifications.telegram import send_telegram_message, format_deal_alert
from app.notifications.email_notif import send_email_notification, format_deal_alert_html
from app.settings_service import load_app_settings

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
    # La source reelle du prix retenu : « zebradex » etait ecrit en dur
    # depuis l'ancien index Pokemon, et designait aussi les prix OPECards.
    label = f"{match.row.source or 'index'} ({detail['confidence']})"
    return match.row.price_eur, label, detail


def _resolve_reference_price(db: Session, listing: Listing) -> tuple:
    """
    Prix de reference d'une annonce, en donnant TOUJOURS le dernier mot a
    l'utilisateur.

    - il a saisi un prix a la main : c'est celui-la, en confiance maximale ;
    - il a signale "ce n'est pas la bonne carte" : aucune identification
      automatique n'est retentee, on prefere ne rien afficher qu'afficher
      ce qu'il a deja rejete ;
    - sinon : identification automatique habituelle.
    """
    if listing.manual_reference_price is not None:
        detail = {
            "price_eur": listing.manual_reference_price,
            "price_low_eur": None,
            "price_high_eur": None,
            "variation_7d_eur": None,
            "rarity": None,
            "series_name": None,
            "matched_card": "Prix saisi par toi",
            "matched_code": None,
            "matched_card_id": None,
            "matched_name_slug": None,
            "confidence": "manual",
            "reason": "prix de marche que tu as corrige toi-meme",
            "source": "manuel",
            "candidates_count": 1,
            "price_spread_eur": 0.0,
            "candidates_min_eur": None,
            "candidates_max_eur": None,
            "uncertain": False,
            "warning": None,
        }
        return listing.manual_reference_price, "corrige par toi", detail

    if listing.manual_status == "wrong_card":
        return None, None, None

    return _get_or_fetch_reference_price(db, listing.title, listing.description or "")


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
    # Une annonce que l'utilisateur a lui-meme examinee ne doit plus etre
    # ecartee automatiquement : s'il l'a corrigee, c'est qu'il la veut.
    if (settings.french_only and not listing.manual_reviewed_at
            and looks_non_french(listing.title, listing.description)):
        listing.status = ListingStatus.IGNORED
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    # LES PIEGES qu'un collectionneur repere au premier coup d'oeil (voir
    # scoring/pieges.py). Une contrefacon n'est jamais une affaire : avant
    # cette garde, « … proxy fan art » a 2,48 EUR arrivait EN TETE du radar,
    # score 82. Elle est ecartee, avec sa raison — sauf si l'utilisateur a
    # lui-meme examine l'annonce, auquel cas son verdict prime.
    pieges = detecter_pieges(listing.title, listing.description)
    if pieges.contrefacon and not listing.manual_reviewed_at:
        listing.status = ListingStatus.IGNORED
        listing.price_detail = {
            "exclusion": f"contrefaçon probable : « {pieges.contrefacon} »"}
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    reference_price, source_label, price_detail = _resolve_reference_price(db, listing)

    text_quality = analyze_text_quality(listing.title, listing.description)
    listing.quality_text_score = text_quality.score
    listing.condition_tier = text_quality.condition_tier

    appeal = detect_card_appeal(listing.title, listing.description)
    listing.rarity_tier = appeal["rarity_tier"]
    listing.is_vintage = appeal["is_vintage"]
    listing.is_popular_character = appeal["is_popular_character"]

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
    #
    # `manual_reviewed_at` protège ici la même chose que dans le filtre sur
    # le titre plus haut, et que dans refilter_language : une annonce que
    # l'utilisateur a examinée lui-même n'est plus écartée automatiquement.
    # Ce garde-fou manquait à ce seul endroit sur les trois. Le cas n'était
    # pas atteignable en pratique — les deux appelants qui repassent sur des
    # annonces existantes sautent la vision, donc vision_result y vaut None,
    # et une annonce toute neuve n'a par définition pas encore été examinée.
    # Mais l'invariant ne tenait que par la façon dont on appelle cette
    # fonction, pas par ce qu'elle garantit : le jour où une relance de
    # l'analyse photo passerait ici, le verdict de l'utilisateur serait
    # effacé en silence.
    if (
        settings.french_only
        and not listing.manual_reviewed_at
        and vision_result
        and vision_result.printed_language
        and vision_result.printed_language not in ("français", "francais", "french")
    ):
        listing.status = ListingStatus.IGNORED
        listing.scored_at = datetime.utcnow()
        db.commit()
        return

    # Filet de rattrapage : si le titre de l'annonce n'a pas suffi à trouver
    # un prix de référence (ex: "Lot cartes One Piece TBE" très générique) mais
    # que l'analyse vision a pu lire un nom/numéro directement sur la carte
    # avec une confiance correcte, on retente avec cette identification —
    # souvent plus fiable qu'un titre écrit à la va-vite par un particulier.
    if reference_price is None and vision_result and vision_result.ocr_confidence in ("medium", "high"):
        ocr_text = f"{vision_result.printed_name} {vision_result.printed_set_number}".strip()
        if ocr_text:
            prix_ocr, source_ocr, detail_ocr = _get_or_fetch_reference_price(db, ocr_text)
            if prix_ocr is not None:
                reference_price = prix_ocr
                source_label = f"{source_ocr} (via OCR photo)"
                price_detail = detail_ocr
            elif detail_ocr is not None and price_detail is None:
                # L'OCR n'a pas donne de prix, mais il a identifie la carte
                # la ou le titre n'identifiait rien. On garde cette
                # identification : elle vaut le visuel et la fiche.
                #
                # On n'ecrase JAMAIS un price_detail deja rempli par un
                # resultat vide : le titre avait pu identifier la carte sans
                # connaitre son prix, et le repli echouant aurait alors fait
                # perdre l'identification acquise.
                source_label, price_detail = source_ocr, detail_ocr

    # LE COUT REEL D'UN ACHAT, calcule avant la branche « pas de prix » : il
    # ne depend pas de la cote, et s'affiche aussi pour un lot. Article,
    # protection acheteur (relevee sur la page Vinted quand elle y est), port
    # — estime quand l'annonce ne le dit pas, et marque comme tel. Voir
    # scoring/margin.cout_d_achat.
    source = getattr(listing.source, "value", listing.source)
    cout = cout_d_achat(source, listing.price, listing.shipping_price,
                        listing.price_incl_protection, settings.vinted_port_estime)
    listing.purchase_cost_eur = cout["total"]
    listing.purchase_cost_detail = cout

    # L'ETAT AJUSTE LE PRIX DE REFERENCE, qui est celui d'une carte en tres
    # bon etat. Le pire de l'etat ecrit dans l'annonce et de celui coche sur
    # Vinted : une contradiction se resout du cote prudent.
    etat = etat_retenu(listing.condition_tier, etat_vinted(listing.seller_condition))
    if etat:
        listing.condition_tier = etat
    decote = DECOTE_PAR_ETAT.get(etat, 1.0)

    # Lot ou carte gradee : le prix d'une carte brute a l'unite ne dit rien de
    # leur valeur. L'annonce reste visible — un lot peut contenir la carte
    # qu'on cherche — mais SANS marge : elle passe par la branche « pas de
    # prix » ci-dessous, qui efface ce qui derive du prix et garde ce qui
    # derive de l'identification. Un prix saisi a la main, lui, est respecte.
    if pieges.non_comparable and listing.manual_reference_price is None:
        reference_price = None
        price_detail = {**(price_detail or {}), "non_comparable": pieges.non_comparable}

    if reference_price is None:
        # NB (04/08/2026) : avant, ce cas utilisait IGNORED, ce qui faisait
        # disparaître l'annonce du dashboard (routers/listings.py exclut
        # IGNORED) — corrigé suite à un retour : l'utilisateur veut voir ces
        # annonces quand même pour comparer manuellement au prix du marché,
        # même sans marge calculée automatiquement.
        #
        # NB (25/08/2026) : il faut aussi EFFACER ce qui avait ete calcule
        # auparavant. Sans ca, une annonce qui perd son prix (parce que
        # l'utilisateur signale "ce n'est pas la bonne carte", ou parce que
        # l'index a change) gardait son ancien prix, son ancienne marge et
        # son ancien score — et continuait de trôner en haut du classement
        # sur la foi d'un chiffre qu'on venait justement de retirer.
        #
        # NB (20/10/2026) : « pas de prix » et « pas de carte » sont deux
        # choses differentes, et ce bloc les traitait pareil. Depuis que le
        # catalogue peut contenir une carte dont le prix n'est pas connu, le
        # cas « j'ai reconnu la carte mais j'ignore ce qu'elle vaut » est
        # courant — et effacer matched_card_id y jetait une identification
        # correcte, donc le visuel et le lien vers la fiche, pour la seule
        # raison qu'un chiffre manquait.
        #
        # On efface donc ce qui derive du prix, et on garde ce qui derive de
        # l'identification. price_detail non vide = une carte a ete reconnue.
        listing.reference_price = None
        listing.reference_price_source = None
        listing.margin_net = None
        listing.margin_ratio = None
        listing.price_low_eur = None
        listing.price_high_eur = None
        listing.deal_score = None
        if price_detail:
            listing.price_detail = price_detail
            listing.price_match_confidence = price_detail.get("confidence")
            listing.matched_card_id = price_detail.get("matched_card_id")
            if price_detail.get("rarity"):
                listing.rarity_tier = price_detail["rarity"]
        else:
            listing.price_detail = None
            listing.price_match_confidence = None
            listing.matched_card_id = None
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
        listing.matched_card_id = price_detail.get("matched_card_id")
        # La rarete officielle ZebraDex est plus fiable que la detection
        # par mots-cles du titre : elle a la priorite quand disponible.
        if price_detail.get("rarity"):
            listing.rarity_tier = price_detail["rarity"]

    reference_ajustee = reference_price * decote
    detail = dict(listing.price_detail or {})
    if decote < 1.0:
        detail["etat_retenu"] = {"etat": etat, "coefficient": decote,
                                 "reference_ajustee": round(reference_ajustee, 2)}
    else:
        detail.pop("etat_retenu", None)

    margin_result = calculate_margin(
        listing_price=cout["article"] + cout["protection"],
        listing_shipping=cout["port"],
        reference_price=reference_ajustee,
        resale_channel="cardmarket",
    )

    # TROP BEAU POUR ETRE VRAI. Une carte cotee qui se vend au quart de sa
    # cote, c'est l'affaire qu'on chasse — et c'est aussi la ou se logent les
    # contrefacons non declarees, les arnaques et les erreurs d'identification.
    # L'annonce garde son score (les vraies affaires partent vite), mais elle
    # porte un avertissement visible. Mesure sur le prix DEMANDE, pas sur le
    # cout total : c'est le prix fixe par le vendeur qui est suspect, pas le
    # port qui s'y ajoute.
    if (reference_price >= SEUIL_ALERTE_COTE
            and cout["article"] < reference_ajustee * PART_ALERTE_COTE):
        detail["alerte"] = ("Prix à moins d'un quart de la cote : vérifie "
                            "l'authenticité et le vendeur avant d'acheter.")
    else:
        detail.pop("alerte", None)
    listing.price_detail = detail or None
    listing.margin_net = margin_result.net_margin
    listing.margin_ratio = margin_result.margin_ratio

    # MODE COLLECTION : ce qu'on economise par rapport a la cote ajustee a
    # l'etat, frais d'achat compris. Calcule dans les deux modes, pour que
    # passer de l'un a l'autre recalcule les scores sans renoter les annonces.
    listing.savings_eur = round(reference_ajustee - cout["total"], 2)
    listing.savings_ratio = (listing.savings_eur / reference_ajustee
                             if reference_ajustee > 0 else 0.0)

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

    listing.deal_score = calculer_deal_score(listing, load_app_settings(db))
    listing.status = ListingStatus.SCORED
    listing.scored_at = datetime.utcnow()
    db.commit()


# En mode collection, une carte payee la moitie de sa cote recoit tous les
# points d'« affaire » : au-dela, ce n'est plus l'affaire qui grandit, c'est
# le risque — voir l'alerte « trop beau pour etre vrai ».
PLAFOND_ECONOMIE = 0.5


def calculer_deal_score(listing: Listing, reglages: dict) -> Optional[float]:
    """Le score d'une annonce deja chiffree, a partir de ce qu'elle porte.

    Separe de _score_listing pour que changer de mode ou de poids dans les
    reglages recalcule tous les scores d'un coup, sans renoter les annonces.
    Et parce que les poids reglables n'etaient JAMAIS lus : calculate_deal_score
    etait appele sans eux, et les curseurs du tableau de bord ne changeaient
    rien au classement.
    """
    if listing.reference_price is None:
        return None

    # Une marge calculee sur un prix de reference douteux n'est pas une
    # information : c'est un chiffre inventé. Quand le rapprochement est
    # incertain (nom seul, plusieurs cartes homonymes aux prix tres
    # differents, variante qui ne correspond pas), la marge reste AFFICHEE
    # a titre indicatif mais ne pese plus dans le score - sinon ce sont
    # justement les rapprochements les plus fragiles qui trustent le haut
    # du classement, avec des "+63 EUR" qui n'existent pas.
    prix_doute = bool((listing.price_detail or {}).get("uncertain"))
    if reglages.get("mode_evaluation") == "revente" or listing.savings_ratio is None:
        part_affaire = normalize_margin_ratio(listing.margin_ratio or 0.0)
    else:
        part_affaire = normalize_margin_ratio(listing.savings_ratio, cap_ratio=PLAFOND_ECONOMIE)
    margin_score = 50.0 if prix_doute else part_affaire

    poids = DealScoreWeights(
        margin=float(reglages.get("margin_weight", 0.5)),
        quality=float(reglages.get("quality_weight", 0.3)),
        seller=float(reglages.get("seller_weight", 0.2)),
    )
    try:
        poids.normalized()
    except ValueError:
        # Trois poids a zero : on garde l'equilibre par defaut plutot que de
        # faire echouer la notation de toutes les annonces.
        poids = DealScoreWeights()

    quality_blend = QualityBlend(
        text_score=listing.quality_text_score if listing.quality_text_score is not None else 50.0,
        vision_score=listing.quality_vision_score,
    )
    # Le bonus d'attrait (personnage recherche, rarete) departage des
    # affaires ; il ne fait pas une affaire d'une annonce qui n'en est pas
    # une. Avant, une Nami payee au-dessus de sa cote gardait 50 points sur
    # la seule foi de son personnage.
    appeal = detect_card_appeal(listing.title, listing.description)
    bonus = appeal["appeal_bonus"] if part_affaire > 0 else 0
    score_brut = min(100.0, calculate_deal_score(
        margin_score_0_100=margin_score,
        quality_blend=quality_blend,
        seller_score_0_100=listing.seller_reliability_score or 50.0,
        weights=poids,
    ) + bonus)
    return round(score_brut * UNCERTAIN_SCORE_CAP / 100.0, 1) if prix_doute else score_brut


def recalculer_scores(db: Session) -> dict:
    """Recalcule le score de toutes les annonces chiffrees, apres un
    changement de mode ou de poids dans les reglages. Aucune requete externe,
    un seul enregistrement : quelques centaines d'annonces en une seconde."""
    reglages = load_app_settings(db)
    annonces = (
        db.query(Listing)
        .filter(Listing.reference_price.isnot(None),
                Listing.status.in_([ListingStatus.SCORED, ListingStatus.NOTIFIED]))
        .all()
    )
    for annonce in annonces:
        annonce.deal_score = calculer_deal_score(annonce, reglages)
    db.commit()
    return {"rescored": len(annonces)}


def _maybe_notify(db: Session, listing: Listing, threshold: Optional[float] = None):
    """Alerte sur une annonce qui depasse le seuil — ou qui tombe dans le
    budget d'une carte de « Ma liste », quel que soit son score : c'est
    l'alerte qu'un collectionneur attend vraiment.

    Le seuil est celui des Reglages. Avant, les appelants passaient la valeur
    FIXE de la configuration : le seuil regle dans le tableau de bord etait
    enregistre, affiche, et jamais lu.
    """
    if listing.status in (ListingStatus.NOTIFIED, ListingStatus.IGNORED):
        return
    reglages = load_app_settings(db)
    if threshold is None:
        threshold = reglages.get("deal_score_threshold", settings.default_deal_score_threshold)
    budget = suivi_service.budget_pour_annonce(db, listing)
    pour_ma_liste = bool(budget and budget["dans_le_budget"])
    if not pour_ma_liste and (listing.deal_score is None or listing.deal_score < threshold):
        return
    # Une annonce deja signalee ne l'est pas deux fois : le statut NOTIFIED
    # est reecrit quand l'annonce est renotee, la trace d'envoi, elle, reste.
    deja = (db.query(NotificationSent)
            .filter(NotificationSent.listing_id == listing.id, NotificationSent.success.is_(True))
            .first())
    if deja:
        return

    sent_any = False
    mode = reglages.get("mode_evaluation", "collection")
    budget_alerte = budget if pour_ma_liste else None

    if settings.telegram_bot_token and settings.telegram_chat_id:
        text = format_deal_alert(listing, mode, budget_alerte)
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
            subject=(f"★ {listing.title[:60]} dans ton budget" if pour_ma_liste
                     else f"🔥 Bonne affaire One Piece (score {listing.deal_score:.0f})"),
            body=format_deal_alert_html(listing, mode, budget_alerte),
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
        results = client.search_card_listings(keywords=settings.ebay_search_keywords)
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
        _maybe_notify(db, listing)


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
        results += _vinted_scraper.search_card_listings(
            search_text=settings.vinted_search_text, sort_order="newest_first"
        )
        results += _vinted_scraper.search_card_listings(
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

        listing = _nouvelle_annonce_vinted(item)
        db.add(listing)
        db.commit()
        _score_listing(db, listing)
        _maybe_notify(db, listing)


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


def _nouvelle_annonce_vinted(item) -> Listing:
    """Une annonce Vinted telle que le scraper l'a relevee.

    Une seule construction pour la collecte, la recherche ciblee et la chasse
    de « Ma liste ». Elles etaient ecrites a part, et la recherche ciblee
    oubliait le prix protection comprise et l'etat coche par le vendeur :
    ses annonces avaient un cout estime et un etat inconnu.
    """
    seller_result = score_vinted_seller(
        review_count=item.seller_review_count,
        average_rating=item.seller_average_rating,
    )
    brut = item.raw or {}
    return Listing(
        source=SourcePlatform.VINTED,
        external_id=item.item_id,
        title=item.title,
        description=item.description or "",
        url=item.url,
        price=item.price,
        shipping_price=0.0,  # Vinted fixe le port au panier : il est ESTIME dans le cout d'achat
        price_incl_protection=brut.get("price_incl_protection_acheteur"),
        seller_condition=brut.get("condition"),
        currency=item.currency,
        photo_urls=item.photo_urls,
        seller_username=item.seller_username,
        seller_reliability_score=seller_result.score,
        seller_reliability_detail=seller_result.detail,
    )


# Combien de cartes de « Ma liste » sont cherchees a chaque cycle de
# collecte. Vinted bloque les rafales : trois recherches de plus toutes les
# vingt minutes restent dans l'allure d'un humain qui navigue, et la file
# tourne — la carte cherchee il y a le plus longtemps passe en premier.
CARTES_CHASSEES_PAR_CYCLE = 3

# Le bilan de la derniere chasse, pour que la page « Ma liste » puisse dire
# pourquoi une recherche demandee n'a rien donne (Vinted injoignable, ou qui
# demande de ralentir) au lieu d'attendre en silence. En memoire : il ne
# sert qu'a la session en cours.
DERNIERE_CHASSE: dict = {}


def chasser_ma_liste(db: Session, par_cycle: int = CARTES_CHASSEES_PAR_CYCLE,
                     cle: Optional[tuple] = None) -> dict:
    """Cherche sur Vinted les cartes de « Ma liste ».

    La collecte de fond ne cherche que « carte one piece » : une carte
    precise n'y apparait que par hasard, parmi les dernieres annonces
    publiees. Sans cette chasse, la liste attendait qu'une carte suivie passe
    par la, au lieu d'aller la chercher. `cle` (code, fiche) : ne chercher
    que cette carte, a l'instant ou on l'ajoute.
    """
    bilan = {"cherchees": 0, "nouvelles": 0, "bloque": False}
    if not settings.vinted_enabled:
        return bilan
    for suivie, requete in suivi_service.a_chercher(db, par_cycle, cle=cle):
        try:
            resultats = _vinted_scraper.search_card_listings(
                search_text=requete, sort_order="newest_first"
            )
        except VintedBlockedError as exc:
            # Vinted demande de ralentir : on s'arrete la, le prochain cycle
            # reprendra la file ou elle en est.
            logger.warning("Chasse de Ma liste : %s", exc)
            bilan["bloque"] = True
            break
        except Exception as exc:
            logger.error("Chasse de Ma liste, recherche « %s » echouee (%s)", requete, exc)
            bilan["erreur"] = str(exc)
            break

        # Le scraper ne leve pas d'erreur quand Vinted ne repond pas : il rend
        # une liste vide et note la raison. Sans ce controle, une panne
        # marquait la carte « cherchee » — on aurait cru qu'il n'y avait rien
        # a vendre. Une recherche ratee n'est pas une recherche : on s'arrete,
        # la carte reste en tete de file pour le prochain cycle.
        panne = getattr(_vinted_scraper, "derniere_erreur", None)
        if not resultats and panne:
            logger.warning("Chasse de Ma liste interrompue : %s", panne)
            bilan["erreur"] = panne
            break

        suivie.derniere_recherche_at = datetime.utcnow()
        bilan["cherchees"] += 1
        connues = _existing_by_external_id(db, SourcePlatform.VINTED,
                                           [item.item_id for item in resultats])
        for item in resultats:
            existante = connues.get(item.item_id)
            if existante:
                existante.last_seen_at = datetime.utcnow()
                continue
            annonce = _nouvelle_annonce_vinted(item)
            db.add(annonce)
            db.commit()
            _score_listing(db, annonce)
            _maybe_notify(db, annonce)
            bilan["nouvelles"] += 1
        db.commit()
    if bilan["cherchees"]:
        logger.info("Chasse de Ma liste : %d carte(s) cherchee(s), %d annonce(s) nouvelle(s)",
                    bilan["cherchees"], bilan["nouvelles"])
    if bilan["cherchees"] or bilan.get("erreur") or bilan["bloque"]:
        DERNIERE_CHASSE.clear()
        DERNIERE_CHASSE.update(bilan, fin_at=datetime.utcnow().isoformat())
    return bilan


def chasser_en_arriere_plan(cle: Optional[tuple] = None, par_cycle: int = 1) -> None:
    """Lance la chasse sans faire attendre la page : une recherche Vinted
    prend plusieurs secondes par carte, delai de politesse compris."""
    import threading

    from app.database import SessionLocal

    def tache():
        db = SessionLocal()
        try:
            chasser_ma_liste(db, par_cycle=par_cycle, cle=cle)
        except Exception as exc:
            db.rollback()
            logger.error("Chasse de Ma liste en arriere-plan echouee (%s)", exc)
        finally:
            db.close()

    threading.Thread(target=tache, name="chasse-ma-liste", daemon=True).start()


def run_targeted_search(db: Session, query: str, limit: int = 60, on_progress=None) -> list:
    """
    Recherche A LA DEMANDE sur un terme precis (ex: "Luffy", "Zoro
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
            vinted_results = _vinted_scraper.search_card_listings(
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
            listing = _nouvelle_annonce_vinted(item)
            db.add(listing)
            db.commit()
            _score_listing(db, listing)
            _maybe_notify(db, listing)

    if settings.ebay_client_id and settings.ebay_client_secret:
        progress("Recherche sur eBay…")
        try:
            client = EbayBrowseClient(
                client_id=settings.ebay_client_id,
                client_secret=settings.ebay_client_secret,
                marketplace_id=settings.ebay_marketplace_id,
                use_sandbox=settings.ebay_use_sandbox,
            )
            ebay_results = client.search_card_listings(keywords=f"{settings.tcg_nom} carte {query}")
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
            _maybe_notify(db, listing)

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
    # Les annonces notees avant le cout reel et le mode collection
    # (contrefacons, lots, cartes gradees, etat, frais Vinted, economie) :
    # sans ce repassage, une contrefacon deja en tete du radar y serait
    # restee. Une fois renotee, elle a une economie calculee et sort de la
    # file d'elle-meme.
    condition = condition | Listing.savings_eur.is_(None)

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
        if listing.manual_reviewed_at:
            continue  # l'utilisateur a tranche lui-meme sur cette annonce
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



# « Trop beau pour etre vrai » : une carte cotee au moins SEUIL_ALERTE_COTE,
# demandee a moins de PART_ALERTE_COTE de sa cote ajustee a son etat. En dessous
# de ce seuil de cote, un ecart de quelques euros ne dit rien.
SEUIL_ALERTE_COTE = 15.0
PART_ALERTE_COTE = 0.25

# Part de l'echantillon qui doit repondre avec LE MEME format pour qu'on
# l'etende au reste. Trois sur quatre : assez pour qu'un format faux soit
# ecarte (il echouerait presque partout), pas au point d'exiger que chaque
# carte existe — certaines n'ont simplement pas d'illustration publiee.
SEUIL_DEDUCTION = 0.75
TAILLE_ECHANTILLON = 8


def _repartis(liste: list, nombre: int) -> list:
    """`nombre` elements pris a intervalles reguliers, pas les premiers.

    Les premiers d'une liste triee par code sont tous de la meme serie : un
    echantillon fait d'eux ne dirait rien des autres series, qui peuvent
    etre servies differemment.
    """
    if nombre <= 0:
        return []
    if nombre >= len(liste):
        return list(liste)
    pas = len(liste) / nombre
    return [liste[int(i * pas)] for i in range(nombre)]


def deduire_visuels(db: Session, taille_echantillon: int = TAILLE_ECHANTILLON,
                    client: Optional[ClientImagesCartes] = None) -> dict:
    """Pose en quelques secondes les visuels qui se deduisent du code.

    POURQUOI
    --------
    L'adresse d'une illustration se deduit du code de la carte. La verifier
    carte par carte, avec la pause qu'on doit a un site qu'on interroge,
    prenait de dix a quarante minutes pour les cartes anglaises — pendant
    lesquelles le catalogue restait gris.

    COMMENT, SANS POSER D'ADRESSE FAUSSE A L'AVEUGLE
    ------------------------------------------------
    On verifie un ECHANTILLON reparti — series differentes, et quelques
    illustrations alternatives pour eprouver aussi leur suffixe. Si au
    moins trois sur quatre repondent avec le meme format, ce format est
    etendu a toutes les autres d'un coup. Sinon on ne deduit rien, et la
    verification carte par carte reste la seule voie.

    Les adresses ainsi posees sont MARQUEES « deduites ». Le travail de fond
    les verifie ensuite une a une (verifier_visuels_deduits) et retire
    celles que le site refuse, qui repassent alors par la recherche
    complete. Et l'interface affiche un repli propre pour une image qui ne
    charge pas : une deduction fausse coute une case « visuel indisponible »
    le temps qu'elle soit corrigee, pas un cadre casse.

    Les cartes du jeu francais et les autres forment deux groupes distincts,
    eprouves separement : elles ne sont pas servies par le meme site.
    """
    from collections import Counter

    from app.collectors.cardlist_fr import rang_de_parallele
    from app.core.langues import FRANCAIS

    cartes = (
        db.query(MarketCardPrice)
        .filter(MarketCardPrice.image_url.is_(None))
        .filter(MarketCardPrice.card_code.isnot(None))
        .filter(MarketCardPrice.card_code != "")
        .order_by(MarketCardPrice.card_code)
        .all()
    )
    client = client or ClientImagesCartes()
    maintenant = datetime.utcnow()
    groupes = []

    for anglais in (False, True):
        membres = [c for c in cartes if (c.language != FRANCAIS) == anglais]
        if not membres:
            continue

        ordinaires = [c for c in membres if rang_de_parallele(c.name_slug) == 0]
        variantes = [c for c in membres if rang_de_parallele(c.name_slug) > 0]
        part_variantes = min(len(variantes), max(1, taille_echantillon // 4)) if variantes else 0
        echantillon = (_repartis(ordinaires, taille_echantillon - part_variantes)
                       + _repartis(variantes, part_variantes))

        formats = Counter()
        for carte in echantillon:
            image = client.chercher_image(carte.display_name, carte.card_code,
                                          rang=rang_de_parallele(carte.name_slug),
                                          anglais=anglais)
            carte.image_checked_at = maintenant
            if image is not None:
                carte.image_url = image.image_url
                carte.image_source = image.source
                formats[(image.source, image.image_url.rsplit(".", 1)[-1])] += 1

        (source, extension), retenus = (formats.most_common(1)[0]
                                        if formats else ((None, None), 0))
        etabli = bool(echantillon) and retenus / len(echantillon) >= SEUIL_DEDUCTION
        base = base_de_source(source) if etabli else None

        deduites = 0
        if base:
            deja_vues = {id(c) for c in echantillon}
            for carte in membres:
                if id(carte) in deja_vues or carte.image_url:
                    continue
                code = code_canonique(carte.card_code)
                suffixe = suffixe_de_rang(rang_de_parallele(carte.name_slug))
                if not code or suffixe is None:
                    continue
                carte.image_url = f"{base}/{code}{suffixe}.{extension}"
                carte.image_source = f"{source}{MARQUE_DEDUITE}"
                carte.image_checked_at = maintenant
                deduites += 1

        groupes.append({
            "groupe": "absentes du jeu francais" if anglais else "jeu francais",
            "cartes": len(membres),
            "echantillon": len(echantillon),
            "echantillon_servi": sum(formats.values()),
            "format": f"{source} .{extension}" if source else None,
            "format_etabli": etabli,
            "deduites": deduites,
        })

    db.commit()
    for g in groupes:
        logger.info("Visuels deduits (%s) : echantillon %d/%d, format %s, %d deduit(s)",
                    g["groupe"], g["echantillon_servi"], g["echantillon"],
                    g["format"] if g["format_etabli"] else "non etabli", g["deduites"])
    return {
        "groupes": groupes,
        "deduites": sum(g["deduites"] for g in groupes),
        "verifiees": sum(g["echantillon_servi"] for g in groupes),
        # Comme pour l'enrichissement : distinguer « le site ne repond pas »
        # de « le site repond sans image ».
        "network_errors": client.erreurs_reseau,
        "http_responses": client.reponses_http,
    }


def verifier_visuels_deduits(db: Session, limit: int = 150,
                             client: Optional[ClientImagesCartes] = None) -> dict:
    """Verifie, en arriere-plan, les adresses posees par deduction.

    Une adresse confirmee perd sa marque. Une adresse que le site REFUSE est
    retiree : la carte repasse alors par la recherche complete, qui essaie
    les autres formats et l'autre site. Une simple absence de reponse ne
    retire RIEN — sinon une coupure de quelques minutes viderait le
    catalogue de ses visuels.
    """
    cartes = (
        db.query(MarketCardPrice)
        .filter(MarketCardPrice.image_source.like(f"%{MARQUE_DEDUITE}"))
        .order_by(MarketCardPrice.image_checked_at.asc().nullsfirst())
        .limit(limit)
        .all()
    )
    if not cartes:
        return {"examined": 0, "confirmed": 0, "removed": 0, "unknown": 0}

    client = client or ClientImagesCartes()
    confirmees, retirees, inconnues = 0, 0, 0
    for carte in cartes:
        verdict = client.verifier(carte.image_url)
        carte.image_checked_at = datetime.utcnow()
        if verdict is True:
            carte.image_source = carte.image_source.replace(MARQUE_DEDUITE, "")
            confirmees += 1
        elif verdict is False:
            carte.image_url = None
            carte.image_source = None
            # Remise en tete de file : elle doit etre recherchee pour de bon,
            # pas attendre derriere des milliers de cartes deja examinees.
            carte.image_checked_at = None
            retirees += 1
        else:
            inconnues += 1
    db.commit()
    logger.info("Visuels deduits : %d confirme(s), %d retire(s), %d sans reponse",
                confirmees, retirees, inconnues)
    return {"examined": len(cartes), "confirmed": confirmees,
            "removed": retirees, "unknown": inconnues}

def enrich_card_images(db: Session, limit: int = 40) -> dict:
    """Complete progressivement le visuel des cartes du catalogue.

    Progressif et non bloquant, pour la meme raison que la synchronisation
    ZebraDex : quelques dizaines de cartes par passage plutot qu'un gros job
    qui depasserait les limites d'un hebergement gratuit. Le catalogue
    compte des milliers de cartes, les images se remplissent sur plusieurs
    cycles.

    `image_checked_at` est renseigne MEME quand aucune image n'est trouvee.
    Sans ca, les cartes introuvables seraient reinterrogees a chaque
    passage et bloqueraient la file : les memes echecs pour toujours, et
    aucune nouvelle carte servie.

    Les cartes SANS code sont ecartees de la file. L'adresse de
    l'illustration se deduit du code et de rien d'autre (voir
    collectors/card_images.py) : les garder reviendrait a leur reserver des
    places dans un lot de taille fixe pour un echec garanti, au detriment
    des cartes qu'on peut reellement servir.
    """
    cartes = (
        db.query(MarketCardPrice)
        .filter(MarketCardPrice.image_url.is_(None))
        .filter(MarketCardPrice.card_code.isnot(None))
        .filter(MarketCardPrice.card_code != "")
        .order_by(MarketCardPrice.image_checked_at.asc().nullsfirst(),
                  MarketCardPrice.price_eur.desc())
        .limit(limit)
        .all()
    )

    if not cartes:
        return {"examined": 0, "found": 0, "not_found": 0, "found_en": 0,
                "network_errors": 0, "http_responses": 0}

    from app.collectors.cardlist_fr import rang_de_parallele
    from app.core.langues import FRANCAIS

    client = ClientImagesCartes()
    trouvees, introuvables, anglaises = 0, 0, 0

    for carte in cartes:
        try:
            # Ce que la fiche SAIT d'elle-meme : quelle illustration elle
            # porte, et si elle existe dans le jeu francais. Sans le premier,
            # la fiche du second parallele pouvait recevoir l'image du
            # premier ; sans le second, une carte qui n'existe qu'en anglais
            # etait cherchee sur le site francais, ou elle ne pouvait pas
            # etre — c'est ce qui laissait des centaines de fiches sans
            # visuel.
            image = client.chercher_image(
                carte.display_name, carte.card_code,
                rang=rang_de_parallele(carte.name_slug),
                anglais=carte.language != FRANCAIS)
        except Exception as exc:  # noqa: BLE001 - une source distante ne doit pas casser le cycle
            logger.warning("Images: recherche echouee pour '%s' (%s)",
                           carte.display_name, exc)
            image = None

        carte.image_checked_at = datetime.utcnow()
        if image is not None:
            carte.image_url = image.image_url
            carte.image_source = image.source
            trouvees += 1
            if image.source == SOURCE_EN:
                anglaises += 1
        else:
            introuvables += 1

    db.commit()
    logger.info(
        "Images: %d carte(s) examinee(s), %d visuel(s) trouve(s) dont %d sur le "
        "site anglais, %d sans image, %d erreur(s) reseau",
        len(cartes), trouvees, anglaises, introuvables, client.erreurs_reseau,
    )
    return {
        "examined": len(cartes), "found": trouvees, "not_found": introuvables,
        "found_en": anglaises,
        # Pour que l'appelant puisse dire VRAI : sans reponse du tout, la
        # source est injoignable ; avec des reponses mais sans image, elle
        # est joignable et n'a simplement pas ces illustrations. Ce ne sont
        # pas les memes conclusions, et pas les memes remedes.
        "network_errors": client.erreurs_reseau,
        "http_responses": client.reponses_http,
    }


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
        chasser_ma_liste(db)
    except Exception as exc:
        db.rollback()
        logger.error("Chasse de Ma liste echouee (%s)", exc)

    # NB (22/10/2026) : la synchronisation ZebraDex a ete retiree d'ici.
    # Cette source ne couvre pas One Piece — c'est le constat qui a fait
    # changer de sources — donc elle interrogeait un site pour rien a
    # chaque cycle, et noyait les journaux sous ses echecs.
    #
    # Les prix de reference viennent desormais d'OPECards, et ils se
    # rafraichissent une fois par nuit (voir scheduler._job_sources_du_jour)
    # plutot qu'ici : des centaines de pages toutes les vingt minutes
    # marteleraient un site communautaire pour des prix qui ne bougent pas
    # a ce rythme. Le cycle rapide reste ce qu'il doit etre — collecter les
    # annonces, et les rescorer des que l'index change.

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
