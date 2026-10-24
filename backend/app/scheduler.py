import logging
from datetime import datetime, timedelta

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
    from app.services.catalog_prices import (
        appliquer_prix, oublier_les_prix_non_confirmes,
    )

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
            series_en_echec = 0
            debut_des_prix = datetime.utcnow()
            for serie in client.series():
                try:
                    prix.extend(client.prix_de_serie(serie))
                except Exception as erreur:  # noqa: BLE001
                    series_en_echec += 1
                    logger.warning("Prix : serie %s illisible (%s)", serie, erreur)
            if prix:
                rapport = appliquer_prix(db, prix)
                logger.info("Prix : %d chiffree(s), %d sans fiche, %d rarete(s) "
                            "opposee(s), %d variante(s) non rattachee(s), "
                            "%d encore sans prix",
                            rapport["chiffrees"], rapport["sans_fiche"],
                            rapport["raretes_opposees"],
                            rapport["variantes_sans_rang"],
                            rapport["sans_prix_restantes"])
                for conflit in rapport["conflits"][:10]:
                    logger.warning(
                        "Prix : %s rang %s laisse sans prix, revendique par %s "
                        "(fiche %s / candidats %s)",
                        conflit["code"], conflit.get("rang", 0),
                        conflit["montants"],
                        conflit.get("rarete_fiche") or "rarete inconnue",
                        [(c["rarete"], c["nom"]) for c in conflit.get("candidats") or []])

                # Un prix mal rapproche par une version precedente peut
                # n'avoir plus aucune candidature legitime : plus rien ne
                # vient l'ecraser. Ce balayage est la seule chose qui
                # l'enleve. Il ne joue que si TOUT a ete lu : une serie
                # manquee n'est pas une serie perimee.
                if series_en_echec:
                    logger.warning("Prix : balayage reporte, %d serie(s) non lue(s)",
                                   series_en_echec)
                else:
                    oubli = oublier_les_prix_non_confirmes(db, debut_des_prix)
                    if oubli["oubliees"]:
                        logger.info("Prix : %d prix perime(s) oublie(s)",
                                    oubli["oubliees"])
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


def _job_amorcage():
    """Remplit un serveur neuf sans que personne n'intervienne.

    Sur un hebergement, aucun script de demarrage ne tourne : une version
    fraichement deployee servirait un catalogue vide jusqu'a la nuit, et
    meme la nuit venue, la tache de 02:00 ne charge que les noms et les
    prix — elle suppose le catalogue de base deja la. Personne ne taperait
    les commandes qui manquent.

    QUAND CETTE TACHE AGIT
    ----------------------
    Le catalogue de base est charge s'il ne contient AUCUNE carte One Piece
    — reconnaissable a sa langue, que seuls les chargements One Piece
    renseignent. Les noms et les prix le sont si AUCUN prix de reference
    n'est encore en base. Sinon elle ne fait rien : la relancer a chaque
    reveil d'un serveur gratuit ne coute qu'un comptage.

    Elle se repare d'elle-meme : un chargement interrompu par une mise en
    veille laisse la base sans prix, et le reveil suivant le reprend.
    """
    from app.collectors import opcg_dataset
    from app.models import MarketCardPrice
    from app.services.catalog_prices import SOURCE as SOURCE_PRIX

    # Ouvrir la session DANS la garde : une base injoignable au reveil est
    # justement le cas ou cette tache doit se taire et laisser le serveur
    # repondre, plutot que de faire remonter l'erreur.
    try:
        db = SessionLocal()
    except Exception:  # noqa: BLE001
        logger.exception("Amorcage : base injoignable, nouvel essai au prochain demarrage")
        return
    try:
        one_piece = (db.query(MarketCardPrice)
                     .filter(MarketCardPrice.language.isnot(None)).count())
        if not one_piece:
            rapport = opcg_dataset.charger_catalogue(db)
            logger.info("Amorcage : catalogue de base charge (%s carte(s), %s)",
                        rapport.get("importees"), rapport.get("origine"))
        chiffrees = (db.query(MarketCardPrice)
                     .filter(MarketCardPrice.source == SOURCE_PRIX).count())
    except Exception:  # noqa: BLE001 - un amorcage rate ne doit pas tuer le serveur
        logger.exception("Amorcage : chargement du catalogue de base echoue")
        return
    finally:
        db.close()

    if chiffrees:
        logger.info("Amorcage : %d prix de reference deja en base, rien a faire",
                    chiffrees)
        return
    logger.info("Amorcage : aucun prix de reference, chargement des noms et des prix")
    _job_sources_du_jour()


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

    # Trente secondes de delai : le serveur doit d'abord ouvrir son port et
    # repondre au controle de sante de l'hebergeur. Un chargement lance
    # pendant le demarrage le retarderait, et l'hebergeur pourrait conclure
    # a un echec de deploiement.
    if settings.amorcage_automatique:
        scheduler.add_job(
            _job_amorcage,
            "date",
            run_date=datetime.now() + timedelta(seconds=30),
            id="amorcage",
            replace_existing=True,
        )
        logger.info("Amorcage automatique programme dans 30 s")

    scheduler.start()
    logger.info(
        "Scheduler demarre : verification toutes les %d minutes, sources FR "
        "a 02:00, releve de prix quotidien a 03:00, visuels toutes les 30 "
        "minutes",
        settings.check_interval_minutes,
    )
