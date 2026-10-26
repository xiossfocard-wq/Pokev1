import enum
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Enum, Float, ForeignKey, Integer, String,
    Text, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SourcePlatform(str, enum.Enum):
    EBAY = "ebay"
    VINTED = "vinted"


class ListingStatus(str, enum.Enum):
    NEW = "new"                        # détectée, pas encore complètement scorée
    SCORED = "scored"                  # marge + qualité + score final calculés
    NOTIFIED = "notified"              # notification envoyée (score au-dessus du seuil)
    NO_PRICE_MATCH = "no_price_match"  # aucun prix de référence trouvé, mais À AFFICHER
                                        # quand même (comparaison manuelle possible) —
                                        # distinct de IGNORED depuis le 04/08/2026 (avant,
                                        # ce cas utilisait IGNORED par erreur, ce qui la
                                        # faisait disparaître du dashboard aussitôt scorée)
    IGNORED = "ignored"                # exclusion délibérée (ex: langue non française) —
                                        # celle-ci reste masquée du dashboard, à raison
    UNAVAILABLE = "unavailable"        # l'annonce n'existe plus chez le vendeur (vendue ou
                                        # supprimée). Masquée : cliquer dessus menait sur une
                                        # page d'erreur Vinted, signalé par l'utilisateur le
                                        # 25/08/2026
    REMOVED = "removed"                # annonce disparue lors d'un scan ultérieur


class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)
    source = Column(Enum(SourcePlatform, native_enum=False), nullable=False, index=True)
    external_id = Column(String(128), nullable=False, index=True)

    title = Column(String(512), nullable=False)
    description = Column(Text, default="")
    url = Column(String(1024), nullable=False)

    price = Column(Float, nullable=False)
    shipping_price = Column(Float, default=0.0)
    currency = Column(String(8), default="EUR")

    # Ce que la page Vinted affiche a cote du prix : le prix protection
    # acheteur comprise, et l'etat choisi par le vendeur dans le menu. Le
    # scraper les relevait depuis le debut, mais le pipeline les jetait —
    # le cout d'achat retenu ignorait donc la protection, et l'etat declare
    # n'entrait pas dans le prix de reference.
    price_incl_protection = Column(Float, nullable=True)
    seller_condition = Column(String(64), nullable=True)
    # Le cout REEL d'un achat — article, protection, port (estime quand
    # l'annonce ne le dit pas) —, et son detail poste par poste, pour que
    # l'interface puisse dire d'ou vient chaque euro.
    purchase_cost_eur = Column(Float, nullable=True)
    purchase_cost_detail = Column(JSON, nullable=True)
    # MODE COLLECTION : ce qu'on economise par rapport a la cote (ajustee a
    # l'etat), frais d'achat compris, en euros et en part de la cote. La
    # marge, elle, suppose une revente sur Cardmarket et en deduit les frais :
    # pour qui garde la carte, elle sous-estimait toutes les affaires.
    savings_eur = Column(Float, nullable=True)
    savings_ratio = Column(Float, nullable=True)

    photo_urls = Column(JSON, default=list)

    seller_username = Column(String(256), nullable=True)
    seller_reliability_score = Column(Float, nullable=True)
    seller_reliability_detail = Column(String(512), nullable=True)

    card_name_guess = Column(String(256), nullable=True)  # meilleure estimation du nom de carte

    reference_price = Column(Float, nullable=True)
    reference_price_source = Column(String(64), nullable=True)  # "cardmarket" etc.

    margin_net = Column(Float, nullable=True)
    margin_ratio = Column(Float, nullable=True)

    quality_text_score = Column(Float, nullable=True)
    quality_vision_score = Column(Float, nullable=True)
    quality_vision_detail = Column(JSON, nullable=True)  # explication du modèle vision

    deal_score = Column(Float, nullable=True, index=True)

    rarity_tier = Column(String(64), nullable=True)      # ex "Illustration Rare"
    is_vintage = Column(Boolean, default=False)
    # Renomme le 14/10/2026 avec le passage a One Piece : le champ parle
    # d'un personnage phare du jeu. L'ancienne colonne est rattrapee
    # par _COLONNES_AJOUTEES (database.py).
    is_popular_character = Column(Boolean, default=False)
    condition_tier = Column(String(8), nullable=True)     # "NM" | "LP" | "MP" | "HP" | "DMG"

    # Prix de reference detaille (voir services/price_index.py). La
    # fourchette basse/haute est derivee de la volatilite 7 jours de
    # ZebraDex, PAS d'un historique de ventes conclues - a presenter
    # comme telle dans l'UI.
    price_low_eur = Column(Float, nullable=True)
    price_high_eur = Column(Float, nullable=True)
    price_match_confidence = Column(String(16), nullable=True)  # high|medium|low

    # Lien vers la carte du catalogue retenue par le rapprochement.
    # Il n'existait que dans le JSON `price_detail`, donc impossible a
    # joindre : on ne pouvait pas demander « quelles annonces pour CETTE
    # carte », qui est pourtant la question qu'on se pose en achetant.
    matched_card_id = Column(
        Integer, ForeignKey("market_card_prices.id"), nullable=True, index=True
    )
    price_detail = Column(JSON, nullable=True)

    status = Column(Enum(ListingStatus, native_enum=False), default=ListingStatus.NEW, index=True)

    # --- Corrections saisies a la main depuis le dashboard --------------
    # L'identification automatique se trompe : le titre est ecrit
    # librement, l'index de prix est incomplet, et plusieurs cartes portent
    # souvent le meme nom. Quand l'utilisateur voit que la carte retenue
    # n'est pas la bonne, il doit pouvoir le dire — et son verdict prime
    # sur l'automatique, definitivement. Aucun repassage automatique ne
    # revient dessus.
    manual_status = Column(String(16), nullable=True, index=True)  # wrong_card | hidden
    manual_reference_price = Column(Float, nullable=True)          # prix marche saisi a la main
    manual_reviewed_at = Column(DateTime, nullable=True)

    first_seen_at = Column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    scored_at = Column(DateTime, nullable=True)

    notifications = relationship("NotificationSent", back_populates="listing")

    def __repr__(self):
        return f"<Listing {self.source}:{self.external_id} score={self.deal_score}>"


class PriceReference(Base):
    """Cache des prix de référence par carte, pour éviter de retaper
    Cardmarket/ZebraDex à chaque annonce (rafraîchi au plus 1x/jour par carte)."""
    __tablename__ = "price_references"

    id = Column(Integer, primary_key=True)
    card_slug = Column(String(256), nullable=False, index=True, unique=True)
    expansion_slug = Column(String(256), nullable=True)
    trend_price_eur = Column(Float, nullable=True)
    avg_30d_price_eur = Column(Float, nullable=True)
    price_source = Column(String(64), nullable=True)  # "cardmarket" | "zebradex" | "cardmarket+zebradex"
    fetched_at = Column(DateTime, default=datetime.utcnow)


class NotificationSent(Base):
    __tablename__ = "notifications_sent"

    id = Column(Integer, primary_key=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False)
    channel = Column(String(32), nullable=False)  # "telegram" | "email"
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_detail = Column(String(512), nullable=True)

    listing = relationship("Listing", back_populates="notifications")


class AppSettings(Base):
    """Réglages modifiables depuis le dashboard (seuil de notif, poids du
    score, etc.), stockés en DB pour ne pas nécessiter de redéploiement."""
    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CarteSuivie(Base):
    """Une carte que l'utilisateur cherche, et le prix qu'il est pret a y
    mettre, protection acheteur et port compris.

    Un collectionneur ne chasse pas « une bonne affaire » en general : il
    chasse SA carte. Le radar classait toutes les annonces au meme titre ;
    une carte suivie est signalee partout ou elle apparait, et une annonce
    sous le budget declenche une alerte quel que soit son score.

    La carte est designee par son code et son nom de fiche, qui ne changent
    pas, plutot que par l'identifiant de sa ligne : une base reconstruite
    renumerote les lignes, et la liste pointerait alors vers d'autres cartes.
    """
    __tablename__ = "cartes_suivies"
    __table_args__ = (UniqueConstraint("card_code", "name_slug", name="uq_carte_suivie"),)

    id = Column(Integer, primary_key=True)
    card_code = Column(String(32), nullable=True)
    name_slug = Column(String(256), nullable=False)
    prix_max = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ZebraDexSeriesState(Base):
    """
    Suivi de synchronisation des series ZebraDex (158 series FR au
    04/08/2026, decouvertes automatiquement via /series - aucune config
    manuelle). La sync est PROGRESSIVE : quelques series par cycle plutot
    qu'un gros job bloquant, pour ne pas depasser les limites d'un
    hebergement gratuit ni marteler ZebraDex (1 req / 6s).
    """
    __tablename__ = "zebradex_series"

    id = Column(Integer, primary_key=True)
    series_id = Column(String(32), nullable=False, unique=True, index=True)
    name = Column(String(256), nullable=False)
    code = Column(String(32), nullable=True)
    bloc = Column(String(128), nullable=True)
    url = Column(String(512), nullable=False)
    last_synced_at = Column(DateTime, nullable=True, index=True)
    card_count = Column(Integer, default=0)
    last_error = Column(String(512), nullable=True)


class MarketCardPrice(Base):
    """
    Index local des prix de reference, une ligne par carte (toutes series
    confondues). Alimente par ZebraDex ; concu pour accueillir d'autres
    sources plus tard (colonne `source`).

    IMPORTANT sur price_low / price_high : ce ne sont PAS des min/max de
    ventes reellement conclues (ZebraDex ne publie pas cette donnee, il
    publie un prix marche + une variation 7 jours). Ce sont des bornes
    derivees de la volatilite recente - a presenter comme telles.
    """
    __tablename__ = "market_card_prices"

    id = Column(Integer, primary_key=True)
    card_code = Column(String(32), nullable=True, index=True)      # "PAF 232"
    name_slug = Column(String(256), nullable=False, index=True)    # "mew-ex"
    display_name = Column(String(256), nullable=False)             # "Mew Ex"
    series_name = Column(String(256), nullable=True, index=True)
    rarity = Column(String(64), nullable=True, index=True)

    # Nullable depuis le 20/10/2026. Cette table porte DEUX faits distincts
    # qu'elle confondait : « cette carte existe » (code, nom, serie, rarete,
    # visuel) et « elle vaut environ X ». Ils ne viennent pas de la meme
    # source et n'arrivent pas en meme temps : la liste officielle donne
    # l'existence, une place de marche donne le prix.
    #
    # Les fusionner obligeait a inventer un prix pour inscrire une carte au
    # catalogue. Un 0.0 de remplissage aurait ete pire que l'absence : il se
    # lit comme « cette carte ne vaut rien » et fausse marges et scores.
    #
    # None veut donc dire exactement une chose : le prix n'est pas connu.
    # Tout ce qui en derive (marge, score, tendance) doit s'abstenir, jamais
    # se rabattre sur une valeur par defaut.
    price_eur = Column(Float, nullable=True)
    price_low_eur = Column(Float, nullable=True)
    price_high_eur = Column(Float, nullable=True)
    variation_7d_eur = Column(Float, nullable=True)

    source = Column(String(32), default="zebradex")
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)

    # --- Exploration par theme (voir services/card_themes.py) ------------
    # Slugs encadres de virgules (",chapeau-de-paille,secret-rare,") pour
    # que le filtre SQL `LIKE '%,chapeau-de-paille,%'` soit exact. Champ texte plutot que table de
    # jointure : portable SQLite/Postgres, et aucune migration pour ce
    # volume. Recalcule a chaque synchronisation de la carte.
    theme_slugs = Column(String(512), nullable=True, index=True)

    # Nom + code normalises (minuscules, sans accents) pour une recherche
    # libre insensible a la casse et aux accents, identique sous SQLite et
    # sous Postgres. Voir card_themes.cle_de_recherche pour le pourquoi.
    search_key = Column(String(512), nullable=True, index=True)

    # --- Visuel de la carte ----------------------------------------------
    # ZebraDex ne publie pas d'image : elle vient d'une source distincte
    # (voir collectors/card_images.py). `image_checked_at` est renseigne
    # meme quand aucune image n'a ete trouvee, pour ne pas reinterroger la
    # meme carte indefiniment.
    image_url = Column(String(1024), nullable=True)
    image_source = Column(String(32), nullable=True)
    image_checked_at = Column(DateTime, nullable=True, index=True)

    # Langue du NOM affiche sur cette fiche, et d'ou il vient. Voir
    # core/langues.py pour ce que la valeur dit exactement : « en » ne
    # prouve pas qu'une carte n'existe pas en francais, seulement qu'on ne
    # l'a pas trouvee dans les series francaises chargees jusqu'ici.
    language = Column(String(8), nullable=True, index=True)


class CardPriceSnapshot(Base):
    """
    Un releve de prix par carte et par jour : c'est ce qui rend une
    tendance de fond possible.

    Pourquoi une table a part plutot qu'une colonne de plus : la source ne
    publie qu'un prix instantane et une variation 7 jours. Sans accumuler
    nous-memes, il n'y a aucun moyen de repondre a « cette carte monte-t-elle
    depuis trois mois ». Et cet historique ne peut pas etre reconstitue
    apres coup : il n'existe qu'a partir du jour ou on commence a le garder.

    Un seul releve par carte et par jour (contrainte d'unicite) : relancer
    la capture plusieurs fois dans la journee met a jour le releve du jour
    au lieu d'empiler des doublons qui fausseraient la regression.
    """
    __tablename__ = "card_price_snapshots"
    __table_args__ = (
        UniqueConstraint("name_slug", "card_code", "captured_on",
                         name="uq_snapshot_carte_jour"),
    )

    id = Column(Integer, primary_key=True)
    name_slug = Column(String(256), nullable=False, index=True)
    card_code = Column(String(32), nullable=True, index=True)
    price_eur = Column(Float, nullable=False)
    captured_on = Column(Date, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
