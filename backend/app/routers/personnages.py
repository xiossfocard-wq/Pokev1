from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import personnages

router = APIRouter(prefix="/api/personnages", tags=["personnages"])


@router.get("")
def les_personnages(toutes_langues: bool = Query(False), db: Session = Depends(get_db)):
    """Les personnages appréciés — icônes de la série et personnages très
    recherchés — qui ont des cartes au catalogue."""
    return personnages.liste_des_personnages(db, toutes_langues=toutes_langues)


@router.get("/{slug}")
def un_personnage(slug: str, toutes_langues: bool = Query(False), db: Session = Depends(get_db)):
    """Toutes les cartes d'un personnage, de la plus accessible à la plus rare,
    et les conseils pour en commencer ou en compléter la collection."""
    page = personnages.page_du_personnage(db, slug, toutes_langues=toutes_langues)
    if page is None:
        raise HTTPException(status_code=404, detail="Pas de page pour ce personnage.")
    return page
