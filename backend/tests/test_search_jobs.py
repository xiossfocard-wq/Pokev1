"""
Tests de la file de recherches ciblees (app/services/search_jobs.py).

Ce module est la reponse au bug "la barre de recherche ne rend rien dans le
navigateur" : la recherche etant beaucoup trop longue pour une requete HTTP
classique (289 s mesurees en prod), elle tourne desormais en tache de fond.
Ces tests verifient le contrat sur lequel le frontend s'appuie.
"""
import logging
import threading
import time
import unittest
from datetime import datetime, timedelta

from app.services.search_jobs import (
    MAX_JOBS,
    STATUS_DONE,
    STATUS_ERROR,
    SearchJobStore,
    JOB_RETENTION,
)


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class SearchJobStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = SearchJobStore()

    def test_submit_rend_la_main_immediatement(self):
        """Le POST ne doit jamais attendre la fin de la recherche."""
        started = threading.Event()
        release = threading.Event()

        def worker(job):
            started.set()
            release.wait(timeout=5)
            job.listing_ids = [1, 2, 3]

        debut = time.time()
        job = self.store.submit("pikachu", worker)
        duree = time.time() - debut

        self.assertLess(duree, 0.5)
        self.assertFalse(job.is_finished)
        self.assertTrue(started.wait(timeout=5))
        release.set()
        self.assertTrue(_wait_until(lambda: job.status == STATUS_DONE))
        self.assertEqual(job.listing_ids, [1, 2, 3])

    def test_resultat_disponible_apres_execution(self):
        def worker(job):
            job.listing_ids = [42]

        job = self.store.submit("dracaufeu ex", worker)
        self.assertTrue(_wait_until(lambda: job.status == STATUS_DONE))

        relu = self.store.get(job.id)
        self.assertIsNotNone(relu)
        self.assertEqual(relu.listing_ids, [42])
        self.assertEqual(relu.to_dict()["result_count"], 1)

    def test_une_erreur_ne_bloque_pas_la_file(self):
        # L'erreur est loguee avec sa stacktrace par le store : on la coupe
        # ici pour ne pas polluer la sortie des tests.
        logging.getLogger("app.services.search_jobs").setLevel(logging.CRITICAL)
        self.addCleanup(
            logging.getLogger("app.services.search_jobs").setLevel, logging.NOTSET
        )

        def worker_ko(job):
            raise RuntimeError("Vinted bloque")

        def worker_ok(job):
            job.listing_ids = [7]

        ko = self.store.submit("boum", worker_ko)
        self.assertTrue(_wait_until(lambda: ko.status == STATUS_ERROR))
        self.assertIn("Vinted bloque", ko.error)

        ok = self.store.submit("ensuite", worker_ok)
        self.assertTrue(_wait_until(lambda: ok.status == STATUS_DONE))

    def test_meme_recherche_relancee_ne_duplique_pas_le_job(self):
        """Recliquer sur "Chercher" pendant que ca tourne ne doit pas taper
        deux fois sur Vinted."""
        release = threading.Event()
        appels = []

        def worker(job):
            appels.append(job.query)
            release.wait(timeout=5)

        premier = self.store.submit("Pikachu", worker)
        second = self.store.submit("  pikachu  ", worker)
        self.assertEqual(premier.id, second.id)

        release.set()
        self.assertTrue(_wait_until(lambda: premier.status == STATUS_DONE))
        self.assertEqual(len(appels), 1)

    def test_soumissions_simultanees_ne_creent_qu_un_job(self):
        """Regression. La recherche de doublon prenait le verrou pour elle
        seule puis le relachait avant l'insertion : deux appels simultanes sur
        la meme requete pouvaient tous deux ne rien trouver et creer chacun
        leur job, donc interroger Vinted deux fois. Le test lance plusieurs
        soumissions vraiment en meme temps (barriere) pour ouvrir la fenetre
        de course aussi grand que possible."""
        nb_threads = 8
        barriere = threading.Barrier(nb_threads)
        liberer = threading.Event()
        self.addCleanup(liberer.set)

        appels = []
        verrou_appels = threading.Lock()

        def worker(job):
            with verrou_appels:
                appels.append(job.id)
            liberer.wait(timeout=10)

        obtenus = []
        verrou_obtenus = threading.Lock()

        def soumettre():
            barriere.wait(timeout=5)
            job = self.store.submit("meme-recherche", worker)
            with verrou_obtenus:
                obtenus.append(job.id)

        threads = [threading.Thread(target=soumettre) for _ in range(nb_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(obtenus), nb_threads)
        self.assertEqual(
            len(set(obtenus)), 1,
            f"plusieurs jobs crees pour la meme recherche : {set(obtenus)}",
        )

        liberer.set()
        for t in threads:
            t.join(timeout=5)
        self.assertTrue(_wait_until(lambda: len(appels) >= 1))
        self.assertEqual(len(appels), 1, "Vinted aurait ete interroge plusieurs fois")

    def test_recherche_inconnue(self):
        self.assertIsNone(self.store.get("jamais-vu"))

    def test_purge_des_jobs_expires(self):
        def worker(job):
            job.listing_ids = []

        vieux = self.store.submit("vieux", worker)
        self.assertTrue(_wait_until(lambda: vieux.is_finished))
        vieux.finished_at = datetime.utcnow() - JOB_RETENTION - timedelta(minutes=1)

        recent = self.store.submit("recent", worker)
        self.assertTrue(_wait_until(lambda: recent.is_finished))

        self.assertIsNone(self.store.get(vieux.id))
        self.assertIsNotNone(self.store.get(recent.id))

    def test_le_debordement_ne_purge_jamais_une_recherche_en_cours(self):
        """Regression. La purge de debordement retirait les jobs les plus
        anciens par date de creation. Avec un seul worker, le plus ancien est
        justement celui qui tourne : la recherche de l'utilisateur sortait du
        magasin en pleine execution, GET /search/{id} repondait 404
        « Recherche inconnue ou expiree » alors qu'elle tournait toujours, et
        la relancer refrappait Vinted une seconde fois."""
        demarre = threading.Event()
        liberer = threading.Event()

        def worker_bloquant(job):
            demarre.set()
            liberer.wait(timeout=10)

        def worker_rapide(job):
            job.listing_ids = []

        en_cours = self.store.submit("recherche-de-l-utilisateur", worker_bloquant)
        self.assertTrue(demarre.wait(timeout=5))
        self.addCleanup(liberer.set)

        # De quoi largement depasser le plafond. Requetes toutes distinctes,
        # sinon la deduplication par requete les fusionnerait.
        for i in range(MAX_JOBS + 5):
            self.store.submit(f"autre-recherche-{i}", worker_rapide)

        self.assertIsNotNone(
            self.store.get(en_cours.id),
            "une recherche encore en cours a ete purgee du magasin",
        )
        self.assertFalse(en_cours.is_finished)

        liberer.set()
        self.assertTrue(_wait_until(lambda: en_cours.status == STATUS_DONE))

    def test_le_debordement_purge_bien_les_jobs_termines(self):
        """Le garde-fou memoire doit continuer a faire son travail : ce sont
        les jobs TERMINES les plus anciens qui partent."""
        def worker(job):
            job.listing_ids = []

        premier = self.store.submit("tout-premier", worker)
        self.assertTrue(_wait_until(lambda: premier.is_finished))

        for i in range(MAX_JOBS + 5):
            job = self.store.submit(f"suivante-{i}", worker)
            self.assertTrue(_wait_until(lambda: job.is_finished))

        self.assertIsNone(
            self.store.get(premier.id),
            "le plafond memoire ne s'applique plus aux jobs termines",
        )

    def test_serialisation_pour_le_frontend(self):
        def worker(job):
            job.listing_ids = [1]

        job = self.store.submit("serialisation", worker)
        self.assertTrue(_wait_until(lambda: job.status == STATUS_DONE))
        payload = job.to_dict()
        for cle in ("job_id", "query", "status", "message", "error",
                    "result_count", "elapsed_seconds"):
            self.assertIn(cle, payload)


if __name__ == "__main__":
    unittest.main()
