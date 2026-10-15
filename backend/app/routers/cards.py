"""
API d'exploration du catalogue de cartes.

Nouvelle direction demandee le 10/10/2026 : chercher dans le CATALOGUE
(quelles cartes existent, a quel prix, dans quel theme, lesquelles montent),
la ou /api/listings part des ANNONCES Vinted/eBay. Les deux cohabitent : on
repere ici une carte qui monte, on la traque ensuite dans les annonces.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MarketCardPrice
from app.services import card_catalog, card_themes
from app.services.card_trends import projection, tendance_historique

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cards", tags=["cards"])

TRIS_ACCEPTES = tuple(card_catalog.TRIS.keys())
TENDANCES_ACCEPTEES = ("hausse", "baisse", "toutes")


@router.get("")
def rechercher(
    q: Optional[str] = Query(None, description="Nom ou code de carte"),
    theme: Optional[str] = Query(None, description="Slug de theme (voir /api/cards/themes)"),
    rarity: Optional[str] = Query(None),
    series: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    trend: str = Query("toutes", description="hausse | baisse | toutes"),
    with_image: Optional[bool] = Query(None),
    with_listings: Optional[bool] = Query(
        None,
        description="true = seulement les cartes ayant au moins une annonce en vente",
    ),
    sort_by: str = Query("prix", description=" | ".join(TRIS_ACCEPTES)),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Recherche filtree dans le catalogue."""
    if theme and card_themes.theme_par_slug(theme) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Thème inconnu : « {theme} ». Valeurs acceptées : "
                f"{', '.join(card_themes.slugs_connus())}."
            ),
        )

    if trend not in TENDANCES_ACCEPTEES:
        raise HTTPException(
            status_code=400,
            detail=f"Tendance inconnue. Valeurs acceptées : {', '.join(TENDANCES_ACCEPTEES)}.",
        )

    if sort_by not in TRIS_ACCEPTES:
        raise HTTPException(
            status_code=400,
            detail=f"Tri inconnu. Valeurs acceptées : {', '.join(TRIS_ACCEPTES)}.",
        )

    # Une fourchette inversee ne rend jamais rien : plutot que de servir une
    # liste vide inexplicable, on dit ce qui cloche.
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(
            status_code=400,
            detail="Le prix minimum est supérieur au prix maximum.",
        )

    return card_catalog.rechercher_cartes(
        db,
        q=q, theme=theme, rarity=rarity, series=series,
        prix_min=price_min, prix_max=price_max,
        tendance=None if trend == "toutes" else trend,
        avec_image=with_image, avec_annonces=with_listings,
        tri=sort_by, ordre=order, limite=limit, decalage=offset,
    )


@router.get("/themes")
def lister_themes(db: Session = Depends(get_db)):
    """Themes disponibles, avec le nombre de cartes et la fourchette de prix
    de chacun — de quoi choisir un theme en connaissance de cause."""
    return {"themes": card_catalog.themes_avec_compteurs(db)}


@router.get("/filters")
def lister_filtres(db: Session = Depends(get_db)):
    """Valeurs reellement presentes en base, pour alimenter l'interface sans
    proposer de filtres qui ne rendraient rien."""
    return card_catalog.valeurs_de_filtres(db)


@router.get("/trending")
def cartes_en_vogue(
    direction: str = Query("hausse", description="hausse | baisse"),
    price_min: Optional[float] = Query(None, ge=0),
    price_max: Optional[float] = Query(None, ge=0),
    theme: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Les plus fortes variations sur 7 jours, en POURCENTAGE.

    Le classement en euros ne dirait que « les cartes cheres bougent de plus
    gros montants ». Les filtres de prix servent justement a cadrer la
    recherche sur un budget.
    """
    if direction not in ("hausse", "baisse"):
        raise HTTPException(
            status_code=400, detail="Direction inconnue : hausse | baisse.",
        )
    if theme and card_themes.theme_par_slug(theme) is None:
        raise HTTPException(status_code=400, detail=f"Thème inconnu : « {theme} ».")

    cartes = card_catalog.cartes_en_vogue(
        db, sens=direction, prix_min=price_min, prix_max=price_max,
        theme=theme, limite=limit,
    )
    return {
        "direction": direction,
        "count": len(cartes),
        "cartes": cartes,
        "source_note": (
            "Variation sur 7 jours publiée par ZebraDex. C'est une donnée de "
            "marché réelle, pas une estimation."
        ),
    }


@router.get("/{card_id}/listings")
def annonces_de_la_carte(card_id: int, limit: int = Query(20, ge=1, le=100),
                         db: Session = Depends(get_db)):
    """Annonces en vente pour cette carte, meilleures affaires d'abord.

    Relie les deux moities de l'app : on repere une carte ici, et on voit
    s'il y a quelque chose a prendre maintenant. Les photos rendues sont
    celles du vendeur, donc de l'exemplaire reel — ce qu'il faut regarder
    avant d'acheter, bien plus qu'une illustration officielle.
    """
    carte = db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()
    if carte is None:
        raise HTTPException(status_code=404, detail="Carte introuvable.")

    annonces = card_catalog.annonces_de_la_carte(db, card_id, limite=limit)
    return {
        "card_id": card_id,
        "display_name": carte.display_name,
        "reference_price_eur": carte.price_eur,
        "count": len(annonces),
        "listings": annonces,
    }


@router.get("/{card_id}")
def detail_carte(card_id: int, horizon_jours: int = Query(30, ge=1, le=365),
                 db: Session = Depends(get_db)):
    """Fiche d'une carte : prix, themes, tendance 7 jours, et tendance de
    fond calculee sur l'historique qu'on constitue nous-memes.

    Tant que l'historique est trop court, `trend_history.fiabilite` vaut
    "insuffisant" et `projection.prix_projete_eur` vaut null. C'est
    volontaire : un prix projete sur deux releves serait un chiffre invente,
    et un chiffre invente affiche a cote de vrais prix est pris pour un vrai
    prix.
    """
    ligne = db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()
    if ligne is None:
        raise HTTPException(status_code=404, detail="Carte introuvable.")

    releves = card_catalog.historique_de_la_carte(db, ligne.name_slug, ligne.card_code)

    charge = card_catalog.carte_en_dict(
        ligne, card_catalog.compteurs_d_annonces(db, [ligne.id]).get(ligne.id)
    )
    charge["themes_detail"] = [
        {
            "slug": theme.slug,
            "label": theme.label,
            "description": theme.description,
            "famille": theme.famille,
        }
        for theme in (card_themes.theme_par_slug(s) for s in charge["themes"])
        if theme is not None
    ]
    charge["history"] = [
        {"captured_on": jour.isoformat(), "price_eur": prix} for jour, prix in releves
    ]
    charge["trend_history"] = tendance_historique(releves).to_dict()
    charge["projection"] = projection(releves, horizon_jours).to_dict()
    return charge
