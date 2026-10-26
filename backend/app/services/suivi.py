"""
« Ma liste » : les cartes que l'utilisateur cherche, et son budget pour chacune.

Un collectionneur ne chasse pas « une bonne affaire » en general : il chasse
SA carte, a SON prix. Ce module dit, pour chaque carte suivie, ce qui est en
vente en ce moment et a quel cout reel, et, pour chaque annonce, si elle
tombe dans le budget — ce qui declenche une alerte quel que soit son score.

Le budget se compare au cout REEL de l'achat (protection acheteur et port
compris) : un budget de 60 EUR veut dire « je suis pret a payer 60 EUR »,
pas « je veux voir 60 EUR sur l'annonce ».
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import CarteSuivie, Listing, MarketCardPrice
from app.services import card_catalog
from app.settings_service import load_app_settings


def cout_de_l_annonce(annonce: Listing) -> float:
    """Le cout reel s'il a ete calcule ; a defaut, article + port affiche."""
    if annonce.purchase_cost_eur is not None:
        return annonce.purchase_cost_eur
    return round((annonce.price or 0.0) + (annonce.shipping_price or 0.0), 2)


def _est_un_lot(annonce: Listing) -> bool:
    """Un lot « dont » la carte n'est pas la carte : son prix est celui de
    tout l'ensemble. Il reste visible dans la liste, mais n'alerte pas."""
    return (annonce.price_detail or {}).get("non_comparable", "").startswith("Lot")


def _suivie(db: Session, carte: MarketCardPrice) -> Optional[CarteSuivie]:
    return (db.query(CarteSuivie)
            .filter(CarteSuivie.card_code == carte.card_code,
                    CarteSuivie.name_slug == carte.name_slug)
            .first())


def _carte(db: Session, card_id: int) -> Optional[MarketCardPrice]:
    return db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()


def etat_de_la_carte(db: Session, carte: MarketCardPrice) -> Optional[dict]:
    """{"prix_max": ...} si la carte est suivie, None sinon."""
    suivie = _suivie(db, carte)
    return {"prix_max": suivie.prix_max} if suivie else None


def suivre(db: Session, card_id: int, prix_max: Optional[float]) -> Optional[dict]:
    """Ajoute la carte a la liste, ou change son budget. None si la carte
    n'existe pas."""
    carte = _carte(db, card_id)
    if carte is None:
        return None
    suivie = _suivie(db, carte)
    if suivie is None:
        suivie = CarteSuivie(card_code=carte.card_code, name_slug=carte.name_slug,
                             created_at=datetime.utcnow())
        db.add(suivie)
    suivie.prix_max = prix_max
    db.commit()
    return _entree(db, suivie, carte)


def ne_plus_suivre(db: Session, card_id: int) -> bool:
    carte = _carte(db, card_id)
    suivie = _suivie(db, carte) if carte is not None else None
    if suivie is None:
        return False
    db.delete(suivie)
    db.commit()
    return True


def budget_pour_annonce(db: Session, annonce: Listing) -> Optional[dict]:
    """Si l'annonce porte sur une carte suivie : son budget, et si elle y
    tombe. None si la carte n'est pas suivie (ou pas identifiee)."""
    if not annonce.matched_card_id:
        return None
    carte = _carte(db, annonce.matched_card_id)
    if carte is None:
        return None
    suivie = _suivie(db, carte)
    if suivie is None:
        return None
    dans_le_budget = (suivie.prix_max is not None
                      and cout_de_l_annonce(annonce) <= suivie.prix_max
                      and not _est_un_lot(annonce))
    return {"prix_max": suivie.prix_max, "dans_le_budget": dans_le_budget}


def _entree(db: Session, suivie: CarteSuivie, carte: Optional[MarketCardPrice]) -> dict:
    """Une ligne de la liste : la carte, le budget, et ce qui est en vente."""
    base = {
        "card_code": suivie.card_code,
        "name_slug": suivie.name_slug,
        "prix_max": suivie.prix_max,
        "suivie_depuis": suivie.created_at.isoformat() if suivie.created_at else None,
    }
    if carte is None:
        # La carte a disparu du catalogue (base reconstruite sans elle) : on
        # le dit, au lieu de faire disparaitre la ligne en silence.
        return {**base, "id": None, "introuvable": True, "annonces": None}

    seuil = load_app_settings(db).get("min_listing_price") or 0.0
    requete = db.query(Listing).filter(Listing.matched_card_id == carte.id)
    annonces = card_catalog._annonces_visibles(requete, seuil).all()
    triees = sorted(annonces, key=cout_de_l_annonce)
    dans_le_budget = [a for a in triees
                      if suivie.prix_max is not None and not _est_un_lot(a)
                      and cout_de_l_annonce(a) <= suivie.prix_max]
    moins_chere = next((a for a in triees if not _est_un_lot(a)), None)
    return {
        **card_catalog.carte_en_dict(carte),
        **base,
        "introuvable": False,
        "annonces": {
            "nombre": len(annonces),
            "dans_le_budget": len(dans_le_budget),
            "moins_chere": None if moins_chere is None else {
                "id": moins_chere.id,
                "title": moins_chere.title,
                "url": moins_chere.url,
                "source": getattr(moins_chere.source, "value", moins_chere.source),
                "cout_eur": cout_de_l_annonce(moins_chere),
                "price_eur": moins_chere.price,
                "condition_tier": moins_chere.condition_tier,
            },
        },
    }


def lister(db: Session) -> List[dict]:
    """La liste, les cartes qui ont une annonce dans le budget en tete."""
    entrees = []
    for suivie in db.query(CarteSuivie).all():
        carte = (db.query(MarketCardPrice)
                 .filter(MarketCardPrice.card_code == suivie.card_code,
                         MarketCardPrice.name_slug == suivie.name_slug)
                 .first())
        entrees.append(_entree(db, suivie, carte))
    return sorted(entrees, key=lambda e: (
        -((e.get("annonces") or {}).get("dans_le_budget") or 0),
        -((e.get("annonces") or {}).get("nombre") or 0),
        e.get("display_name") or e["name_slug"],
    ))
