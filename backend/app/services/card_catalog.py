"""
Exploration du catalogue de cartes : filtres, themes, cartes en vogue,
historique.

Ce module sert la nouvelle direction de l'app demandee le 10/10/2026 :
chercher des cartes dans le CATALOGUE (« quelles cartes existent, a quel
prix, dans quel theme, lesquelles montent »), par opposition a la chasse
aux bonnes affaires, qui part des ANNONCES Vinted/eBay. Les deux cohabitent
et se completent : on repere ici une carte qui monte, on la traque ensuite
dans les annonces.

La source est `MarketCardPrice`, l'index local alimente par ZebraDex. Donc
tout ce qui est servi ici depend de l'avancement de cette synchronisation :
`/api/admin/price-index-status` dit ou elle en est. Un catalogue vide n'est
pas une panne, c'est une synchronisation qui n'a pas encore tourne.
"""
import logging
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import func, nullslast
from sqlalchemy.orm import Session

from app.models import CardPriceSnapshot, MarketCardPrice
from app.services import card_themes
from app.services.card_trends import tendance_7_jours
from app.settings_service import load_app_settings

logger = logging.getLogger(__name__)

# Tri par defaut : le prix decroissant est plus parlant que l'ordre
# d'insertion quand on explore un theme.
TRIS = {
    "prix": MarketCardPrice.price_eur,
    "nom": MarketCardPrice.display_name,
    "variation": MarketCardPrice.variation_7d_eur,
    "maj": MarketCardPrice.updated_at,
}


def _requete_filtree(
    db: Session,
    q: Optional[str] = None,
    theme: Optional[str] = None,
    rarity: Optional[str] = None,
    series: Optional[str] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    tendance: Optional[str] = None,
    avec_image: Optional[bool] = None,
    avec_annonces: Optional[bool] = None,
):
    requete = db.query(MarketCardPrice)

    if q:
        # La requete est normalisee exactement comme `search_key` l'a ete a
        # l'ecriture : minuscules, sans accents. C'est ce qui rend la
        # recherche insensible a la casse ET aux accents, et identique sous
        # SQLite et sous Postgres. Chercher sur le nom affiche ne marchait
        # pas : `lower()` de SQLite ignore les accents, et personne ne tape
        # « Électhor ». Voir card_themes.cle_de_recherche.
        normalise = card_themes.cle_de_recherche(q)
        # Replis pour les lignes pas encore rattrapees par
        # /api/admin/recompute-card-fields : sans eux, une base synchronisee
        # avant cette colonne ne rendrait plus rien du tout. Le slug est deja
        # sans accents mais separe par des tirets ; le code de carte est de
        # l'ASCII, donc `lower()` s'y comporte pareil sous SQLite et Postgres.
        requete = requete.filter(
            func.coalesce(MarketCardPrice.search_key, "").like(f"%{normalise}%")
            | MarketCardPrice.name_slug.like(f"%{normalise.replace(' ', '-')}%")
            | func.lower(func.coalesce(MarketCardPrice.card_code, "")).like(f"%{normalise}%")
        )

    if theme:
        # Filtre exact grace aux virgules de bord : voir card_themes.
        requete = requete.filter(
            MarketCardPrice.theme_slugs.like(card_themes.motif_like_pour_theme(theme))
        )

    if rarity:
        requete = requete.filter(
            func.lower(func.coalesce(MarketCardPrice.rarity, "")) == rarity.strip().lower()
        )

    if series:
        requete = requete.filter(
            func.lower(func.coalesce(MarketCardPrice.series_name, "")).like(
                f"%{series.strip().lower()}%"
            )
        )

    if prix_min is not None:
        requete = requete.filter(MarketCardPrice.price_eur >= prix_min)
    if prix_max is not None:
        requete = requete.filter(MarketCardPrice.price_eur <= prix_max)

    if tendance in ("hausse", "baisse"):
        # La direction se lit sur le signe de la variation. Le seuil de
        # "stable" est applique apres coup en Python (il depend du prix),
        # mais ce pre-filtre evite de ramener toute la base pour rien.
        if tendance == "hausse":
            requete = requete.filter(MarketCardPrice.variation_7d_eur > 0)
        else:
            requete = requete.filter(MarketCardPrice.variation_7d_eur < 0)

    if avec_image is True:
        requete = requete.filter(MarketCardPrice.image_url.isnot(None))
    elif avec_image is False:
        requete = requete.filter(MarketCardPrice.image_url.is_(None))

    if avec_annonces is True:
        # EXISTS plutot qu'une jointure : une carte avec cinq annonces doit
        # rester UNE ligne, sinon le total affiche et la pagination
        # comptent des doublons.
        from app.models import Listing  # local : evite un cycle

        seuil = load_app_settings(db).get("min_listing_price") or 0.0
        sous_requete = db.query(Listing.id).filter(
            Listing.matched_card_id == MarketCardPrice.id
        )
        requete = requete.filter(_annonces_visibles(sous_requete, seuil).exists())

    return requete


def rechercher_cartes(
    db: Session,
    q: Optional[str] = None,
    theme: Optional[str] = None,
    rarity: Optional[str] = None,
    series: Optional[str] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    tendance: Optional[str] = None,
    avec_image: Optional[bool] = None,
    avec_annonces: Optional[bool] = None,
    tri: str = "prix",
    ordre: str = "desc",
    limite: int = 60,
    decalage: int = 0,
) -> dict:
    """Recherche filtree dans le catalogue.

    Rend aussi le total AVANT pagination : sans lui, l'interface ne peut pas
    dire « 1 240 cartes correspondent » ni proposer une page suivante.
    """
    requete = _requete_filtree(
        db, q=q, theme=theme, rarity=rarity, series=series,
        prix_min=prix_min, prix_max=prix_max, tendance=tendance,
        avec_image=avec_image, avec_annonces=avec_annonces,
    )

    total = requete.count()

    colonne = TRIS.get(tri, MarketCardPrice.price_eur)
    requete = requete.order_by(colonne.desc() if ordre == "desc" else colonne.asc())

    lignes = requete.limit(limite).offset(decalage).all()

    # Une seule requete agregee pour toute la page, pas une par carte.
    compteurs = compteurs_d_annonces(db, [ligne.id for ligne in lignes])

    return {
        "total": total,
        "limite": limite,
        "decalage": decalage,
        "cartes": [carte_en_dict(ligne, compteurs.get(ligne.id)) for ligne in lignes],
    }


def carte_en_dict(ligne: MarketCardPrice,
                  annonces: Optional[dict] = None) -> dict:
    """`annonces` vient de `compteurs_d_annonces` : {listings_count,
    best_deal_score}. Absent (fiche carte, cartes en vogue) -> zero.

    Le compte est porte jusqu'a la grille pour repondre d'un coup d'oeil a
    « laquelle de ces cartes a quelque chose a prendre ? », au lieu de
    devoir ouvrir chaque fiche l'une apres l'autre.
    """
    tendance = tendance_7_jours(ligne.price_eur, ligne.variation_7d_eur)
    annonces = annonces or {}
    return {
        "id": ligne.id,
        "card_code": ligne.card_code,
        "name_slug": ligne.name_slug,
        "display_name": ligne.display_name,
        "series_name": ligne.series_name,
        "rarity": ligne.rarity,
        "price_eur": ligne.price_eur,
        "price_low_eur": ligne.price_low_eur,
        "price_high_eur": ligne.price_high_eur,
        # Rappel porte jusqu'a l'interface : cette fourchette est derivee de
        # la volatilite recente, ce ne sont PAS des extremes de ventes
        # conclues (la source ne publie pas cette donnee).
        "price_range_is_derived": True,
        "themes": card_themes.decoder_themes(ligne.theme_slugs),
        "image_url": ligne.image_url,
        "image_source": ligne.image_source,
        "trend_7d": tendance.to_dict(),
        "listings_count": annonces.get("listings_count", 0),
        "best_deal_score": annonces.get("best_deal_score"),
        "updated_at": ligne.updated_at.isoformat() if ligne.updated_at else None,
    }


def themes_avec_compteurs(db: Session) -> List[dict]:
    """Liste des themes, avec le nombre de cartes et la fourchette de prix.

    Permet a l'interface d'afficher « Equipage du Chapeau de Paille — 184 cartes, de
    0,30 a 419 EUR » plutot qu'une simple etiquette : c'est ce qui rend un
    theme choisissable.
    """
    resultats = []
    for theme in card_themes.TOUS_LES_THEMES:
        agregats = (
            db.query(
                func.count(MarketCardPrice.id),
                func.min(MarketCardPrice.price_eur),
                func.max(MarketCardPrice.price_eur),
                func.avg(MarketCardPrice.price_eur),
            )
            .filter(
                MarketCardPrice.theme_slugs.like(
                    card_themes.motif_like_pour_theme(theme.slug)
                )
            )
            .one()
        )
        nombre, prix_min, prix_max, prix_moyen = agregats
        resultats.append({
            "slug": theme.slug,
            "label": theme.label,
            "description": theme.description,
            "famille": theme.famille,
            "card_count": nombre or 0,
            "price_min_eur": round(prix_min, 2) if prix_min is not None else None,
            "price_max_eur": round(prix_max, 2) if prix_max is not None else None,
            "price_avg_eur": round(prix_moyen, 2) if prix_moyen is not None else None,
        })
    return resultats


def valeurs_de_filtres(db: Session) -> dict:
    """Valeurs reellement presentes en base pour alimenter les listes
    deroulantes. Proposer une rarete qu'aucune carte ne porte ne sert qu'a
    offrir un filtre qui ne rend rien."""
    raretes = [
        r[0] for r in db.query(MarketCardPrice.rarity)
        .filter(MarketCardPrice.rarity.isnot(None))
        .distinct().order_by(MarketCardPrice.rarity).all()
        if r[0]
    ]
    series = [
        s[0] for s in db.query(MarketCardPrice.series_name)
        .filter(MarketCardPrice.series_name.isnot(None))
        .distinct().order_by(MarketCardPrice.series_name).all()
        if s[0]
    ]
    bornes = db.query(
        func.min(MarketCardPrice.price_eur), func.max(MarketCardPrice.price_eur)
    ).one()
    return {
        "rarities": raretes,
        "series": series,
        "price_min_eur": round(bornes[0], 2) if bornes[0] is not None else None,
        "price_max_eur": round(bornes[1], 2) if bornes[1] is not None else None,
        "themes": [
            {"slug": t.slug, "label": t.label, "famille": t.famille}
            for t in card_themes.TOUS_LES_THEMES
        ],
        "total_cards": db.query(MarketCardPrice).count(),
    }


def cartes_en_vogue(
    db: Session,
    sens: str = "hausse",
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    theme: Optional[str] = None,
    limite: int = 30,
) -> List[dict]:
    """Les plus fortes variations 7 jours, en POURCENTAGE et non en euros.

    Le classement en euros ne dirait rien d'autre que « les cartes cheres
    bougent de plus gros montants » : +12 EUR sur une carte a 400 EUR est du
    bruit, alors que +12 EUR sur une carte a 8 EUR est un triplement. Le tri
    se fait donc en Python sur le pourcentage, apres un pre-filtre SQL sur
    le signe.
    """
    requete = _requete_filtree(
        db, theme=theme, prix_min=prix_min, prix_max=prix_max, tendance=sens,
    ).filter(MarketCardPrice.variation_7d_eur.isnot(None))

    # Garde-fou : on borne ce qu'on ramene en memoire. Les plus fortes
    # variations en euros sont de bonnes candidates aux plus fortes
    # variations en pourcentage, sans etre exactement les memes — d'ou une
    # marge large plutot qu'un `limite` serre.
    plafond_lecture = max(limite * 20, 500)
    colonne = MarketCardPrice.variation_7d_eur
    lignes = (
        requete.order_by(colonne.desc() if sens == "hausse" else colonne.asc())
        .limit(plafond_lecture)
        .all()
    )

    cartes = [carte_en_dict(ligne) for ligne in lignes]
    cartes = [c for c in cartes if c["trend_7d"]["variation_pct"] is not None]
    cartes.sort(
        key=lambda c: c["trend_7d"]["variation_pct"],
        reverse=(sens == "hausse"),
    )
    cartes = cartes[:limite]

    # Les compteurs d'annonces APRES la coupe : on vient d'en lire plusieurs
    # centaines pour n'en garder qu'une douzaine, les compter toutes serait
    # du travail jete. Sans ca, une carte du rail affichait « aucune
    # annonce » alors que la grille en annonçait trois juste en dessous.
    compteurs = compteurs_d_annonces(db, [c["id"] for c in cartes])
    for carte in cartes:
        compte = compteurs.get(carte["id"], {})
        carte["listings_count"] = compte.get("listings_count", 0)
        carte["best_deal_score"] = compte.get("best_deal_score")

    return cartes


# --- historique ----------------------------------------------------------


def enregistrer_releve_du_jour(db: Session, limite: Optional[int] = None) -> dict:
    """Prend un releve de prix pour chaque carte de l'index.

    A appeler une fois par jour (voir scheduler). C'est la seule facon
    d'avoir un jour un historique : la source ne publie qu'un prix
    instantane, et rien ne permet de reconstituer le passe apres coup.

    Relancer le meme jour met a jour les releves du jour au lieu d'empiler
    des doublons, qui fausseraient la regression.
    """
    aujourdhui = date.today()

    requete = db.query(MarketCardPrice).filter(MarketCardPrice.price_eur.isnot(None))
    if limite:
        requete = requete.limit(limite)
    cartes = requete.all()

    existants = {
        (s.name_slug, s.card_code): s
        for s in db.query(CardPriceSnapshot)
        .filter(CardPriceSnapshot.captured_on == aujourdhui)
        .all()
    }

    crees, mis_a_jour = 0, 0
    for carte in cartes:
        cle = (carte.name_slug, carte.card_code)
        existant = existants.get(cle)
        if existant is not None:
            if existant.price_eur != carte.price_eur:
                existant.price_eur = carte.price_eur
                mis_a_jour += 1
        else:
            db.add(CardPriceSnapshot(
                name_slug=carte.name_slug,
                card_code=carte.card_code,
                price_eur=carte.price_eur,
                captured_on=aujourdhui,
            ))
            crees += 1

    db.commit()
    logger.info(
        "Releve de prix du %s : %d carte(s) examinee(s), %d releve(s) cree(s), "
        "%d mis a jour", aujourdhui, len(cartes), crees, mis_a_jour,
    )
    return {
        "captured_on": aujourdhui.isoformat(),
        "examined": len(cartes),
        "created": crees,
        "updated": mis_a_jour,
    }


def historique_de_la_carte(db: Session, name_slug: str,
                           card_code: Optional[str] = None) -> List[tuple]:
    requete = db.query(CardPriceSnapshot).filter(
        CardPriceSnapshot.name_slug == name_slug
    )
    if card_code:
        requete = requete.filter(CardPriceSnapshot.card_code == card_code)
    lignes = requete.order_by(CardPriceSnapshot.captured_on.asc()).all()
    return [(ligne.captured_on, ligne.price_eur) for ligne in lignes]


def _annonces_visibles(requete, seuil: float):
    """Les exclusions du tableau de bord, definies UNE SEULE FOIS.

    Annonce ecartee, disparue de chez le vendeur, retiree, masquee a la
    main, ou sous le prix plancher. Trois endroits s'en servent : la liste
    des annonces d'une carte, le comptage affiche sur la grille, et le
    filtre « seulement les cartes avec une annonce ». S'ils divergeaient,
    la grille promettrait une affaire que la fiche ne montrerait pas — ce
    qui est pire que de ne rien promettre du tout.
    """
    from app.models import Listing, ListingStatus  # local : evite un cycle

    return (
        requete
        .filter(Listing.status.notin_([ListingStatus.IGNORED,
                                       ListingStatus.UNAVAILABLE,
                                       ListingStatus.REMOVED]))
        .filter((Listing.manual_status.is_(None)) | (Listing.manual_status != "hidden"))
        .filter(Listing.price > seuil)
    )


def compteurs_d_annonces(db: Session, card_ids: List[int]) -> dict:
    """Combien d'annonces en vente par carte, et le meilleur score.

    Une seule requete agregee pour toute la page de resultats : la grille
    affiche des dizaines de cartes, et une requete par carte ferait des
    dizaines d'allers-retours pour une information d'appoint.

    Sert a repondre, depuis la grille, a « laquelle de ces cartes a quelque
    chose a prendre en ce moment ? » sans avoir a les ouvrir une par une.
    """
    from app.models import Listing  # local : evite un cycle

    if not card_ids:
        return {}

    seuil = load_app_settings(db).get("min_listing_price") or 0.0

    requete = db.query(
        Listing.matched_card_id,
        func.count(Listing.id),
        func.max(Listing.deal_score),
    ).filter(Listing.matched_card_id.in_(card_ids))

    requete = _annonces_visibles(requete, seuil).group_by(Listing.matched_card_id)

    return {
        card_id: {"listings_count": nombre, "best_deal_score": meilleur}
        for card_id, nombre, meilleur in requete.all()
    }


def annonces_de_la_carte(db: Session, card_id: int, limite: int = 20) -> List[dict]:
    """Annonces en vente pour CETTE carte, les meilleures affaires d'abord.

    C'est ce qui relie les deux moities de l'app : on repere une carte dans
    le catalogue, et on voit immediatement s'il y a quelque chose a prendre
    en ce moment, sans retourner fouiller le dashboard.

    Les memes exclusions que le dashboard s'appliquent — annonce ecartee,
    disparue de chez le vendeur, masquee a la main, ou sous le seuil de prix
    — pour qu'une annonce cachee d'un cote ne reapparaisse pas de l'autre.

    Les PHOTOS DU VENDEUR sont rendues telles quelles. Pour decider
    d'acheter, elles valent mieux qu'une illustration officielle : c'est
    l'exemplaire reel qui est en vente, avec son centrage, ses bords et son
    etat.
    """
    from app.models import Listing  # local : evite un cycle

    seuil = load_app_settings(db).get("min_listing_price") or 0.0

    requete = db.query(Listing).filter(Listing.matched_card_id == card_id)
    lignes = (
        _annonces_visibles(requete, seuil)
        .order_by(nullslast(Listing.deal_score.desc()))
        .limit(limite)
        .all()
    )

    return [
        {
            "id": ligne.id,
            "source": ligne.source.value if ligne.source else None,
            "title": ligne.title,
            "url": ligne.url,
            "price_eur": ligne.price,
            "shipping_eur": ligne.shipping_price,
            "total_eur": round((ligne.price or 0) + (ligne.shipping_price or 0), 2),
            "deal_score": ligne.deal_score,
            "margin_net_eur": ligne.margin_net,
            "margin_ratio": ligne.margin_ratio,
            "condition_tier": ligne.condition_tier,
            "quality_text_score": ligne.quality_text_score,
            "quality_vision_score": ligne.quality_vision_score,
            "seller_username": ligne.seller_username,
            "seller_reliability_score": ligne.seller_reliability_score,
            # Les photos de l'exemplaire reellement en vente.
            "photo_urls": ligne.photo_urls or [],
            "price_match_confidence": ligne.price_match_confidence,
            "first_seen_at": ligne.first_seen_at.isoformat() if ligne.first_seen_at else None,
        }
        for ligne in lignes
    ]


def recalculer_champs_derives(db: Session, limite: int = 5000) -> dict:
    """Recalcule les champs DERIVES des cartes deja en base : les themes et
    la cle de recherche.

    Necessaire a trois moments : au deploiement de ces fonctionnalites, ou
    toutes les cartes ont ete synchronisees avant que ces colonnes existent ;
    apres chaque ajout de theme dans card_themes.py ; et si la normalisation
    de la cle de recherche change. Sans ce rattrapage, un nouveau theme
    resterait vide et la recherche ne rendrait rien sur les anciennes lignes,
    jusqu'a la resynchronisation complete du catalogue — qui prend des jours
    au rythme impose a ZebraDex.
    """
    cartes = db.query(MarketCardPrice).limit(limite).all()
    modifiees = 0
    for carte in cartes:
        themes = card_themes.encoder_themes(
            card_themes.themes_de_la_carte(carte.display_name, carte.rarity)
        )
        cle = card_themes.cle_de_recherche(carte.display_name, carte.card_code)
        if carte.theme_slugs != themes or carte.search_key != cle:
            carte.theme_slugs = themes
            carte.search_key = cle
            modifiees += 1
    db.commit()
    logger.info("Champs derives : %d carte(s) examinee(s), %d mise(s) a jour",
                len(cartes), modifiees)
    return {"examined": len(cartes), "updated": modifiees}
