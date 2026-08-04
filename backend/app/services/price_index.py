"""
Construction et interrogation de l'index local de prix de reference.

Deux responsabilites :
1. SYNCHRONISATION (`sync_series_batch`) : remplit `market_card_prices`
   depuis ZebraDex, de facon PROGRESSIVE. Les 169 series ne sont pas
   telechargees d'un coup (ce serait ~17 min de requetes a 6s d'intervalle,
   incompatible avec un hebergement gratuit et peu respectueux du site) :
   on synchronise `batch_size` series par cycle, en priorisant celles
   jamais vues puis les plus anciennes. Avec un cycle toutes les 20 min et
   un batch de 6, l'index complet est construit en ~10h puis rafraichi en
   continu. Le dashboard reste utilisable pendant la construction : les
   series deja synchronisees servent immediatement.

2. MATCHING (`find_price_for_listing`) : retrouve le prix d'une annonce a
   partir de son titre. Strategie a plusieurs niveaux, du plus fiable au
   moins fiable, car un titre Vinted est souvent approximatif :
     a. code carte exact present dans le titre (ex "PAF 232") -> tres fiable
     b. numero de set (ex "4/102" ou "232/193") + nom -> fiable
     c. nom de carte seul, avec desambiguisation par prix median si
        plusieurs series contiennent une carte du meme nom -> moyennement
        fiable, d'ou le champ `match_confidence` renvoye et affiche dans
        l'UI pour que l'utilisateur sache a quel point se fier au chiffre.
"""
import logging


from datetime import datetime
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.collectors.zebradex_prices import ZebraDexClient
from app.matching.title_parser import (
    extract_card_codes, extract_name_candidates, extract_set_number,
)
from app.models import MarketCardPrice, ZebraDexSeriesState

logger = logging.getLogger(__name__)

_client = ZebraDexClient()

# --------------------------------------------------------------------------
# Synchronisation
# --------------------------------------------------------------------------

def refresh_series_catalog(db: Session) -> int:
    """Decouvre/actualise la liste des series (aucune config manuelle)."""
    series_list = _client.discover_series()
    if not series_list:
        logger.warning("ZebraDex: catalogue de series vide, rien a mettre a jour")
        return 0

    added = 0
    for s in series_list:
        existing = db.query(ZebraDexSeriesState).filter_by(series_id=s.series_id).first()
        if existing:
            existing.name, existing.code, existing.bloc, existing.url = s.name, s.code, s.bloc, s.url
        else:
            db.add(ZebraDexSeriesState(
                series_id=s.series_id, name=s.name, code=s.code, bloc=s.bloc, url=s.url,
            ))
            added += 1
    db.commit()
    logger.info("ZebraDex: %d series au catalogue (%d nouvelles)", len(series_list), added)
    return added


def sync_series_batch(db: Session, batch_size: int = 6) -> dict:
    """
    Synchronise `batch_size` series : d'abord celles jamais synchronisees,
    puis les plus anciennes. Retourne un resume pour les logs / l'API admin.
    """
    if db.query(ZebraDexSeriesState).count() == 0:
        refresh_series_catalog(db)

    pending = (
        db.query(ZebraDexSeriesState)
        .order_by(ZebraDexSeriesState.last_synced_at.asc().nullsfirst())
        .limit(batch_size)
        .all()
    )

    synced, total_cards = 0, 0
    for series in pending:
        cards = _client.fetch_series_cards(series.url, series_name=series.name)
        if not cards:
            series.last_error = "0 carte extraite"
            series.last_synced_at = datetime.utcnow()
            db.commit()
            continue

        for card in cards:
            _upsert_card_price(db, card)
        series.card_count = len(cards)
        series.last_synced_at = datetime.utcnow()
        series.last_error = None
        db.commit()
        synced += 1
        total_cards += len(cards)
        logger.info("ZebraDex: %s synchronisee (%d cartes)", series.name, len(cards))

    remaining = db.query(ZebraDexSeriesState).filter(
        ZebraDexSeriesState.last_synced_at.is_(None)
    ).count()
    return {
        "series_synced": synced,
        "cards_upserted": total_cards,
        "series_never_synced_remaining": remaining,
        "total_prices_in_index": db.query(MarketCardPrice).count(),
    }


def _upsert_card_price(db: Session, card) -> None:
    existing = (
        db.query(MarketCardPrice)
        .filter_by(card_code=card.card_code, name_slug=card.name_slug)
        .first()
    )
    values = dict(
        display_name=card.name,
        series_name=card.series_name,
        rarity=card.rarity,
        price_eur=card.price_eur,
        price_low_eur=card.price_low,
        price_high_eur=card.price_high,
        variation_7d_eur=card.variation_7d_eur,
        source="zebradex",
        updated_at=datetime.utcnow(),
    )
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(MarketCardPrice(
            card_code=card.card_code, name_slug=card.name_slug, **values
        ))


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

class PriceMatch:
    def __init__(self, row: MarketCardPrice, confidence: str, reason: str):
        self.row = row
        self.confidence = confidence  # "high" | "medium" | "low"
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "price_eur": self.row.price_eur,
            "price_low_eur": self.row.price_low_eur,
            "price_high_eur": self.row.price_high_eur,
            "variation_7d_eur": self.row.variation_7d_eur,
            "rarity": self.row.rarity,
            "series_name": self.row.series_name,
            "matched_card": self.row.display_name,
            "matched_code": self.row.card_code,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.row.source,
        }


def find_price_for_listing(db: Session, title: str, description: str = "") -> Optional[PriceMatch]:
    text = f"{title or ''} {description or ''}"

    # (a) Code carte explicite (le plus fiable)
    for candidate in extract_card_codes(text):
        row = db.query(MarketCardPrice).filter(
            func.upper(MarketCardPrice.card_code) == candidate
        ).first()
        if row:
            return PriceMatch(row, "high", f"code carte {candidate} trouve dans le titre")

    name_candidates = extract_name_candidates(text)
    set_number = extract_set_number(text)

    # (b) Numero de set + nom de carte
    if set_number and name_candidates:
        number = set_number[0]
        for name in name_candidates:
            rows = db.query(MarketCardPrice).filter(
                MarketCardPrice.name_slug == name,
                MarketCardPrice.card_code.like(f"%{number}"),
            ).all()
            if len(rows) == 1:
                return PriceMatch(rows[0], "high", f"nom '{name}' + numero {number}")
            if rows:
                return PriceMatch(
                    _median_row(rows), "medium",
                    f"nom '{name}' + numero {number} ({len(rows)} correspondances)",
                )

    # (c) Nom seul
    for name in name_candidates:
        rows = db.query(MarketCardPrice).filter(MarketCardPrice.name_slug == name).all()
        if not rows:
            continue
        if len(rows) == 1:
            return PriceMatch(rows[0], "medium", f"nom '{name}' (unique dans l'index)")
        return PriceMatch(
            _median_row(rows), "low",
            f"nom '{name}' present dans {len(rows)} series - prix median retenu",
        )

    return None


def _median_row(rows: List[MarketCardPrice]) -> MarketCardPrice:
    ordered = sorted(rows, key=lambda r: r.price_eur)
    return ordered[len(ordered) // 2]


def index_stats(db: Session) -> dict:
    total_series = db.query(ZebraDexSeriesState).count()
    synced = db.query(ZebraDexSeriesState).filter(
        ZebraDexSeriesState.last_synced_at.isnot(None)
    ).count()
    return {
        "series_known": total_series,
        "series_synced": synced,
        "series_pending": total_series - synced,
        "cards_in_index": db.query(MarketCardPrice).count(),
        "progress_percent": round(100 * synced / total_series, 1) if total_series else 0.0,
    }
