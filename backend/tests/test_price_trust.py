"""
Tests des deux garde-fous demandes apres consultation du dashboard reel :

1. Masquer les annonces a tres bas prix. Une carte a 1 EUR annoncee avec
   "+63 EUR de marge" n'est pas une bonne affaire : c'est un lot, une carte
   abimee, ou un titre qui a trompe le rapprochement.

2. Ne pas laisser une marge calculee sur un prix DOUTEUX piloter le score.
   Sinon ce sont les rapprochements les plus fragiles qui trustent le haut
   du classement — exactement l'inverse de ce qu'on veut d'un radar.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings, Listing, MarketCardPrice, SourcePlatform, ListingStatus
from app.pipeline import _score_listing
from app.routers.listings import _min_price_filter
from app.services import price_index


def carte(name_slug, display_name, card_code, price):
    return MarketCardPrice(
        name_slug=name_slug, display_name=display_name, card_code=card_code,
        price_eur=price, price_low_eur=price * 0.9, price_high_eur=price * 1.1,
        series_name="Serie test", source="zebradex",
    )


def annonce(titre, prix, external_id):
    return Listing(
        source=SourcePlatform.VINTED, external_id=external_id, title=titre,
        description="", url=f"https://exemple.test/{external_id}", price=prix,
        shipping_price=0.0, currency="EUR", photo_urls=[],
        seller_reliability_score=50.0,
    )


class BaseDeTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        price_index._slug_cache = []
        price_index._slug_cache_at = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = []
        price_index._slug_cache_at = None


class TestPrixMinimum(BaseDeTest):
    def setUp(self):
        super().setUp()
        self.db.add_all([
            annonce("Pikachu ex", 0.50, "a"),
            annonce("Pikachu ex", 1.00, "b"),
            annonce("Pikachu ex", 1.50, "c"),
            annonce("Dracaufeu V", 25.00, "d"),
        ])
        self.db.commit()

    def visibles(self):
        return sorted(
            l.price for l in self.db.query(Listing).filter(_min_price_filter(self.db)).all()
        )

    def test_seuil_par_defaut_masque_les_cartes_a_1_euro(self):
        self.assertEqual(self.visibles(), [1.50, 25.00])

    def test_seuil_reglable_depuis_le_dashboard(self):
        self.db.add(AppSettings(key="min_listing_price", value=5.0))
        self.db.commit()
        self.assertEqual(self.visibles(), [25.00])

    def test_seuil_a_zero_montre_tout(self):
        self.db.add(AppSettings(key="min_listing_price", value=0.0))
        self.db.commit()
        self.assertEqual(self.visibles(), [0.50, 1.00, 1.50, 25.00])


class TestMargeDouteuseExclueDuScore(BaseDeTest):
    def test_prix_incertain_ne_gonfle_plus_le_score(self):
        """Dix cartes "Pikachu ex" de 2 a 1130 EUR : la mediane retenue ne
        veut rien dire, la marge qui en decoule non plus."""
        self.db.add_all([
            carte("pikachu-ex", "Pikachu Ex", f"SET{i} {i}", prix)
            for i, prix in enumerate([2.0, 5.0, 9.0, 20.0, 75.0, 90.0, 300.0, 600.0, 900.0, 1130.0], 1)
        ])
        listing = annonce("Carte Pokemon Pikachu ex", 5.0, "douteux")
        self.db.add(listing)
        self.db.commit()

        _score_listing(self.db, listing, skip_vision=True)

        self.assertIsNotNone(listing.reference_price, "le prix reste affiche a titre indicatif")
        self.assertEqual(listing.price_match_confidence, "low")
        self.assertTrue(listing.price_detail["uncertain"])
        self.assertIsNotNone(listing.margin_net, "la marge reste visible")
        # Sans ce garde-fou, une marge fantaisiste de +70 EUR poussait le
        # score au maximum.
        self.assertLess(listing.deal_score, 80)

    def test_score_plafonne_quand_le_prix_est_inexploitable(self):
        """Une annonce dont on ne sait pas etablir le prix ne doit jamais
        flotter en haut du classement, meme avec un excellent vendeur et une
        carte tres recherchee : le radar n'a rien a annoncer sur elle."""
        self.db.add_all([
            carte("pikachu-ex", "Pikachu Ex", f"SET{i} {i}", prix)
            for i, prix in enumerate([2.0, 900.0, 1130.0], 1)
        ])
        listing = annonce("Carte Pokemon Pikachu ex neuve mint", 5.0, "plafond")
        listing.seller_reliability_score = 100.0
        self.db.add(listing)
        self.db.commit()

        _score_listing(self.db, listing, skip_vision=True)

        self.assertTrue(listing.price_detail["uncertain"])
        self.assertLessEqual(listing.deal_score, 60.0)
        # Sous le seuil de notification par defaut : pas d'alerte sur une
        # annonce qu'on est incapable de valoriser.
        self.assertLess(listing.deal_score, 70.0)

    def test_l_ordre_entre_annonces_douteuses_est_conserve(self):
        """Le plafond ne doit pas ecraser toutes les annonces douteuses au
        meme score : qualite et vendeur continuent de les departager."""
        self.db.add_all([
            carte("pikachu-ex", "Pikachu Ex", f"SET{i} {i}", prix)
            for i, prix in enumerate([2.0, 900.0, 1130.0], 1)
        ])
        bonne = annonce("Carte Pokemon Pikachu ex neuve mint", 5.0, "bonne")
        bonne.seller_reliability_score = 100.0
        mauvaise = annonce("Carte Pokemon Pikachu ex abimee pliee", 5.0, "mauvaise")
        mauvaise.seller_reliability_score = 10.0
        self.db.add_all([bonne, mauvaise])
        self.db.commit()

        _score_listing(self.db, bonne, skip_vision=True)
        _score_listing(self.db, mauvaise, skip_vision=True)

        self.assertGreater(bonne.deal_score, mauvaise.deal_score)

    def test_prix_fiable_compte_toujours_dans_le_score(self):
        """Meme annonce, mais un code carte explicite rend le rapprochement
        sur : la marge doit alors compter normalement."""
        self.db.add(carte("pikachu-ex", "Pikachu Ex", "PAF 232", 180.0))
        listing = annonce("Carte Pokemon Pikachu ex PAF 232", 5.0, "fiable")
        self.db.add(listing)
        self.db.commit()

        _score_listing(self.db, listing, skip_vision=True)

        self.assertEqual(listing.price_match_confidence, "high")
        self.assertFalse(listing.price_detail["uncertain"])
        self.assertGreater(listing.deal_score, 80)


if __name__ == "__main__":
    unittest.main()
