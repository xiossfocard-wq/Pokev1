"""
« Ma collection » : les cartes que l'utilisateur possede, ce qu'il les a
payees, et ce qu'elles valent aujourd'hui.

La valeur d'un exemplaire est la cote de sa carte ramenee a son etat — la
meme decote que pour juger une annonce (scoring/margin.DECOTE_PAR_ETAT) :
une carte MP ne vaut pas la cote d'une carte comme neuve, que ce soit a
l'achat ou dans un classeur. Une carte sans cote connue n'a pas de valeur
estimee, et le total le dit, au lieu de la compter pour zero.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import CartePossedee, Listing, MarketCardPrice
from app.scoring.margin import DECOTE_PAR_ETAT
from app.services import card_catalog


def _carte(db: Session, card_id: int) -> Optional[MarketCardPrice]:
    return db.query(MarketCardPrice).filter(MarketCardPrice.id == card_id).first()


def _carte_par_cle(db: Session, code: Optional[str], slug: str) -> Optional[MarketCardPrice]:
    return (db.query(MarketCardPrice)
            .filter(MarketCardPrice.card_code == code, MarketCardPrice.name_slug == slug)
            .first())


def valeur_d_un_exemplaire(cote: Optional[float], etat: Optional[str]) -> Optional[float]:
    """La cote ramenee a l'etat ; un etat inconnu ne decote pas."""
    if cote is None:
        return None
    return round(cote * DECOTE_PAR_ETAT.get(etat, 1.0), 2)


def ajouter(db: Session, card_id: Optional[int] = None, listing_id: Optional[int] = None,
            prix_paye: Optional[float] = None, etat: Optional[str] = None) -> Optional[dict]:
    """Range un exemplaire. Depuis une annonce achetee : la carte reconnue,
    le cout reel paye et l'etat retenu en sont repris (ce que l'utilisateur
    precise l'emporte), l'annonce quitte le radar et la carte quitte « Ma
    liste » — elle est trouvee.

    Rend None si la carte est introuvable (ou l'annonce non identifiee)."""
    annonce = None
    if listing_id is not None:
        annonce = db.query(Listing).filter(Listing.id == listing_id).first()
        if annonce is None or not annonce.matched_card_id:
            return None
        card_id = annonce.matched_card_id
        if prix_paye is None:
            prix_paye = annonce.purchase_cost_eur or annonce.price
        etat = etat or annonce.condition_tier
    carte = _carte(db, card_id) if card_id is not None else None
    if carte is None:
        return None

    db.add(CartePossedee(card_code=carte.card_code, name_slug=carte.name_slug,
                         prix_paye=prix_paye, etat=etat, achetee_le=datetime.utcnow(),
                         listing_id=listing_id))
    if annonce is not None:
        # Achetee : elle n'a plus rien a faire sur le radar.
        annonce.manual_status = "hidden"
        annonce.manual_reviewed_at = datetime.utcnow()
        from app.services import suivi
        suivi.ne_plus_suivre(db, carte.id)
    db.commit()
    return etat_de_la_carte(db, carte)


def retirer(db: Session, exemplaire_id: int) -> bool:
    exemplaire = db.query(CartePossedee).filter(CartePossedee.id == exemplaire_id).first()
    if exemplaire is None:
        return False
    db.delete(exemplaire)
    db.commit()
    return True


def etat_de_la_carte(db: Session, carte: MarketCardPrice) -> dict:
    """Combien d'exemplaires de cette carte, pour sa fiche."""
    nombre = (db.query(CartePossedee)
              .filter(CartePossedee.card_code == carte.card_code,
                      CartePossedee.name_slug == carte.name_slug)
              .count())
    return {"exemplaires": nombre}


def lister(db: Session) -> dict:
    """La collection, carte par carte, la plus precieuse d'abord, et ses
    totaux : valeur estimee, montant paye, plus-value."""
    groupes = {}
    for ex in db.query(CartePossedee).order_by(CartePossedee.achetee_le).all():
        groupes.setdefault((ex.card_code, ex.name_slug), []).append(ex)

    cartes: List[dict] = []
    totaux = {"exemplaires": 0, "valeur": 0.0, "paye": 0.0, "sans_cote": 0, "sans_prix_paye": 0,
              "plus_value": 0.0}
    for (code, slug), exemplaires in groupes.items():
        carte = _carte_par_cle(db, code, slug)
        cote = carte.price_eur if carte is not None else None
        lignes = []
        for ex in exemplaires:
            valeur = valeur_d_un_exemplaire(cote, ex.etat)
            lignes.append({
                "id": ex.id,
                "prix_paye": ex.prix_paye,
                "etat": ex.etat,
                "achetee_le": ex.achetee_le.isoformat() if ex.achetee_le else None,
                "valeur": valeur,
                # La plus-value n'a de sens que si les deux sont connus.
                "plus_value": (round(valeur - ex.prix_paye, 2)
                               if valeur is not None and ex.prix_paye is not None else None),
            })
            totaux["exemplaires"] += 1
            if valeur is None:
                totaux["sans_cote"] += 1
            else:
                totaux["valeur"] += valeur
            if ex.prix_paye is None:
                totaux["sans_prix_paye"] += 1
            else:
                totaux["paye"] += ex.prix_paye
            if lignes[-1]["plus_value"] is not None:
                totaux["plus_value"] += lignes[-1]["plus_value"]
        base = (card_catalog.carte_en_dict(carte) if carte is not None
                else {"id": None, "card_code": code, "name_slug": slug, "display_name": slug})
        cartes.append({
            **base,
            "introuvable": carte is None,
            "exemplaires": lignes,
            "valeur": round(sum(l["valeur"] for l in lignes if l["valeur"] is not None), 2),
        })
    cartes.sort(key=lambda c: (-c["valeur"], c.get("display_name") or ""))
    for cle in ("valeur", "paye", "plus_value"):
        totaux[cle] = round(totaux[cle], 2)
    return {"cartes": cartes, "totaux": totaux}
