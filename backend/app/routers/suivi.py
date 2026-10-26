from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import SuiviUpdate
from app.services import suivi

router = APIRouter(prefix="/api/suivi", tags=["suivi"])


@router.get("")
def lister_les_cartes_suivies(db: Session = Depends(get_db)):
    """« Ma liste » : chaque carte suivie, son budget, et ce qui est en vente
    — les cartes qui ont une annonce dans le budget en tete."""
    return suivi.lister(db)


@router.put("/{card_id}")
def suivre_une_carte(card_id: int, corps: SuiviUpdate, db: Session = Depends(get_db)):
    """Ajoute la carte a la liste, ou change son budget (cout reel maximum,
    protection et port compris ; vide = la suivre sans budget)."""
    entree = suivi.suivre(db, card_id, corps.prix_max)
    if entree is None:
        raise HTTPException(status_code=404, detail="Carte introuvable.")
    return entree


@router.delete("/{card_id}")
def ne_plus_suivre_une_carte(card_id: int, db: Session = Depends(get_db)):
    if not suivi.ne_plus_suivre(db, card_id):
        raise HTTPException(status_code=404, detail="Cette carte n'est pas dans ta liste.")
    return {"status": "ok"}
