from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import nullslast
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import Listing, SourcePlatform, ListingStatus
from app.schemas import ListingOut
from app.pipeline import run_targeted_search
from app.services import search_jobs

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
    # Un id inexistant renvoyait None, ce que FastAPI transformait en
    # erreur 500 illisible : on rend un vrai 404.
    row = db.query(Listing).filter(Listing.id == listing_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    return row


def _run_search_job(job: search_jobs.SearchJob):
    """Corps de la recherche, execute dans un thread de fond. Il ouvre sa
    PROPRE session SQLAlchemy : celle de la requete HTTP est deja fermee
    quand ce code tourne."""
    db = SessionLocal()
    try:
        results = run_targeted_search(
            db, query=job.query, on_progress=lambda msg: setattr(job, "message", msg)
        )
        job.listing_ids = [row.id for row in results]
    finally:
        db.close()


@router.post("/search")
def start_search(
    q: str = Query(..., min_length=2, description="ex: Pikachu, Dracaufeu ex, PAF 232"),
):
    """Demarre une recherche ciblee et rend IMMEDIATEMENT un identifiant de
    job. Ne fait volontairement PAS le travail dans cette requete : la
    recherche prend 1 a 5 minutes (Vinted + eBay en direct puis scoring de
    chaque annonce), bien au-dela de ce qu'un navigateur accepte d'attendre.
    Voir app/services/search_jobs.py pour le detail du raisonnement.

    Suivre l'avancement avec GET /api/listings/search/{job_id}.
    """
    job = search_jobs.store.submit(q, _run_search_job)
    return job.to_dict()


@router.get("/search/{job_id}")
def get_search_result(job_id: str, db: Session = Depends(get_db)):
    """Etat d'une recherche ciblee. Tant que `status` vaut "pending" ou
    "running", `listings` est vide et le frontend doit reinterroger. A
    "done", `listings` contient le resultat complet."""
    job = search_jobs.store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Recherche inconnue ou expiree (les resultats sont gardes "
                "30 min, et sont perdus si le serveur redemarre). Relance "
                "la recherche."
            ),
        )

    payload = job.to_dict()
    payload["listings"] = []

    if job.status == search_jobs.STATUS_DONE and job.listing_ids:
        rows = (
            db.query(Listing)
            .filter(Listing.id.in_(job.listing_ids))
            .filter(Listing.status != ListingStatus.IGNORED)
            .order_by(nullslast(Listing.deal_score.desc()))
            .all()
        )
        payload["listings"] = [ListingOut.model_validate(row).model_dump(mode="json") for row in rows]
        payload["result_count"] = len(rows)

    return payload
