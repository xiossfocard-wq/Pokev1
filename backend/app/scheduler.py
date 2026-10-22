import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.database import SessionLocal
from app.pipeline import run_full_check, enrich_card_images
from app.services.card_catalog import enregistrer_releve_du_jour

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _job():
    db = SessionLocal()
    try:
        run_full_check(db)
    finally:
        db.close()


def _job_releve_quotidien():
    """Un releve de prix par jour, pour tout le catalogue.

    C'est ce qui rend les tendances de fond possibles : la source ne publie
    qu'un prix instantane et une variation 7 jours, et le passe ne se
    reconstitue pas apres coup. Chaque jour manque est un trou definitif
    dans la courbe, d'ou une tache dediee plutot qu'un calcul a la demande.
    """
    db = SessionLocal()
    try:
        enregistrer_releve_du_jour(db)
    except Exception:  # noqa: BLE001 - une tache de fond ne doit pas tuer le scheduler
        logger.exception("Releve de prix quotidien echoue")
    finally:
        db.close()


def _job_sources_du_jour():
    """Rafraichit les noms francais puis les prix, une fois par nuit.

    POURQUOI LA NUIT, ET PAS DANS LE CYCLE RAPIDE
    ---------------------------------------------
    Les deux sources se lisent page par page : 37 series cote liste
    officielle, plusieurs centaines de pages cote prix, avec une pause
    entre chaque pour ne pas marteler un site communautaire. Faire ca
    toutes les vingt minutes serait aussi inutile qu'impoli — un prix de
    reference ne bouge pas a ce rythme.

    L'ORDRE N'EST PAS ARBITRAIRE
    ----------------------------
    Les noms d'abord : ils creent les fiches manquantes et etablissent la
    cle (code, rang de variante) sur laquelle les prix viennent se poser.
    Les prix ensuite, a 02:00, pour que le releve quotidien de 03:00 porte
    sur des valeurs fraiches — un jour manque dans cette courbe est un trou
    definitif, elle ne se reconstitue pas apres coup.

    Un echec ne doit rien emporter : chaque source est tentee separement,
    et le catalogue garde ce qu'il avait.
    """
    from app.collectors.cardlist_fr import ClientListeFR
    from app.collectors.opecards_prices import ClientOPECards
    from app.services.catalog_fr import appliquer_noms_francais
    from app.services.catalog_prices import appliquer_prix

    db = SessionLocal()
    try:
        try:
            client = ClientListeFR()
            cartes = []
            for serie in client.series():
                try:
                    cartes.extend(client.cartes_de_serie(serie))
                except Exception as erreur:  # noqa: BLE001
                    logger.warning("Noms FR : serie %s illisible (%s)", serie, erreur)
            if cartes:
                rapport = appliquer_noms_francais(db, cartes)
                logger.info("Noms FR : %d renommee(s), %d creee(s)",
                            rapport["renommees"], rapport["creees"])
            else:
                logger.warning("Noms FR : aucune carte lue, catalogue inchange")
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Rafraichissement des noms francais echoue")

        try:
            client = ClientOPECards()
            prix = []
            for serie in client.series():
                try:
                    prix.extend(client.prix_de_serie(serie))
                except Exception as erreur:  # noqa: BLE001
                    logger.warning("Prix : serie %s illisible (%s)", serie, erreur)
            if prix:
                rapport = appliquer_prix(db, prix)
                logger.info("Prix : %d chiffree(s), %d sans fiche, %d rarete(s) "
                            "opposee(s), %d encore sans prix",
                            rapport["chiffrees"], rapport["sans_fiche"],
                            rapport["raretes_opposees"],
                            rapport["sans_prix_restantes"])
                for conflit in rapport["conflits"][:10]:
                    logger.warning("Prix : %s reclame a %s EUR ET %s EUR, "
                                   "le plus bas retenu", conflit["code"],
                                   conflit["concurrents"][1],
                                   conflit["concurrents"][0])
                for ecart in rapport["ecarts_suspects"][:10]:
                    logger.warning("Prix : ecart x%s sur %s (%s EUR -> %s EUR)",
                                   ecart["facteur"], ecart["code"],
                                   ecart["avant"], ecart["apres"])
            else:
                logger.warning("Prix : aucun prix lu, catalogue inchange")
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("Rafraichissement des prix echoue")
    finally:
        db.close()


def _job_images():
    """Complete le visuel des cartes, par petits lots.

    Separe du cycle principal parce qu'il interroge une autre source a un
    autre rythme : le catalogue compte des milliers de cartes, les images se
    remplissent sur plusieurs heures sans bloquer la chasse aux annonces.
    """
    db = SessionLocal()
    try:
        enrich_card_images(db, limit=40)
    except Exception:  # noqa: BLE001
        logger.exception("Enrichissement des visuels echoue")
    finally:
        db.close()


def start_scheduler():
    if not settings.scheduler_enabled:
        logger.info(
            "Scheduler desactive (SCHEDULER_ENABLED=false) : aucune collecte "
            "automatique. Les routes /api/admin/* restent utilisables pour "
            "declencher un passage a la main."
        )
        return

    scheduler.add_job(
        _job,
        "interval",
        minutes=settings.check_interval_minutes,
        id="deal_check",
        replace_existing=True,
        next_run_time=None,  # on laisse APScheduler programmer le premier run après l'intervalle
    )

    # 03:00 : creux d'activite, et apres la synchronisation nocturne des
    # prix, donc le releve porte sur des valeurs fraiches.
    scheduler.add_job(
        _job_releve_quotidien,
        "cron",
        hour=3,
        minute=0,
        id="card_price_snapshot",
        replace_existing=True,
    )

    # 02:00 : avant le releve de 03:00, pour qu'il porte sur des prix du
    # jour meme.
    scheduler.add_job(
        _job_sources_du_jour,
        "cron",
        hour=2,
        minute=0,
        id="sources_fr",
        replace_existing=True,
    )

    scheduler.add_job(
        _job_images,
        "interval",
        minutes=30,
        id="card_images",
        replace_existing=True,
        next_run_time=None,
    )

    scheduler.start()
    logger.info(
        "Scheduler demarre : verification toutes les %d minutes, sources FR "
        "a 02:00, releve de prix quotidien a 03:00, visuels toutes les 30 "
        "minutes",
        settings.check_interval_minutes,
    )
