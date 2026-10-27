from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import personnages

router = APIRouter(prefix="/api/personnages", tags=["personnages"])


@router.get("")
def les_personnages(toutes_langues: bool = Query(False), db: Session = Depends(get_db)):
    """Les personnages appréciés — icônes de la série et personnages très
    recherchés — qui ont des cartes au catalogue, et par qui commencer une
    collection sympa sans se ruiner."""
    liste = personnages.liste_des_personnages(db, toutes_langues=toutes_langues)
    return {"personnages": liste, "par_qui_commencer": personnages.par_qui_commencer(liste)}


@router.get("/mes-cartes")
def les_cartes_de_mes_personnages(db: Session = Depends(get_db)):
    """Les personnages de tes goûts et les fiches de toutes leurs cartes :
    le radar s'en sert pour ne montrer que leurs annonces."""
    return personnages.cartes_de_mes_personnages(db)


@router.get("/{slug}")
def un_personnage(slug: str, toutes_langues: bool = Query(False), db: Session = Depends(get_db)):
    """Toutes les cartes d'un personnage, de la plus accessible à la plus rare,
    et les conseils pour en commencer ou en compléter la collection."""
    page = personnages.page_du_personnage(db, slug, toutes_langues=toutes_langues)
    if page is None:
        raise HTTPException(status_code=404, detail="Pas de page pour ce personnage.")
    return page


class Chasse(BaseModel):
    budget_max: float = Field(gt=0, le=100000)
    toutes_langues: bool = False


@router.post("/{slug}/chasse")
def chasser(slug: str, chasse: Chasse, db: Session = Depends(get_db)):
    """Ajoute à Ma liste toutes ses belles versions manquantes dans le budget,
    chacune avec sa cote comme budget : la chasse Vinted les cherchera."""
    resultat = personnages.chasser_les_belles_versions(db, slug, chasse.budget_max,
                                                      toutes_langues=chasse.toutes_langues)
    if resultat is None:
        raise HTTPException(status_code=404, detail="Pas de page pour ce personnage.")
    return resultat
