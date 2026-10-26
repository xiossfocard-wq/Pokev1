from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ExemplaireAjout
from app.services import collection

router = APIRouter(prefix="/api/collection", tags=["collection"])


@router.get("")
def lister_la_collection(db: Session = Depends(get_db)):
    """« Ma collection » : chaque carte possedee, ses exemplaires (prix paye,
    etat, valeur estimee), et les totaux."""
    return collection.lister(db)


@router.post("")
def ajouter_un_exemplaire(corps: ExemplaireAjout, db: Session = Depends(get_db)):
    """Range un exemplaire. Avec `listing_id` (« je l'ai achetee » sur le
    radar), la carte, le prix paye et l'etat sont repris de l'annonce."""
    if corps.card_id is None and corps.listing_id is None:
        raise HTTPException(status_code=400, detail="Indique la carte (card_id) ou l'annonce (listing_id).")
    etat = collection.ajouter(db, card_id=corps.card_id, listing_id=corps.listing_id,
                              prix_paye=corps.prix_paye, etat=corps.etat)
    if etat is None:
        raise HTTPException(
            status_code=404,
            detail="Carte introuvable, ou annonce dont la carte n'a pas été reconnue.",
        )
    return etat


@router.delete("/{exemplaire_id}")
def retirer_un_exemplaire(exemplaire_id: int, db: Session = Depends(get_db)):
    if not collection.retirer(db, exemplaire_id):
        raise HTTPException(status_code=404, detail="Exemplaire introuvable.")
    return {"status": "ok"}
