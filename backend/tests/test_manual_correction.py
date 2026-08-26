"""
Tests des corrections saisies a la main depuis le dashboard.

Demande du 25/08/2026 : « donne-moi la main sur le site avec possibilite
de corriger l'erreur moi-meme si je juge que les cartes ne correspondent
pas ». L'identification automatique se trompe — titres ecrits librement,
index incomplet, homonymes — et l'utilisateur voit souvent d'un coup d'oeil
ce que le programme n'arrive pas a decider.

Le point CRUCIAL teste ici : une correction doit survivre aux repassages
automatiques. Si le cycle suivant reecrivait par-dessus, l'utilisateur
aurait travaille pour rien, et ne ferait plus confiance a la fonction.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Listing, ListingStatus, MarketCardPrice, SourcePlatform
from app.pipeline import _score_listing, rescore_unpriced_listings, refilter_language
from app.routers.listings import correct_listing, _not_hidden_by_user
from app.schemas import ListingCorrection
from app.services import price_index


def carte(name_slug, display_name, card_code, price):
    return MarketCardPrice(
        name_slug=name_slug, display_name=display_name, card_code=card_code,
        price_eur=price, price_low_eur=price * 0.9, price_high_eur=price * 1.1,
        series_name="Serie test", source="zebradex",
    )


class TestCorrectionManuelle(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        price_index._slug_cache = []
        price_index._slug_cache_at = None

        # Trois "Pikachu ex" a des prix sans rapport : le rapprochement
        # automatique retiendra la mediane, et se trompera.
        self.db.add_all([
            carte("pikachu-ex", "Pikachu Ex", "SET1 1", 2.0),
            carte("pikachu-ex", "Pikachu Ex", "SET2 2", 75.0),
            carte("pikachu-ex", "Pikachu Ex", "SET3 3", 900.0),
        ])
        self.listing = Listing(
            source=SourcePlatform.VINTED, external_id="abc",
            title="Carte Pokemon Pikachu ex", description="",
            url="https://www.vinted.fr/items/abc-carte", price=5.0,
            shipping_price=0.0, currency="EUR", photo_urls=[],
            seller_reliability_score=50.0,
        )
        self.db.add(self.listing)
        self.db.commit()
        _score_listing(self.db, self.listing, skip_vision=True)

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = []
        price_index._slug_cache_at = None

    def corriger(self, action, price=None):
        return correct_listing(
            self.listing.id, ListingCorrection(action=action, price=price), self.db
        )

    # -- l'automatique se trompe, point de depart ------------------------

    def test_point_de_depart_le_prix_automatique_est_douteux(self):
        self.assertEqual(self.listing.reference_price, 75.0)
        self.assertTrue(self.listing.price_detail["uncertain"])

    # -- "ce n'est pas la bonne carte" -----------------------------------

    def test_mauvaise_carte_efface_le_prix(self):
        resultat = self.corriger("wrong_card")
        self.assertIsNone(resultat.reference_price)
        self.assertIsNone(resultat.margin_net)
        self.assertEqual(resultat.manual_status, "wrong_card")
        self.assertIsNotNone(resultat.manual_reviewed_at)

    def test_mauvaise_carte_survit_au_repassage_automatique(self):
        """Le test le plus important du fichier : sans ca, la correction
        serait effacee au cycle suivant."""
        self.corriger("wrong_card")

        rescore_unpriced_listings(self.db, limit=50, include_uncertain=True)

        self.db.refresh(self.listing)
        self.assertIsNone(self.listing.reference_price,
                          "le prix rejete ne doit jamais revenir tout seul")
        self.assertEqual(self.listing.manual_status, "wrong_card")

    # -- "voici le vrai prix" --------------------------------------------

    def test_prix_saisi_a_la_main_fait_autorite(self):
        resultat = self.corriger("set_price", price=250.0)
        self.assertEqual(resultat.reference_price, 250.0)
        self.assertEqual(resultat.price_match_confidence, "manual")
        self.assertFalse(resultat.price_detail["uncertain"])

    def test_prix_saisi_compte_pleinement_dans_le_score(self):
        """Un prix verifie par un humain est le plus fiable qui soit : il ne
        doit pas subir le plafond des prix douteux."""
        resultat = self.corriger("set_price", price=250.0)
        self.assertIsNotNone(resultat.margin_net)
        self.assertGreater(resultat.deal_score, 60.0)

    def test_prix_saisi_survit_au_repassage(self):
        self.corriger("set_price", price=250.0)
        rescore_unpriced_listings(self.db, limit=50, include_uncertain=True)
        self.db.refresh(self.listing)
        self.assertEqual(self.listing.reference_price, 250.0)

    def test_prix_invalide_refuse(self):
        for prix in (None, 0, -5):
            with self.subTest(prix=prix):
                with self.assertRaises(HTTPException) as ctx:
                    self.corriger("set_price", price=prix)
                self.assertEqual(ctx.exception.status_code, 400)

    # -- masquer ----------------------------------------------------------

    def test_masquer_retire_l_annonce_des_listes(self):
        self.corriger("hide")
        visibles = self.db.query(Listing).filter(_not_hidden_by_user()).all()
        self.assertEqual(visibles, [])

    # -- revenir en arriere ----------------------------------------------

    def test_reset_rend_la_main_a_l_automatique(self):
        self.corriger("wrong_card")
        resultat = self.corriger("reset")
        self.assertIsNone(resultat.manual_status)
        self.assertIsNone(resultat.manual_reviewed_at)
        self.assertEqual(resultat.reference_price, 75.0)

    # -- garde-fous --------------------------------------------------------

    def test_action_inconnue_refusee(self):
        with self.assertRaises(HTTPException) as ctx:
            self.corriger("supprime_tout")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_annonce_inexistante(self):
        with self.assertRaises(HTTPException) as ctx:
            correct_listing(999999, ListingCorrection(action="hide"), self.db)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_le_filtre_de_langue_respecte_l_utilisateur(self):
        """Si l'utilisateur a examine une annonce et l'a gardee, le filtre
        automatique n'a pas a la faire disparaitre derriere son dos."""
        etrangere = Listing(
            source=SourcePlatform.VINTED, external_id="de-1",
            title="Pokemon Karte Glurak Einzelkarte Sammelkarte", description="",
            url="https://www.vinted.fr/items/de-1-carte", price=9.0,
            shipping_price=0.0, currency="EUR", photo_urls=[],
        )
        self.db.add(etrangere)
        self.db.commit()

        correct_listing(etrangere.id, ListingCorrection(action="set_price", price=40.0), self.db)
        refilter_language(self.db)

        self.db.refresh(etrangere)
        self.assertNotEqual(etrangere.status, ListingStatus.IGNORED)


if __name__ == "__main__":
    unittest.main()
