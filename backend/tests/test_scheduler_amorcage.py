"""
Tests de l'amorcage automatique d'un serveur sans operateur.

CE QUI EST VERIFIE
------------------
Qu'un serveur deploye se remplisse seul — et surtout qu'il ne fasse RIEN
quand il n'y a rien a faire : sur un hebergement gratuit, cette tache tourne
a chaque reveil, et un rechargement complet a chaque reveil serait un
desastre de lenteur.

Le cas de la base heritee est verifie a part : celle du deploiement actuel
contient l'ancien index Pokemon. Ses lignes n'ont pas de langue, et elles ne
doivent pas faire croire que le catalogue One Piece est deja la.
"""
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config, scheduler
from app.database import Base
from app.models import MarketCardPrice


class TestAmorcage(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.Session = sessionmaker(bind=moteur)
        self.sources = mock.Mock()

    def lancer(self):
        with mock.patch.object(scheduler, "SessionLocal", self.Session), \
             mock.patch.object(scheduler, "_job_sources_du_jour", self.sources):
            scheduler._job_amorcage()

    def compter(self, **filtre):
        db = self.Session()
        try:
            requete = db.query(MarketCardPrice)
            if "langue" in filtre:
                requete = requete.filter(MarketCardPrice.language.isnot(None))
            return requete.count()
        finally:
            db.close()

    def ajouter(self, **champs):
        db = self.Session()
        db.add(MarketCardPrice(**champs))
        db.commit()
        db.close()

    def test_une_base_vide_se_remplit_seule(self):
        """Le cas d'un deploiement neuf : catalogue de base, puis noms et
        prix. Avec le VRAI instantane livre dans le depot."""
        self.lancer()
        self.assertGreater(self.compter(langue=True), 3000)
        self.sources.assert_called_once()

    def test_une_base_deja_servie_ne_bouge_pas(self):
        """Chaque reveil d'un serveur gratuit relance cette tache. Elle ne
        doit alors couter qu'un comptage."""
        self.ajouter(card_code="OP17-022", name_slug="shanks",
                     display_name="Shanks", language="fr",
                     price_eur=0.75, source="opecards")
        self.lancer()
        self.assertEqual(self.compter(), 1)
        self.sources.assert_not_called()

    def test_les_lignes_d_un_ancien_index_ne_comptent_pas(self):
        """La base du deploiement actuel contient l'ancien index Pokemon.
        Ses lignes n'ont pas de langue : elles ne doivent pas faire croire
        que le catalogue One Piece est deja charge."""
        self.ajouter(card_code="SV01-001", name_slug="pikachu",
                     display_name="Pikachu", price_eur=2.0, source="zebradex")
        self.lancer()
        self.assertGreater(self.compter(langue=True), 3000)

    def test_un_chargement_interrompu_reprend_au_reveil_suivant(self):
        """Catalogue la, mais aucun prix : la mise en veille a coupe le
        chargement des prix. Le reveil suivant doit le reprendre, sans
        recharger le catalogue."""
        self.ajouter(card_code="OP17-022", name_slug="shanks",
                     display_name="Shanks", language="fr")
        self.lancer()
        self.assertEqual(self.compter(), 1)
        self.sources.assert_called_once()

    def test_une_base_injoignable_ne_fait_rien_remonter(self):
        """Au reveil, la base peut ne pas repondre encore. La tache doit se
        taire et laisser le serveur servir, pas propager l'erreur."""
        with mock.patch.object(scheduler, "SessionLocal",
                               side_effect=RuntimeError("base injoignable")), \
             mock.patch.object(scheduler, "_job_sources_du_jour", self.sources):
            scheduler._job_amorcage()
        self.sources.assert_not_called()

    def test_un_catalogue_illisible_n_enchaine_pas_sur_les_prix(self):
        """Sans catalogue, les prix n'auraient aucune fiche ou se poser."""
        with mock.patch("app.collectors.opcg_dataset.charger_catalogue",
                        side_effect=RuntimeError("instantane corrompu")):
            self.lancer()
        self.sources.assert_not_called()


class TestOuLAmorcageSActive(unittest.TestCase):
    """Actif sur Render, eteint sur un poste de travail.

    Sur un poste, le script de demarrage fait deja ce travail ; le faire
    AUSSI lancerait deux chargements concurrents sur la meme base SQLite,
    qui n'admet qu'un ecrivain a la fois."""

    def reglage(self, **env):
        propre = {k: v for k, v in os.environ.items()
                  if k not in ("RENDER", "AMORCAGE_AUTOMATIQUE")}
        propre.update(env)
        with mock.patch.dict(os.environ, propre, clear=True):
            return config.Settings().amorcage_automatique

    def test_eteint_sur_un_poste_de_travail(self):
        self.assertFalse(self.reglage())

    def test_actif_sur_render(self):
        """Render pose lui-meme RENDER=true : aucun reglage a faire."""
        self.assertTrue(self.reglage(RENDER="true"))

    def test_le_reglage_explicite_prime(self):
        self.assertFalse(self.reglage(RENDER="true", AMORCAGE_AUTOMATIQUE="false"))
        self.assertTrue(self.reglage(AMORCAGE_AUTOMATIQUE="true"))

    def test_la_tache_n_est_programmee_que_si_active(self):
        for actif in (True, False):
            with self.subTest(actif=actif):
                faux = mock.Mock()
                with mock.patch.object(scheduler, "scheduler", faux), \
                     mock.patch.object(scheduler.settings, "scheduler_enabled", True), \
                     mock.patch.object(scheduler.settings, "amorcage_automatique", actif):
                    scheduler.start_scheduler()
                ids = [appel.kwargs.get("id") for appel in faux.add_job.call_args_list]
                self.assertEqual("amorcage" in ids, actif)


if __name__ == "__main__":
    unittest.main()
