from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.pipeline import (
    run_full_check, rescore_unpriced_listings, refilter_language,
    check_vinted_availability, enrich_card_images,
)
from app.core.language_filter import detect_language
from app.collectors.vinted_scraper import VintedScraper
from app.collectors.zebradex_prices import ZebraDexClient
from app.services.price_index import (
    sync_series_batch, refresh_series_catalog, index_stats, find_price_for_listing,
)
from app.collectors.card_images import ClientImagesCartes
from app.collectors.catalog_sources import SondeurDeSources
from app.collectors import opcg_dataset
from app.services import catalog_import
from app.services import card_catalog

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _run_check_with_own_session():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


def _sync_prices_with_own_session(batch_size: int):
    db = SessionLocal()
    try:
        sync_series_batch(db, batch_size=batch_size)
    finally:
        db.close()


@router.post("/run-check-now")
def run_check_now(background_tasks: BackgroundTasks):
    """Declenche un cycle de collecte immediatement, en tache de fond."""
    background_tasks.add_task(_run_check_with_own_session)
    return {"status": "cycle de verification lance en arriere-plan"}


@router.post("/sync-prices")
def sync_prices(background_tasks: BackgroundTasks, batch_size: int = Query(6, ge=1, le=30)):
    """
    Synchronise un lot de series ZebraDex vers l'index local de prix.
    Progressif par design : a 6s par requete, 30 series = 3 min. Appeler
    plusieurs fois (ou laisser le scheduler faire) pour couvrir les 158
    series.
    """
    background_tasks.add_task(_sync_prices_with_own_session, batch_size)
    return {"status": f"synchronisation de {batch_size} serie(s) lancee en arriere-plan"}


@router.post("/rescore-unpriced")
def rescore_unpriced(
    limit: int = Query(120, ge=1, le=2000),
    include_uncertain: bool = Query(True, description="Inclure aussi les prix en confiance faible"),
):
    """
    Retente le rapprochement sur les annonces sans prix de reference et,
    par defaut, sur celles dont le prix a ete trouve en confiance faible.
    Tourne aussi automatiquement a chaque cycle ; cet endpoint sert a voir
    l'effet tout de suite apres une amelioration du moteur de matching.
    """
    db = SessionLocal()
    try:
        return {"status": "ok", **rescore_unpriced_listings(
            db, limit=limit, include_uncertain=include_uncertain
        )}
    finally:
        db.close()


@router.post("/refilter-language")
def refilter_language_now(limit: int = Query(2000, ge=1, le=10000)):
    """
    Repasse le filtre de langue sur les annonces deja en base. A lancer
    apres une amelioration du filtre : sans ca, seules les NOUVELLES
    annonces en beneficient.
    """
    db = SessionLocal()
    try:
        return {"status": "ok", **refilter_language(db, limit=limit)}
    finally:
        db.close()


def _check_availability_with_own_session(limit: int):
    db = SessionLocal()
    try:
        check_vinted_availability(db, limit=limit)
    finally:
        db.close()


@router.post("/check-availability")
def check_availability_now(background_tasks: BackgroundTasks, limit: int = Query(10, ge=1, le=200)):
    """
    Verifie que les meilleures annonces Vinted sont toujours en ligne et
    masque celles qui ont disparu.

    Lance en tache de fond : 8 s de politesse par annonce, soit plus de
    cinq minutes des 40 annonces. Faire attendre la reponse HTTP aussi
    longtemps la faisait echouer (meme raison que la recherche ciblee, voir
    app/services/search_jobs.py). Suivre l'avancement dans les logs Render.
    """
    background_tasks.add_task(_check_availability_with_own_session, limit)
    return {"status": f"verification de {limit} annonce(s) lancee en arriere-plan"}


@router.post("/refresh-series-catalog")
def refresh_catalog():
    """Redecouvre la liste des series ZebraDex (158 au 25/08/2026)."""
    db = SessionLocal()
    try:
        added = refresh_series_catalog(db)
        return {"status": "ok", "nouvelles_series": added, **index_stats(db)}
    finally:
        db.close()


@router.get("/price-index-status")
def price_index_status():
    """Avancement de la construction de l'index de prix."""
    db = SessionLocal()
    try:
        return index_stats(db)
    finally:
        db.close()


@router.get("/test-price-match")
def test_price_match(title: str = Query(..., description="Titre d'annonce a tester")):
    """
    Teste le matching d'un titre contre l'index, sans rien enregistrer.
    Utile pour comprendre pourquoi une annonce n'a pas de prix.
    """
    db = SessionLocal()
    try:
        match = find_price_for_listing(db, title)
        if match is None:
            return {"matched": False, "title": title,
                    "hint": "aucune carte de l'index ne correspond - index peut-etre incomplet, voir /price-index-status"}
        return {"matched": True, "title": title, **match.to_dict()}
    finally:
        db.close()


@router.get("/test-language")
def test_language(title: str = Query(..., description="Titre d'annonce a tester")):
    """
    Explique pourquoi une annonce est jugee francaise ou non. Sans ca, une
    annonce ecartee disparait du dashboard sans qu'on sache pourquoi.
    """
    verdict = detect_language(title)
    return {"title": title, **verdict.to_dict()}


@router.get("/debug-vinted")
def debug_vinted(search_text: Optional[str] = None):
    search_text = search_text or settings.vinted_search_text
    """Diagnostic lecture seule du scraper Vinted."""
    scraper = VintedScraper(request_delay_seconds=settings.vinted_request_delay_seconds)
    return scraper.diagnostic_fetch(search_text=search_text)


@router.get("/debug-zebradex")
def debug_zebradex(series_url: Optional[str] = None):
    """
    Diagnostic lecture seule de ZebraDex. Sans parametre : teste la page
    listant les series. Avec `series_url` : teste le parsing d'une serie.
    """
    return ZebraDexClient().diagnostic_fetch(series_url=series_url)

# --------------------------------------------------------------------------
# Catalogue de cartes (exploration par theme / tendances / visuels)
# --------------------------------------------------------------------------


@router.post("/snapshot-card-prices")
def snapshot_card_prices(limit: Optional[int] = Query(None, ge=1)):
    """Enregistre le releve de prix du jour pour tout le catalogue.

    A declencher une fois par jour. C'est la SEULE facon d'avoir un jour un
    historique : la source ne publie qu'un prix instantane, et le passe ne
    se reconstitue pas apres coup. Chaque jour ou cet appel n'a pas lieu est
    un trou definitif dans la courbe.

    Le scheduler l'appelle automatiquement, cette route sert au rattrapage
    manuel et au premier amorcage.
    """
    db = SessionLocal()
    try:
        return card_catalog.enregistrer_releve_du_jour(db, limite=limit)
    finally:
        db.close()


@router.post("/enrich-card-images")
def enrich_card_images_now(limit: int = Query(40, ge=1, le=200)):
    """Complete le visuel des cartes qui n'en ont pas encore.

    Progressif a dessein : quelques dizaines par appel, pour ne pas marteler
    l'API ni depasser les limites d'un hebergement gratuit. A relancer
    plusieurs fois pour couvrir un gros catalogue.
    """
    db = SessionLocal()
    try:
        return enrich_card_images(db, limit=limit)
    finally:
        db.close()


@router.post("/recompute-card-fields")
def recompute_card_fields(limit: int = Query(5000, ge=1, le=50000)):
    """Recalcule les champs derives des cartes deja en base : les themes et
    la cle de recherche.

    A LANCER UNE FOIS apres le deploiement : les cartes synchronisees avant
    l'existence de ces colonnes n'en portent aucune, donc leurs themes sont
    vides et la recherche libre ne les trouve pas. A relancer ensuite apres
    chaque ajout de theme. Sans ce rattrapage, il faudrait attendre la
    resynchronisation complete du catalogue, qui prend des jours au rythme
    impose a ZebraDex.
    """
    db = SessionLocal()
    try:
        return card_catalog.recalculer_champs_derives(db, limite=limit)
    finally:
        db.close()


@router.post("/import-catalog")
async def import_catalog(request: Request):
    """Remplit le catalogue depuis un fichier CSV ou JSON.

    Le catalogue n'avait qu'une seule facon d'etre rempli, et quand cette
    source s'est revelee ne pas couvrir One Piece il n'est rien reste. Ce
    chemin-ci ne depend ni du reseau ni de la forme d'une page : on donne
    un fichier, il remplit.

    Le corps de la requete EST le fichier — CSV ou JSON, reconnu tout seul.
    Pas de formulaire, pas de dependance supplementaire :

        curl -X POST http://localhost:8000/api/admin/import-catalog \
             --data-binary @cartes.csv

    Colonnes : card_code, display_name, price_eur (obligatoires),
    series_name, rarity (facultatives). Les intitules courants en francais
    sont acceptes — « code », « nom », « prix », « serie », « rarete ».

    Chaque ligne refusee est rendue avec son numero et sa raison.
    """
    corps = (await request.body()).decode("utf-8", errors="replace")

    lignes, erreur = catalog_import.analyser(corps)
    if erreur:
        raise HTTPException(status_code=400, detail=erreur)
    if not lignes:
        raise HTTPException(status_code=400, detail="aucune ligne exploitable")

    db = SessionLocal()
    try:
        return catalog_import.importer_catalogue(db, lignes)
    finally:
        db.close()


@router.post("/load-opcg-catalog")
def load_opcg_catalog(
    rafraichir: bool = Query(
        False,
        description="Aller rechercher la derniere version publiee au lieu de "
                    "lire l'instantane versionne du depot.",
    ),
):
    """Remplit le catalogue depuis le releve de la liste OFFICIELLE du jeu.

    C'est le chemin a prendre pour partir d'un catalogue vide : il donne les
    ~3870 fiches reelles (code, nom, serie, rarete, et le visuel qui se
    deduit du code), sans fichier a fournir ni page a explorer.

    Sans parametre, il lit l'instantane versionne dans le depot : hors ligne,
    immediat, et identique a ce que les tests ont valide.
    `?rafraichir=true` va chercher la derniere version publiee et reecrit
    l'instantane au passage.

        curl -X POST http://localhost:8000/api/admin/load-opcg-catalog

    CE QU'IL NE FAIT PAS : cette source ne publie aucun prix. Les cartes
    entrent donc sans prix de reference, et le rapport le dit (`sans_prix`).
    Les marges et les scores d'affaire resteront vides jusqu'a ce qu'une
    source de prix soit branchee — par exemple un import de fichier avec une
    colonne prix, qui met a jour les memes fiches sans les dupliquer.
    """
    db = SessionLocal()
    try:
        return opcg_dataset.charger_catalogue(db, rafraichir=rafraichir)
    finally:
        db.close()


@router.get("/debug-catalog-sources")
def debug_catalog_sources():
    """Quelles sources peuvent alimenter le catalogue One Piece ?

    ZebraDex ne couvre PAS One Piece : verifie le 15/10/2026, son sitemap FR
    ne contient que /fr/tcg/pokemon et /fr/tcg/one-piece rend 404. Le
    catalogue restait donc vide, et avec lui tout ce qui en depend — prix de
    reference, exploration par theme, visuels deduits du code carte.

    Cette route interroge les sources candidates et rapporte ce que chacune
    repond, SANS rien parser. Elle existe parce que l'environnement de
    developpement n'a pas d'acces sortant vers ces hotes, alors que ce
    backend, lui, en a un : on s'en sert pour constater la forme reelle
    avant d'ecrire le parseur.

    C'est exactement ce qui a manque la premiere fois. La couverture One
    Piece de ZebraDex avait ete supposee, jamais constatee.

    Copier la reponse entiere dans la conversation.
    """
    return SondeurDeSources().sonder_tout()


@router.get("/debug-card-images")
def debug_card_images(code: str = Query("OP01-001"), nom: str = Query("")):
    """Detail de CHAQUE adresse essayee pour un code de carte : code HTTP et
    type de contenu.

    Le format d'adresse n'a pas pu etre verifie contre l'hote reel :
    l'environnement de developpement n'a pas d'acces sortant vers
    en.onepiece-cardgame.com. Si aucune image ne remonte, c'est par ici
    qu'il faut passer — la reponse dit s'il s'agit d'un 404 (format
    d'adresse a corriger via CARD_IMAGE_BASE_URL), d'un 403 (hote qui
    refuse) ou d'une erreur reseau. Meme demarche que debug-vinted et
    debug-zebradex.
    """
    return ClientImagesCartes().diagnostic(code, nom)
