"""
Tests du bilan de sante (/api/admin/diagnostic) et de ce qui l'alimente.

CE QUI EST VERIFIE
------------------
Que le bilan dise la VRAIE raison d'un echec, sans jamais exposer de
secret, et qu'une rubrique en panne n'emporte pas les autres. Un bilan qui
plante quand quelque chose va mal ne sert precisement a rien.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.collectors.vinted_scraper import VintedScraper
from app.database import Base
from app.models import MarketCardPrice
from app.services import diagnostic


class TestBilan(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add_all([
            MarketCardPrice(card_code="OP17-022", name_slug="shanks",
                            display_name="Shanks", language="fr", price_eur=0.75,
                            source="opecards",
                            image_url="https://fr.test/OP17-022.webp",
                            image_source="onepiece-cardgame"),
            MarketCardPrice(card_code="OP01-001", name_slug="zoro",
                            display_name="Zoro", language="en",
                            image_url="https://en.test/OP01-001.png",
                            image_source="onepiece-cardgame-en:deduit"),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_les_rubriques_locales_sont_toutes_la(self):
        bilan = diagnostic.etablir_diagnostic(self.db, avec_sources=False)
        for rubrique in ("catalogue", "visuels", "annonces", "collecte",
                         "erreurs_recentes"):
            self.assertIn(rubrique, bilan)
        self.assertEqual(bilan["catalogue"]["francaises"], 1)
        self.assertEqual(bilan["catalogue"]["avec_prix"], 1)
        self.assertEqual(bilan["visuels"]["dont_deduits_pas_encore_verifies"], 1)

    def test_sans_sources_aucun_appel_reseau(self):
        """Le mode rapide doit l'etre vraiment."""
        with mock.patch.object(diagnostic, "_vinted") as vinted:
            bilan = diagnostic.etablir_diagnostic(self.db, avec_sources=False)
        vinted.assert_not_called()
        self.assertNotIn("vinted_depuis_cette_machine", bilan)

    def test_une_rubrique_en_panne_n_emporte_pas_les_autres(self):
        """Un bilan qui plante quand quelque chose va mal ne sert a rien."""
        with mock.patch.object(diagnostic, "_annonces",
                               side_effect=RuntimeError("table absente")):
            bilan = diagnostic.etablir_diagnostic(self.db, avec_sources=False)
        self.assertIn("erreur", bilan["annonces"])
        self.assertEqual(bilan["catalogue"]["cartes"], 2)

    def test_la_cle_ebay_n_apparait_jamais(self):
        with mock.patch.multiple(diagnostic.settings, ebay_client_id="ID-SECRET",
                                 ebay_client_secret="SECRET-ABSOLU"):
            bilan = diagnostic.etablir_diagnostic(self.db, avec_sources=False)
        self.assertIs(bilan["collecte"]["ebay_configure"], True)
        self.assertNotIn("SECRET", repr(bilan))


class TestJournaux(unittest.TestCase):
    def test_les_deux_journaux_sont_lus_et_filtres(self):
        """Le script Windows met la sortie dans api.log et les erreurs dans
        api.log.err ; c'est dans le second que Python ecrit ses journaux."""
        with tempfile.TemporaryDirectory() as dossier:
            Path(dossier, "api.log").write_text("INFO tout va bien\n", encoding="utf-8")
            Path(dossier, "api.log.err").write_text(
                "INFO rien\nWARNING Vinted: statut 403\nERROR Prix : serie illisible\n",
                encoding="utf-8")
            lignes = diagnostic.erreurs_recentes(Path(dossier))
        self.assertEqual(len(lignes), 2)
        self.assertTrue(any("403" in l for l in lignes))

    def test_les_secrets_sont_masques(self):
        with tempfile.TemporaryDirectory() as dossier:
            Path(dossier, "api.log").write_text(
                "ERROR connexion a postgresql://moi:MotDePasse@hote/base refusee\n"
                "WARNING appel avec token=ABC123 refuse\n", encoding="utf-8")
            lignes = " ".join(diagnostic.erreurs_recentes(Path(dossier)))
        self.assertNotIn("MotDePasse", lignes)
        self.assertNotIn("ABC123", lignes)
        self.assertIn("***", lignes)

    def test_sans_journal_liste_vide(self):
        """Sur un hebergement, aucun fichier : pas une erreur."""
        with tempfile.TemporaryDirectory() as dossier:
            self.assertEqual(diagnostic.erreurs_recentes(Path(dossier)), [])


class Reponse:
    def __init__(self, code, texte=""):
        self.status_code = code
        self.text = texte


class TestRaisonDUnEchecVinted(unittest.TestCase):
    """Le scraper rendait None dans cinq cas sans dire lequel. Ils n'ont pas
    le meme remede — et l'un d'eux, robots.txt, n'en a aucun."""

    def scraper(self):
        s = VintedScraper(request_delay_seconds=0, jitter_seconds=0)
        return s

    def test_robots_txt_est_nomme(self):
        s = self.scraper()
        with mock.patch("app.collectors.vinted_scraper.robots_compliance.is_allowed",
                        return_value=False):
            self.assertIsNone(s._get("/catalog"))
        self.assertIn("robots.txt", s.derniere_erreur)

    def test_un_refus_http_est_nomme(self):
        s = self.scraper()
        with mock.patch("app.collectors.vinted_scraper.robots_compliance.is_allowed",
                        return_value=True), \
             mock.patch.object(s.session, "get", return_value=Reponse(403)):
            self.assertIsNone(s._get("/catalog"))
        self.assertIn("403", s.derniere_erreur)

    def test_une_coupure_reseau_est_nommee(self):
        s = self.scraper()
        with mock.patch("app.collectors.vinted_scraper.robots_compliance.is_allowed",
                        return_value=True), \
             mock.patch.object(s.session, "get",
                               side_effect=requests.ConnectionError("DNS")):
            self.assertIsNone(s._get("/catalog"))
        self.assertIn("reseau", s.derniere_erreur)

    def test_le_diagnostic_rend_la_vraie_raison(self):
        """Plus de « voir les logs Render » sur un PC qui n'a pas de Render."""
        s = self.scraper()
        with mock.patch("app.collectors.vinted_scraper.robots_compliance.is_allowed",
                        return_value=False):
            page = s.diagnostic_fetch("carte one piece")
        self.assertFalse(page["ok"])
        self.assertIn("robots.txt", page["reason"])
        self.assertNotIn("Render", page["reason"])

    def test_une_reponse_reussie_efface_l_echec_precedent(self):
        s = self.scraper()
        s.derniere_erreur = "HTTP 429 : ancien refus"
        with mock.patch("app.collectors.vinted_scraper.robots_compliance.is_allowed",
                        return_value=True), \
             mock.patch.object(s.session, "get", return_value=Reponse(200, "<html/>")):
            self.assertIsNotNone(s._get("/catalog"))
        self.assertIsNone(s.derniere_erreur)


if __name__ == "__main__":
    unittest.main()
