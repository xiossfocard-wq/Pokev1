from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.models import MarketCardPrice
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
import requests

from app.collectors.card_images import (
    USER_AGENT as USER_AGENT_IMAGES, ClientImagesCartes, code_canonique,
    urls_candidates,
)
from app.collectors.catalog_sources import SondeurDeSources
from app.collectors import opcg_dataset
from app.collectors.cardlist_fr import ClientListeFR, rang_de_parallele
from app.services import catalog_fr
from app.collectors.opecards_prices import ClientOPECards
from app.services import catalog_prices
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
def run_check_now(
    background_tasks: BackgroundTasks,
    attendre: bool = Query(
        False,
        description="Attendre la fin de la collecte et rendre son resultat, "
                    "au lieu de rendre la main tout de suite.",
    ),
):
    """Declenche un cycle de collecte immediatement.

    Par defaut en tache de fond. Avec « attendre=true », la reponse arrive
    a la fin du cycle et dit combien d'annonces il a apporte : c'est ce que
    le script de demarrage demande, parce qu'il comptait les annonces
    aussitot l'appel rendu — avant meme que la collecte n'ait commence — et
    concluait donc toujours « aucune annonce ».
    """
    if not attendre:
        background_tasks.add_task(_run_check_with_own_session)
        return {"status": "cycle de verification lance en arriere-plan"}

    from app.models import Listing

    db = SessionLocal()
    try:
        avant = db.query(Listing).count()
    finally:
        db.close()
    _run_check_with_own_session()
    db = SessionLocal()
    try:
        apres = db.query(Listing).count()
    finally:
        db.close()
    return {"status": "cycle termine", "annonces_avant": avant,
            "annonces_apres": apres, "nouvelles": apres - avant}


@router.get("/controle-qualite")
def controle_qualite():
    """Controle la justesse des prix et la langue des cartes, sur la base reelle.

    Ne corrige rien : rapporte les anomalies avec des exemples, pour qu'elles
    puissent etre verifiees carte par carte. Variantes moins cheres que leur
    base, prix aberrants pour leur rarete, prix venus d'autres sources,
    cartes anglaises dans une serie francaise, langue fausse, annonces que
    le filtre actuel ecarterait.

        http://localhost:8000/api/admin/controle-qualite
    """
    from app.services.controle_qualite import controler

    db = SessionLocal()
    try:
        return controler(db)
    finally:
        db.close()


@router.get("/diagnostic")
def diagnostic(
    sources: bool = Query(
        True,
        description="Tester aussi Vinted et les sites officiels depuis cette "
                    "machine (une vingtaine de secondes).",
    ),
):
    """Bilan de sante complet, a ouvrir dans un navigateur.

    Catalogue, prix, visuels, annonces, reglages de collecte, ce que Vinted
    et les sites officiels repondent DEPUIS CETTE MACHINE, et les dernieres
    erreurs du journal. Une seule adresse au lieu d'une commande par
    hypothese. Aucun secret n'y figure.

        http://localhost:8000/api/admin/diagnostic
    """
    from app.services.diagnostic import etablir_diagnostic

    db = SessionLocal()
    try:
        return etablir_diagnostic(db, avec_sources=sources)
    finally:
        db.close()


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
    from app.scheduler import rafraichissement_en_cours

    db = SessionLocal()
    try:
        return {**index_stats(db), "refresh_in_progress": rafraichissement_en_cours()}
    finally:
        db.close()


@router.post("/refresh-sources")
def refresh_sources():
    """Rafraichit les noms francais et les prix EN ARRIERE-PLAN.

    Rend la main tout de suite : le site reste utilisable pendant les
    dizaines de minutes que prend la lecture des sources, et les prix se
    mettent a jour sous les yeux de l'utilisateur. Un seul rafraichissement
    a la fois — un second appel pendant le premier ne relance rien.

        curl -X POST http://localhost:8000/api/admin/refresh-sources
    """
    from app.scheduler import lancer_sources_en_arriere_plan

    lance = lancer_sources_en_arriere_plan()
    return {
        "lance": lance,
        "message": ("rafraichissement lance en arriere-plan" if lance
                    else "un rafraichissement est deja en cours"),
    }


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


@router.post("/deduce-card-images")
def deduce_card_images():
    """Pose d'un coup les visuels qui se deduisent du code.

    Un echantillon reparti est verifie ; si au moins trois sur quatre
    repondent avec le meme format, il est etendu a toutes les cartes sans
    visuel. Quelques secondes, au lieu de dix a quarante minutes de
    verification carte par carte. Les adresses deduites sont ensuite
    verifiees en arriere-plan, et retirees si le site les refuse.

        curl -X POST http://localhost:8000/api/admin/deduce-card-images
    """
    from app.pipeline import deduire_visuels

    db = SessionLocal()
    try:
        return deduire_visuels(db)
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


@router.get("/fr-series")
def fr_series():
    """Les series francaises a charger, des deux sources.

    Existe pour que le chargement puisse se faire SERIE PAR SERIE et
    afficher sa progression. Tout charger d'un seul appel laissait le
    terminal muet pendant parfois une heure — et un ecran qui ne bouge pas
    pendant une heure se lit comme un plantage, pas comme du travail.

    Chaque source est tentee separement : si l'une est injoignable, l'autre
    reste utilisable.
    """
    resultat = {}
    for cle, fabrique in (("officielles", ClientListeFR), ("prix", ClientOPECards)):
        try:
            resultat[cle] = fabrique().series()
        except Exception as erreur:   # noqa: BLE001
            resultat[cle] = {}
            resultat[f"{cle}_erreur"] = str(erreur)
    return resultat


@router.post("/load-fr-names")
def load_fr_names(
    series: str = Query(
        "",
        description="Valeurs de serie a charger, separees par des virgules "
                    "(ex. « 622117,622116 »). Vide = toutes celles que le "
                    "menu deroulant du site propose.",
    ),
):
    """Passe le catalogue aux noms FRANCAIS, depuis la liste officielle.

    Les noms venaient jusqu'ici d'un releve de la liste ANGLAISE. Pour les
    personnages cela passait — « Roronoa Zoro » s'ecrit pareil des deux
    cotes — mais c'est faux la ou ca compte : l'anglais « Buggy » s'appelle
    « Baggy » en francais, « Hive » s'appelle « Ruche », et les cartes
    Evenement sont integralement traduites. Un vendeur francais qui ecrit
    « Baggy » ne rencontrait donc jamais la fiche.

    L'operation RENOMME les fiches existantes au lieu d'en creer de
    nouvelles : le catalogue est indexe sur (code, nom), et un import
    classique aurait laisse « Buggy » et « Baggy » cote a cote pour la meme
    carte. Les prix de reference ne sont pas touches.

    Les visuels sont ranges au passage : la page publie leur adresse exacte,
    ce qui evite un aller-retour reseau par carte.

        curl -X POST http://localhost:8000/api/admin/load-fr-names
    """
    client = ClientListeFR()
    try:
        voulues = [s.strip() for s in series.split(",") if s.strip()]
        if not voulues:
            voulues = list(client.series().keys())
    except Exception as erreur:   # noqa: BLE001 - on rend la raison, on ne masque pas
        raise HTTPException(
            status_code=502,
            detail=f"liste des series illisible : {erreur}",
        )

    cartes, echecs = [], []
    for valeur in voulues:
        try:
            cartes.extend(client.cartes_de_serie(valeur))
        except Exception as erreur:   # noqa: BLE001
            # Une serie qui echoue ne doit pas emporter les autres, mais
            # elle doit etre DITE : un rapport qui tairait les series
            # manquantes se lirait comme un passage complet.
            echecs.append({"serie": valeur, "raison": str(erreur)})

    if not cartes:
        raise HTTPException(
            status_code=502,
            detail={"message": "aucune carte lue", "echecs": echecs},
        )

    db = SessionLocal()
    try:
        rapport = catalog_fr.appliquer_noms_francais(db, cartes)
    finally:
        db.close()

    rapport["series_demandees"] = len(voulues)
    rapport["series_en_echec"] = echecs
    return rapport


@router.post("/load-fr-prices")
def load_fr_prices(
    series: str = Query(
        "",
        description="Valeurs de serie a charger, separees par des virgules. "
                    "Vide = toutes les series FRANCAISES proposees par le site.",
    ),
):
    """Ecrit les prix de reference en euros, depuis OPECards.fr.

    C'etait la moitie manquante : le catalogue savait quelles cartes
    existent et comment elles s'appellent, mais pas ce qu'elles valent —
    donc aucune marge, aucun score, aucune bonne affaire.

    La cle de rapprochement est (code carte, RANG de variante). Pas le nom,
    qui differe d'une source a l'autre ; pas le code seul, parce qu'un code
    designe jusqu'a quatre cartes : les trois impressions de OP15-118-SEC
    valent 10,50 €, 22,00 € et 695,00 €.

    Une carte absente du catalogue n'est PAS creee ici : cette source dit ce
    que valent les cartes, pas lesquelles existent. Lancer d'abord
    POST /api/admin/load-fr-names.

        curl -X POST http://localhost:8000/api/admin/load-fr-prices
    """
    client = ClientOPECards()
    try:
        voulues = [s.strip() for s in series.split(",") if s.strip()]
        if not voulues:
            voulues = list(client.series().keys())
    except Exception as erreur:   # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"liste des series illisible : {erreur}",
        )

    prix, echecs = [], []
    for valeur in voulues:
        try:
            prix.extend(client.prix_de_serie(valeur))
        except Exception as erreur:   # noqa: BLE001
            echecs.append({"serie": valeur, "raison": str(erreur)})

    if not prix:
        raise HTTPException(
            status_code=502,
            detail={"message": "aucun prix lu", "echecs": echecs},
        )

    db = SessionLocal()
    try:
        rapport = catalog_prices.appliquer_prix(db, prix)
    finally:
        db.close()

    rapport["series_demandees"] = len(voulues)
    rapport["series_en_echec"] = echecs
    return rapport


@router.get("/diagnostic-variantes")
def diagnostic_variantes(
    series: str = Query(..., description="UNE valeur de serie OPECards."),
    limite: int = Query(5, ge=1, le=40,
                        description="Nombre de codes examines au plus."),
    toutes: bool = Query(
        False,
        description="Examiner aussi les codes dont toutes les mentions ont "
                    "deja un rang. Par defaut, seuls les codes portant une "
                    "mention encore inconnue sont examines.",
    ),
):
    """Mesure si les illustrations alternatives peuvent etre appariees.

    CE QUE CETTE ROUTE N'ECRIT PAS
    ------------------------------
    Rien. Aucun prix, aucune fiche. Elle RAPPORTE ce que les images disent,
    et c'est tout.

    LE PROBLEME QU'ELLE INSTRUIT
    ----------------------------
    La liste officielle declare les alternatives — « OP17-005_p2 » est
    releve sur sa page. Des fiches existent donc, et elles sont vides. La
    source des prix donne « (Parallele) » et « (Manga) » pour le meme code,
    a 5,80 EUR et 500 EUR. Les effectifs concordent ; seul l'appariement
    manque.

    Et dans les champs de la page officielle — code, rarete, type, nom — les
    deux alternatives sont rigoureusement identiques. Rien n'y designe celle
    qui porte l'illustration manga. La seule information qui les distingue
    est l'image, donc on compare les images.

    Decreter que « (Manga) » est la deuxieme alternative plutot que la
    premiere poserait 500 EUR sur une carte qui en vaut 5,80. Cette route
    existe pour remplacer cette hypothese par une mesure.

        curl "http://localhost:8000/api/admin/diagnostic-variantes?series=819"
    """
    from app.collectors.opecards_prices import VARIANTE_SANS_RANG
    from app.services import appariement_variantes as app_var

    client = ClientOPECards()
    try:
        releve = client.prix_de_serie(series.strip())
    except Exception as erreur:   # noqa: BLE001
        raise HTTPException(status_code=502,
                            detail=f"serie illisible : {erreur}")

    # Les mentions sans rang, regroupees par code, plus l'impression
    # ordinaire du meme code quand la serie la donne aussi.
    #
    # TOUTES les impressions d'un code, quel que soit leur rang. Ne garder
    # que l'ordinaire et les mentions inconnues rendait la route aveugle
    # des que certaines mentions avaient recu un rang : pour un code
    # « ordinaire + Parallele + Super Leader Parallele », elle comparait
    # deux impressions a trois fiches officielles, concluait « effectifs
    # differents », et ne pouvait donc jamais mesurer la mention qui restait
    # a etablir — precisement celle pour laquelle elle existe.
    par_code: dict = {}
    for carte in releve:
        code = code_canonique(carte.card_code)
        if not code:
            continue
        par_code.setdefault(code.upper(), []).append(carte)

    # Par defaut, seuls les codes qui ont encore quelque chose a apprendre.
    if not toutes:
        par_code = {code: cartes for code, cartes in par_code.items()
                    if any(c.rang_variante == VARIANTE_SANS_RANG for c in cartes)}

    db = SessionLocal()
    session = requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT_IMAGES)
    rapports, examines = [], 0
    try:
        for code, cartes in sorted(par_code.items()):
            if examines >= limite:
                break
            # Un seul prix pour ce code : rien a departager.
            if len(cartes) < 2:
                continue

            fiches = [l for l in db.query(MarketCardPrice)
                      .filter(MarketCardPrice.card_code == code).all()]
            if len(fiches) < 2:
                continue
            examines += 1

            officielles, binaires_off = {}, {}
            for fiche in fiches:
                rang = rang_de_parallele(fiche.name_slug)
                donnees = _telecharger(session, fiche.image_url) \
                    if fiche.image_url else None
                if donnees is None:
                    for essai in urls_candidates(code, rang=rang):
                        donnees = _telecharger(session, essai)
                        if donnees:
                            break
                officielles[rang] = app_var.empreinte_perceptive(donnees)
                binaires_off[rang] = app_var.empreinte_binaire(donnees)

            boutique, binaires_bou = {}, {}
            for carte in cartes:
                marque = carte.variante or ""
                donnees = _telecharger(session, carte.image_url)
                boutique[marque] = app_var.empreinte_perceptive(donnees)
                binaires_bou[marque] = app_var.empreinte_binaire(donnees)

            resultat = app_var.apparier(officielles, boutique)
            resultat["code"] = code
            resultat["nom"] = fiches[0].display_name
            # L'egalite BINAIRE est le cas le plus simple : si la boutique
            # reheberge le fichier officiel, aucune comparaison d'image
            # n'est necessaire et l'appariement est certain.
            resultat["fichiers_identiques"] = sorted(
                set(v for v in binaires_off.values() if v)
                & set(v for v in binaires_bou.values() if v))
            resultat["mentions"] = sorted(boutique)
            resultat["rangs_officiels"] = sorted(officielles)
            rapports.append(resultat)
    finally:
        db.close()

    etablis = [r for r in rapports if r["fiable"]]
    return {
        "serie": series,
        "pillow_disponible": app_var.pillow_disponible(),
        "codes_examines": examines,
        "appariements_etablis": len(etablis),
        "appariements_incertains": len(rapports) - len(etablis),
        "rapports": rapports,
        # Dit en une phrase si la methode tient sur cette serie, pour ne pas
        # avoir a interpreter des dizaines de distances.
        "conclusion": (
            "les images apparient de maniere fiable"
            if etablis and len(etablis) == len(rapports)
            else "les images ne suffisent pas a apparier de maniere sure"
            if rapports else "aucun code comparable sur cette serie"),
    }


def _telecharger(session, url: Optional[str], plafond: int = 2_000_000):
    """Les octets d'une image, ou None. Ne leve jamais.

    Un diagnostic qui s'interrompt sur la premiere image absente ne
    diagnostique rien.
    """
    if not url:
        return None
    try:
        reponse = session.get(url, timeout=20, stream=True)
        if reponse.status_code != 200:
            return None
        donnees = reponse.raw.read(plafond + 1, decode_content=True)
        return None if len(donnees) > plafond else donnees
    except Exception:   # noqa: BLE001
        return None


@router.post("/sweep-fr-prices")
def sweep_fr_prices(
    minutes: int = Query(
        ...,
        ge=1,
        description="Duree que vient de prendre le rechargement des prix. "
                    "Un prix non reconfirme depuis au moins ce delai est "
                    "considere comme perime et efface.",
    ),
):
    """Oublie les prix de reference que la source ne confirme plus.

    A LANCER APRES load-fr-prices, JAMAIS AVANT
    -------------------------------------------
    Recharger les prix ne suffit pas a reparer un mauvais rapprochement :
    un prix ecrit par erreur peut n'avoir plus aucune candidature
    legitime, donc plus rien pour l'ecraser. Il reste alors en base
    indefiniment — et c'est precisement le chiffre qui invente une bonne
    affaire qui n'existe pas.

    Cette route efface ces prix-la, et seulement eux : ceux que la source
    vient de passer sans reconfirmer. D'ou le parametre « minutes », qui
    doit couvrir la duree du rechargement : tout ce qui a ete touche
    pendant est garde.

    L'ordre compte. Vider les prix AVANT de recharger ouvrirait une fenetre
    sans aucun prix au catalogue, et un rechargement qui echoue en route la
    laisserait ouverte.

        curl -X POST "http://localhost:8000/api/admin/sweep-fr-prices?minutes=90"
    """
    db = SessionLocal()
    try:
        return catalog_prices.oublier_les_prix_non_confirmes(
            db, datetime.utcnow() - timedelta(minutes=minutes))
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
def debug_card_images(
    code: str = Query("OP01-001"),
    nom: str = Query(""),
    anglais: bool = Query(
        False,
        description="Essayer aussi le site anglais, comme pour une carte "
                    "absente de la liste francaise.",
    ),
):
    """Detail de CHAQUE adresse essayee pour un code de carte : code HTTP et
    type de contenu.

    Avec « anglais=true », le site anglais est essaye en premier — c'est le
    chemin des cartes qui n'existent pas dans le jeu francais, et le seul
    moyen de verifier son format d'adresse sans deviner :

        /api/admin/debug-card-images?code=OP01-001&anglais=true

    Le format d'adresse n'a pas pu etre verifie contre l'hote reel :
    l'environnement de developpement n'a pas d'acces sortant vers
    en.onepiece-cardgame.com. Si aucune image ne remonte, c'est par ici
    qu'il faut passer — la reponse dit s'il s'agit d'un 404 (format
    d'adresse a corriger via CARD_IMAGE_BASE_URL), d'un 403 (hote qui
    refuse) ou d'une erreur reseau. Meme demarche que debug-vinted et
    debug-zebradex.
    """
    return ClientImagesCartes().diagnostic(code, nom, anglais=anglais)
