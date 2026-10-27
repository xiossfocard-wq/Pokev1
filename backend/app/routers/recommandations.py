from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MarketCardPrice, RecommandationEcartee
from app.schemas import GoutsUpdate
from app.services import recommandations

router = APIRouter(prefix="/api/recommandations", tags=["recommandations"])


@router.get("")
def idees_de_collection(
    budget_max: float = Query(20.0, gt=0, le=10000, description="Cote maximale d'une carte (EUR)"),
    toutes_langues: bool = Query(False, description="Inclure les séries sans version française"),
    db: Session = Depends(get_db),
):
    """Des cartes qu'un connaisseur conseillerait pour une belle collection :
    beau visuel, personnage qui compte, marché favorable, dans le budget —
    chacune avec ses raisons. Des repères, pas des conseils d'investissement."""
    return recommandations.recommander(db, budget_max=budget_max, toutes_langues=toutes_langues)


@router.get("/gouts")
def mes_gouts(db: Session = Depends(get_db)):
    """Les goûts enregistrés, et ce qu'on peut choisir."""
    return {"gouts": recommandations.lire_gouts(db), "options": recommandations.options_de_gouts()}


@router.put("/gouts")
def enregistrer_mes_gouts(corps: GoutsUpdate, db: Session = Depends(get_db)):
    """Personnages, groupes et styles préférés : les idées s'y adaptent, et
    chacun devient un projet de collection suivi."""
    return recommandations.enregistrer_gouts(db, corps.personnages, corps.themes, corps.styles)


@router.post("/ecarter/{card_id}")
def pas_pour_moi(card_id: int, db: Session = Depends(get_db)):
    """« Pas pour moi » : la carte ne revient plus dans les idées."""
    carte = db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()
    if carte is None:
        raise HTTPException(status_code=404, detail="Carte introuvable.")
    deja = (db.query(RecommandationEcartee)
            .filter(RecommandationEcartee.card_code == carte.card_code,
                    RecommandationEcartee.name_slug == carte.name_slug).first())
    if deja is None:
        db.add(RecommandationEcartee(card_code=carte.card_code, name_slug=carte.name_slug,
                                     created_at=datetime.utcnow()))
        db.commit()
    return {"status": "ok"}


@router.delete("/ecartees")
def revoir_les_cartes_ecartees(db: Session = Depends(get_db)):
    """Remet dans les idées toutes les cartes écartées."""
    nombre = db.query(RecommandationEcartee).delete()
    db.commit()
    return {"status": "ok", "remises": nombre}
