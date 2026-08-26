"""
Tests de la verification de disponibilite des annonces Vinted.

Motivation : signale le 25/08/2026 — « certains liens ne marchent pas sur
Vinted ». Les URLs stockees sont pourtant correctes ; ce sont les annonces
qui n'existent plus (vendues ou supprimees). Rien dans le pipeline ne le
detectait : les annonces s'accumulaient indefiniment et cliquer dessus
menait sur une page d'erreur.

Le point le plus important teste ici est le comportement en cas de DOUTE :
si Vinted nous bloque ou si le reseau echoue, on ne masque rien. Mieux vaut
un lien mort de temps en temps qu'une bonne affaire bien vivante effacee du
dashboard sans explication.
"""
import sys, os, unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import pipeline
from app.database import Base
from app.models import Listing, ListingStatus, SourcePlatform


def annonce(external_id, score, statut=ListingStatus.SCORED,
            source=SourcePlatform.VINTED, vue_il_y_a_h=0):
    return Listing(
        source=source, external_id=external_id,
        title=f"Carte Pokemon {external_id}", description="",
        url=f"https://www.vinted.fr/items/{external_id}-carte",
        price=12.0, shipping_price=0.0, currency="EUR", photo_urls=[],
        deal_score=score, status=statut,
        last_seen_at=datetime.utcnow() - timedelta(hours=vue_il_y_a_h),
    )


class FauxScraper:
    """Remplace les appels reseau : `reponses` associe un id d'annonce a
    True (en ligne), False (404) ou None (impossible de conclure)."""

    def __init__(self, reponses):
        self.reponses = reponses
        self.appels = []

    def is_listing_online(self, url):
        self.appels.append(url)
        for cle, valeur in self.reponses.items():
            if cle in url:
                return valeur
        return None


class TestDisponibilite(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self._vrai_scraper = pipeline._vinted_scraper

    def tearDown(self):
        pipeline._vinted_scraper = self._vrai_scraper
        self.db.close()

    def _lancer(self, reponses, limit=10, pool=200):
        pipeline._vinted_scraper = FauxScraper(reponses)
        resultat = pipeline.check_vinted_availability(self.db, limit=limit, pool=pool)
        return resultat, pipeline._vinted_scraper

    def test_annonce_disparue_masquee(self):
        self.db.add(annonce("vendue", 90.0))
        self.db.commit()

        resultat, _ = self._lancer({"vendue": False})

        self.assertEqual(resultat["gone"], 1)
        rechargee = self.db.query(Listing).filter_by(external_id="vendue").one()
        self.assertEqual(rechargee.status, ListingStatus.UNAVAILABLE)

    def test_annonce_toujours_en_ligne_conservee(self):
        self.db.add(annonce("vivante", 90.0))
        self.db.commit()

        resultat, _ = self._lancer({"vivante": True})

        self.assertEqual(resultat["gone"], 0)
        rechargee = self.db.query(Listing).filter_by(external_id="vivante").one()
        self.assertEqual(rechargee.status, ListingStatus.SCORED)

    def test_en_cas_de_doute_on_ne_masque_rien(self):
        """Vinted nous bloque, ou le reseau tombe : surtout ne rien effacer."""
        self.db.add(annonce("incertaine", 90.0))
        self.db.commit()

        resultat, _ = self._lancer({"incertaine": None})

        self.assertEqual(resultat["gone"], 0)
        self.assertEqual(resultat["checked"], 0)
        rechargee = self.db.query(Listing).filter_by(external_id="incertaine").one()
        self.assertEqual(rechargee.status, ListingStatus.SCORED)

    def test_seules_les_mieux_classees_sont_candidates(self):
        """Verifier coute 8 s : on ne depense ces requetes que sur les
        annonces qu'on est susceptible de cliquer."""
        self.db.add_all([
            annonce("faible", 10.0),
            annonce("forte", 95.0),
            annonce("moyenne", 50.0),
        ])
        self.db.commit()

        _, faux = self._lancer({}, limit=2, pool=2)

        self.assertEqual(len(faux.appels), 2)
        self.assertNotIn("faible", " ".join(faux.appels))

    def test_la_file_tourne_vraiment(self):
        """Trier seulement par score ferait reverifier les MEMES annonces a
        chaque cycle, sans jamais descendre. Dans le vivier des meilleures,
        on prend donc les moins recemment verifiees."""
        self.db.add_all([
            annonce("verifiee-a-l-instant", 95.0, vue_il_y_a_h=0),
            annonce("verifiee-hier", 90.0, vue_il_y_a_h=24),
            annonce("verifiee-avant-hier", 85.0, vue_il_y_a_h=48),
        ])
        self.db.commit()

        _, faux = self._lancer({}, limit=2)

        self.assertIn("verifiee-avant-hier", faux.appels[0])
        self.assertIn("verifiee-hier", faux.appels[1])

    def test_ebay_non_concerne(self):
        """eBay garde ses annonces terminees en ligne : leurs liens restent
        valides, inutile de depenser des requetes dessus."""
        self.db.add(annonce("ebay-item", 99.0, source=SourcePlatform.EBAY))
        self.db.commit()

        _, faux = self._lancer({"ebay-item": False})

        self.assertEqual(faux.appels, [])

    def test_ecriture_apres_chaque_annonce(self):
        """La passe doit conserver ce qu'elle a deja trouve, meme si elle
        est interrompue. C'est aussi ce qui garde la connexion Neon
        vivante : sans ca, 5 minutes d'interrogation de Vinted sans une
        seule ecriture faisaient tomber le commit final en erreur 500."""
        self.db.add_all([annonce("morte-1", 90.0), annonce("morte-2", 80.0)])
        self.db.commit()

        commits = []
        vrai_commit = self.db.commit

        def commit_espionne():
            commits.append(len(commits) + 1)
            return vrai_commit()

        self.db.commit = commit_espionne
        try:
            self._lancer({"morte-1": False, "morte-2": False})
        finally:
            self.db.commit = vrai_commit

        self.assertGreaterEqual(len(commits), 2, "un commit par annonce attendu")

    def test_annonces_deja_masquees_ignorees(self):
        self.db.add_all([
            annonce("etrangere", 80.0, statut=ListingStatus.IGNORED),
            annonce("deja-disparue", 80.0, statut=ListingStatus.UNAVAILABLE),
        ])
        self.db.commit()

        _, faux = self._lancer({})

        self.assertEqual(faux.appels, [])


if __name__ == "__main__":
    unittest.main()
