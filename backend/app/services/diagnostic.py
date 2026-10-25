"""
Bilan de sante complet, lisible dans un navigateur.

POURQUOI CE MODULE EXISTE
-------------------------
« L'application ne marche pas » peut vouloir dire dix choses : catalogue
vide, prix absents, visuels gris, radar sans annonce, source qui refuse,
serveur qui plante. Les distinguer demandait jusqu'ici une commande par
hypothese, tapee dans une seconde fenetre — et autant d'allers-retours.

Une seule adresse rend tout, testee DEPUIS LA MACHINE OU TOURNE
L'APPLICATION : c'est elle qui atteint les sources, et c'est donc d'elle
qu'il faut savoir ce qu'elles repondent.

CE QUI N'Y FIGURE PAS
---------------------
Aucun secret : la presence d'une cle eBay est dite (oui/non), jamais sa
valeur, et les lignes de journal sont expurgees de tout ce qui ressemble a
un identifiant de connexion.

Chaque rubrique est isolee : une source qui plante donne une ligne
« erreur » dans le bilan, pas un bilan absent.
"""
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Listing, MarketCardPrice

logger = logging.getLogger(__name__)

# Ce qu'il faut masquer dans une ligne de journal avant de l'afficher :
# « postgresql://utilisateur:motdepasse@hote », « token=… », « secret=… ».
_SECRETS = [
    (re.compile(r"(://[^:/\s]+:)[^@\s]+@"), r"\1***@"),
    (re.compile(r"((?:token|secret|password|api[_-]?key)[\"']?\s*[=:]\s*[\"']?)[^\s\"'&,]+", re.I),
     r"\1***"),
]


def _rubrique(fonction):
    """Execute une rubrique ; une erreur devient une ligne du bilan."""
    try:
        return fonction()
    except Exception as erreur:  # noqa: BLE001
        logger.warning("Diagnostic : rubrique %s en echec (%s)", fonction.__name__, erreur)
        return {"erreur": f"{type(erreur).__name__}: {str(erreur)[:200]}"}


def _expurger(ligne: str) -> str:
    for motif, remplacement in _SECRETS:
        ligne = motif.sub(remplacement, ligne)
    return ligne


def erreurs_recentes(dossier: Path = Path("."), nombre: int = 25) -> list:
    """Les derniers avertissements et erreurs des journaux du serveur.

    Le script Windows envoie la sortie standard dans api.log et les erreurs
    dans api.log.err ; c'est la que Python ecrit ses journaux. On lit les
    deux, s'ils existent. Sur un hebergement, aucun fichier : liste vide.
    """
    lignes = []
    for nom in ("api.log", "api.log.err"):
        chemin = dossier / nom
        if not chemin.exists():
            continue
        try:
            brut = chemin.read_bytes()
        except OSError:
            continue
        # Sous Windows, Python ecrit son journal dans l'encodage du systeme
        # (cp1252 en francais), pas en UTF-8 : lu en UTF-8, « Démarrage »
        # devenait « D�marrage ». On tente l'UTF-8, puis cp1252.
        try:
            texte = brut.decode("utf-8")
        except UnicodeDecodeError:
            texte = brut.decode("cp1252", errors="replace")
        lignes += [l for l in texte.splitlines()
                   if "WARNING" in l or "ERROR" in l or "Traceback" in l
                   or "Error:" in l or "Exception" in l]
    return [_expurger(l)[:300] for l in lignes[-nombre:]]


def _catalogue(db: Session) -> dict:
    from app.scheduler import rafraichissement_en_cours

    total = db.query(MarketCardPrice).count()
    par_langue = dict(db.query(MarketCardPrice.language, func.count())
                      .group_by(MarketCardPrice.language).all())
    chiffrees = db.query(MarketCardPrice).filter(MarketCardPrice.price_eur.isnot(None)).count()
    releve = (db.query(func.max(MarketCardPrice.updated_at))
              .filter(MarketCardPrice.source == "opecards").scalar())
    return {
        "cartes": total,
        "francaises": par_langue.get("fr", 0),
        "anglaises": par_langue.get("en", 0),
        "sans_langue": par_langue.get(None, 0),
        "avec_prix": chiffrees,
        "prix_releves_le": releve.isoformat() if releve else None,
        "rafraichissement_en_cours": rafraichissement_en_cours(),
    }


def _visuels(db: Session) -> dict:
    from app.collectors.card_images import MARQUE_DEDUITE

    par_source = dict(db.query(MarketCardPrice.image_source, func.count())
                      .filter(MarketCardPrice.image_url.isnot(None))
                      .group_by(MarketCardPrice.image_source).all())
    sans = db.query(MarketCardPrice).filter(MarketCardPrice.image_url.is_(None)).count()
    return {
        "avec_visuel": sum(par_source.values()),
        "dont_deduits_pas_encore_verifies": sum(
            n for s, n in par_source.items() if (s or "").endswith(MARQUE_DEDUITE)),
        "sans_visuel": sans,
        "par_source": {s or "inconnue": n for s, n in par_source.items()},
    }


def _annonces(db: Session) -> dict:
    total = db.query(Listing).count()
    par_source = {str(getattr(s, "value", s)): n for s, n in
                  db.query(Listing.source, func.count()).group_by(Listing.source).all()}
    derniere = db.query(func.max(Listing.last_seen_at)).scalar()
    avec_score = db.query(Listing).filter(Listing.deal_score.isnot(None)).count()
    return {
        "annonces": total,
        "par_source": par_source,
        "avec_score": avec_score,
        "derniere_vue_le": derniere.isoformat() if derniere else None,
    }


def _collecte() -> dict:
    return {
        "vinted_active": settings.vinted_enabled,
        "vinted_recherche": settings.vinted_search_text,
        "ebay_configure": bool(settings.ebay_client_id and settings.ebay_client_secret),
        "planificateur_actif": settings.scheduler_enabled,
        "intervalle_minutes": settings.check_interval_minutes,
        "cartes_francaises_seulement": settings.french_only,
    }


def _vinted() -> dict:
    """Une VRAIE recherche, pour savoir combien d'annonces en sortent.

    Le scraper lit la page HTML du catalogue ; si Vinted en change la
    structure, il ne trouve plus rien SANS lever d'erreur — le radar reste
    vide et rien ne dit pourquoi. Le nombre d'annonces extraites, mis a cote
    de la taille de la page et du nombre de liens d'annonces qu'elle
    contient, distingue « Vinted refuse » de « Vinted repond mais on ne sait
    plus lire sa page ».
    """
    from app.collectors.vinted_scraper import VintedBlockedError, VintedScraper

    scraper = VintedScraper(request_delay_seconds=1.0)
    page = scraper.diagnostic_fetch(search_text=settings.vinted_search_text)
    resultat = {
        "page_recue": page.get("ok"),
        "code_http": page.get("status_code"),
        "taille_page": page.get("html_length"),
        "liens_d_annonces_dans_la_page": page.get("items_link_count"),
    }
    if not page.get("ok"):
        resultat["raison"] = page.get("reason")
        resultat["adresse"] = page.get("url_tentee")
        return resultat
    try:
        annonces = scraper.search_card_listings(search_text=settings.vinted_search_text)
    except VintedBlockedError as erreur:
        resultat["refus"] = str(erreur)[:200]
        return resultat
    resultat["annonces_extraites"] = len(annonces)
    resultat["exemples"] = [f"{a.price} € — {a.title[:70]}" for a in annonces[:3]]
    return resultat


def _visuels_en_ligne(db: Session) -> dict:
    """Ce que les sites officiels repondent, pour une carte de chaque jeu."""
    from app.collectors.card_images import ClientImagesCartes

    client = ClientImagesCartes()
    francaise = (db.query(MarketCardPrice)
                 .filter(MarketCardPrice.image_url.like("%fr.onepiece-cardgame.com%"))
                 .first())
    bilan = {}
    if francaise:
        bilan["carte_francaise"] = {
            "adresse": francaise.image_url,
            "image_servie": client.verifier(francaise.image_url),
        }
    essai = client.diagnostic("OP01-001", anglais=True)
    bilan["carte_anglaise_OP01-001"] = [
        {"adresse": t["url"],
         "reponse": t.get("status_code") or t.get("erreur_reseau", "")[:80],
         "type": t.get("content_type")}
        for t in (essai.get("tentatives") or [])[:4]
    ]
    return bilan


def etablir_diagnostic(db: Session, avec_sources: bool = True) -> dict:
    """Le bilan complet. `avec_sources=False` saute les appels au reseau."""
    bilan = {
        "etabli_le": datetime.utcnow().isoformat(),
        "catalogue": _rubrique(lambda: _catalogue(db)),
        "visuels": _rubrique(lambda: _visuels(db)),
        "annonces": _rubrique(lambda: _annonces(db)),
        "collecte": _rubrique(_collecte),
    }
    if avec_sources:
        bilan["vinted_depuis_cette_machine"] = _rubrique(_vinted)
        bilan["sites_officiels_depuis_cette_machine"] = _rubrique(
            lambda: _visuels_en_ligne(db))
    bilan["erreurs_recentes"] = _rubrique(erreurs_recentes)
    return bilan
