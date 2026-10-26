from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import CarteSuivie, MarketCardPrice
from app.schemas import SuiviUpdate
from app.services import suivi

router = APIRouter(prefix="/api/suivi", tags=["suivi"])

# « Chercher maintenant » sur toute la liste : au-dela, la rafale de
# recherches ferait bloquer Vinted ; le cycle de fond prend le relais.
CARTES_CHERCHEES_A_LA_DEMANDE = 10


@router.get("")
def lister_les_cartes_suivies(db: Session = Depends(get_db)):
    """« Ma liste » : chaque carte suivie, son budget, et ce qui est en vente
    — les cartes qui ont une annonce dans le budget en tete."""
    return suivi.lister(db)


@router.get("/etat")
def etat_de_la_derniere_chasse():
    """Bilan de la derniere recherche Vinted des cartes de la liste : combien
    de cartes cherchees, d'annonces nouvelles, et l'erreur s'il y en a eu."""
    from app.pipeline import DERNIERE_CHASSE

    return DERNIERE_CHASSE or {"fin_at": None}


@router.post("/chercher")
def chercher_maintenant(db: Session = Depends(get_db)):
    """Lance tout de suite la recherche Vinted des cartes de la liste, en
    arriere-plan. Les resultats apparaissent dans la liste au fil des
    recherches (quelques secondes par carte)."""
    from app.pipeline import chasser_en_arriere_plan  # local : pipeline est lourd

    if not settings.vinted_enabled:
        raise HTTPException(status_code=409, detail="La collecte Vinted est désactivée (VINTED_ENABLED).")
    nombre = min(db.query(CarteSuivie).count(), CARTES_CHERCHEES_A_LA_DEMANDE)
    if nombre:
        chasser_en_arriere_plan(par_cycle=nombre)
    return {"status": "lancee" if nombre else "liste vide", "cartes": nombre}


@router.put("/{card_id}")
def suivre_une_carte(card_id: int, corps: SuiviUpdate, db: Session = Depends(get_db)):
    """Ajoute la carte a la liste, ou change son budget (cout reel maximum,
    protection et port compris ; vide = la suivre sans budget). Une carte
    tout juste ajoutee est cherchee sur Vinted aussitot, sans attendre le
    prochain cycle."""
    carte = db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()
    nouvelle = carte is not None and suivi.etat_de_la_carte(db, carte) is None
    entree = suivi.suivre(db, card_id, corps.prix_max)
    if entree is None:
        raise HTTPException(status_code=404, detail="Carte introuvable.")
    if nouvelle and settings.vinted_enabled:
        from app.pipeline import chasser_en_arriere_plan

        chasser_en_arriere_plan(cle=(carte.card_code, carte.name_slug))
    return entree


@router.delete("/{card_id}")
def ne_plus_suivre_une_carte(card_id: int, db: Session = Depends(get_db)):
    if not suivi.ne_plus_suivre(db, card_id):
        raise HTTPException(status_code=404, detail="Cette carte n'est pas dans ta liste.")
    return {"status": "ok"}
