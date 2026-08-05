from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Listing, SourcePlatform, ListingStatus
from app.schemas import ListingOut
from app.pipeline import run_targeted_search

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
    query = db.query(Listing).filter(Listing.status != ListingStatus.IGNORED)

    if source:
        try:
            query = query.filter(Listing.source == SourcePlatform(source))
        except ValueError:
            pass

    if min_score is not None:
        query = query.filter(Listing.deal_score >= min_score)

    sort_column = SORTABLE_FIELDS.get(sort_by, Listing.deal_score)
    sort_column = nullslast(sort_column.desc() if order == "desc" else sort_column.asc())
    query = query.order_by(sort_column)

    return query.limit(limit).all()


@router.get("/{listing_id}", response_model=ListingOut)
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    return db.query(Listing).filter(Listing.id == listing_id).first()


@router.post("/search", response_model=list[ListingOut])
def search_listings(
    q: str = Query(..., min_length=2, description="ex: Pikachu, Dracaufeu ex, PAF 232"),
    db: Session = Depends(get_db),
):
    return run_targeted_search(db, query=q)
