from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Listing, SourcePlatform, ListingStatus
from app.schemas import ListingOut

router = APIRouter(prefix="/api/listings", tags=["listings"])

SORTABLE_FIELDS = {
    "deal_score": Listing.deal_score,
    "margin_net": Listing.margin_net,
    "first_seen_at": Listing.first_seen_at,
    "price": Listing.price,
}


@router.get("", response_model=list[ListingOut])
def list_listings(
    source: Optional[str] = Query(None, description="ebay | vinted"),
    sort_by: str = Query("deal_score"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    min_score: Optional[float] = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    # Exclut seulement les exclusions délibérées (IGNORED, ex: langue non
    # française). Les annonces sans prix de référence trouvé (NO_PRICE_MATCH)
    # restent visibles délibérément : l'utilisateur veut pouvoir les comparer
    # manuellement au marché même sans marge calculée automatiquement.
    query = db.query(Listing).filter(Listing.status != ListingStatus.IGNORED)

    if source:
        try:
            query = query.filter(Listing.source == SourcePlatform(source))
        except ValueError:
            pass

    if min_score is not None:
        # Un min_score explicite exclut de fait les annonces sans score
        # (NULL) — comportement voulu si l'utilisateur filtre par score.
        query = query.filter(Listing.deal_score >= min_score)

    sort_column = SORTABLE_FIELDS.get(sort_by, Listing.deal_score)
    # nullslast() dans les deux sens de tri : sans ça, Postgres remonte les
    # valeurs NULL en premier en tri désc (comportement par défaut), ce qui
    # noierait les vraies bonnes affaires sous les annonces sans score.
    sort_column = nullslast(sort_column.desc() if order == "desc" else sort_column.asc())
    query = query.order_by(sort_column)

    return query.limit(limit).all()


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    return db.query(Listing).filter(Listing.id == listing_id).first()
