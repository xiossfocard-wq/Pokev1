"""
Ce qu'un collectionneur reprochait au classement des affaires.

Des annonces realistes passees dans l'algorithme de notation donnaient :

    « … proxy fan art »              2,48 EUR   score 82, en tete du radar
    « Lot de 50 cartes dont … »      36 EUR     comparee au prix d'UNE carte
    « … PSA 10 »                     6,65 EUR   comparee a une carte brute
    « … etat moyen »                            comparee a une carte neuve
    « … » a 5,75 EUR sur Vinted                 en coute 9,64 une fois payee

Chaque test verrouille l'une de ces corrections, et verifie qu'elle ne
touche pas une annonce saine : un garde-fou qui ecarte de vraies affaires
serait pire que le defaut qu'il corrige.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Listing, ListingStatus, MarketCardPrice, SourcePlatform
from app.pipeline import _score_listing
from app.scoring.margin import cout_d_achat, etat_retenu, etat_vinted
from app.scoring.pieges import detecter
from app.services import price_index


class TestPieges(unittest.TestCase):
    def test_les_contrefacons(self):
        for titre in ("Shanks OP01-120 proxy", "Luffy fan art holo", "Zoro carte custom",
                      "Nami orica full art", "Carte réplique Ace", "Luffy non officielle"):
            with self.subTest(titre=titre):
                self.assertIsNotNone(detecter(titre).contrefacon)

    def test_les_lots_et_les_cartes_gradees(self):
        self.assertIsNotNone(detecter("Lot de 50 cartes One Piece").lot)
        self.assertIsNotNone(detecter("Playset Nami OP01-016").lot)
        self.assertIsNotNone(detecter("Shanks OP01-120 PSA 10").gradee)
        self.assertIsNotNone(detecter("Luffy BGS 9.5").gradee)
        self.assertIsNotNone(detecter("Zoro gradée PCA 9").gradee)

    def test_une_annonce_honnete_ne_declenche_rien(self):
        """Les tournures d'annonces ordinaires qui ressemblent a un piege."""
        for titre in ("Shanks OP01-120 sortie de booster, prête pour PSA",
                      "Monkey D. Luffy parallèle très bon état",
                      "Nami OP01-016 1 carte", "Carte Zoro copieusement protégée",
                      "Boa Hancock alternative art FR"):
            with self.subTest(titre=titre):
                p = detecter(titre)
                self.assertEqual((p.contrefacon, p.lot, p.gradee), (None, None, None))


class TestCoutReel(unittest.TestCase):
    def test_vinted_ajoute_la_protection_et_estime_le_port(self):
        c = cout_d_achat("vinted", 5.75, None, None, 2.90)
        self.assertEqual(c["protection"], 0.99)       # 0,70 + 5 % de 5,75
        self.assertTrue(c["port_estime"])
        self.assertEqual(c["total"], 9.64)

    def test_la_protection_relevee_sur_vinted_prime_sur_le_calcul(self):
        c = cout_d_achat("vinted", 2.99, None, 3.84, 2.90)
        self.assertEqual(c["protection"], 0.85)
        self.assertEqual(c["origine_protection"], "relevee sur Vinted")

    def test_un_port_connu_n_est_pas_estime(self):
        c = cout_d_achat("vinted", 10.0, 3.50, None, 2.90)
        self.assertFalse(c["port_estime"])
        self.assertEqual(c["port"], 3.50)

    def test_ebay_sans_frais_d_acheteur(self):
        c = cout_d_achat("ebay", 10.0, 2.0)
        self.assertEqual((c["protection"], c["total"]), (0.0, 12.0))


class TestEtat(unittest.TestCase):
    def test_libelles_vinted(self):
        self.assertEqual(etat_vinted("Très bon état"), "NM")
        self.assertEqual(etat_vinted("Bon état"), "LP")
        self.assertEqual(etat_vinted("Satisfaisant"), "MP")
        self.assertIsNone(etat_vinted("Inconnu"))

    def test_une_contradiction_se_resout_du_cote_prudent(self):
        self.assertEqual(etat_retenu("MP", "NM"), "MP")
        self.assertEqual(etat_retenu(None, "LP"), "LP")
        self.assertIsNone(etat_retenu(None, None))


class TestNotation(unittest.TestCase):
    """Les memes annonces, notees de bout en bout."""

    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add(MarketCardPrice(card_code="OP05-119", name_slug="monkey-d-luffy",
                                    display_name="Monkey.D.Luffy", rarity="SEC",
                                    price_eur=40.0, language="fr", source="opecards"))
        self.db.commit()
        price_index._slug_cache = None
        self.n = 0

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def noter(self, titre, prix, etat_coche=None, description=""):
        self.n += 1
        annonce = Listing(source=SourcePlatform.VINTED, external_id=str(self.n),
                          title=titre, description=description,
                          url=f"https://vinted.test/{self.n}", price=prix,
                          currency="EUR", photo_urls=[], seller_reliability_score=80.0,
                          seller_condition=etat_coche)
        self.db.add(annonce)
        self.db.commit()
        _score_listing(self.db, annonce)
        self.db.refresh(annonce)
        return annonce

    def test_une_contrefacon_est_ecartee_avec_sa_raison(self):
        a = self.noter("Monkey.D.Luffy OP05-119 proxy fan art", 2.48)
        self.assertEqual(a.status, ListingStatus.IGNORED)
        self.assertIn("proxy", a.price_detail["exclusion"])

    def test_un_lot_reste_visible_mais_sans_marge(self):
        a = self.noter("Lot de 50 cartes dont Monkey.D.Luffy OP05-119", 36.0)
        self.assertEqual(a.status, ListingStatus.NO_PRICE_MATCH)
        self.assertIsNone(a.margin_net)
        self.assertIsNone(a.deal_score)
        self.assertIn("Lot", a.price_detail["non_comparable"])
        self.assertIsNotNone(a.purchase_cost_eur)   # le cout, lui, est connu

    def test_une_carte_gradee_n_est_pas_comparee_a_une_carte_brute(self):
        a = self.noter("Monkey.D.Luffy OP05-119 PSA 10", 60.0)
        self.assertIsNone(a.margin_net)
        self.assertIn("gradée", a.price_detail["non_comparable"])

    def test_la_marge_compte_le_cout_reel_d_un_achat_vinted(self):
        """20 EUR affiches = 24,60 EUR payes : protection 0,70 + 5 %, port estime."""
        from app.scoring.margin import calculate_margin
        a = self.noter("Monkey.D.Luffy OP05-119", 20.0)
        self.assertEqual(a.purchase_cost_eur, 24.60)
        self.assertTrue(a.purchase_cost_detail["port_estime"])
        hors_frais = calculate_margin(20.0, 0.0, 40.0).net_margin
        self.assertAlmostEqual(hors_frais - a.margin_net, 4.60, places=2)

    def test_l_etat_decote_la_reference(self):
        neuve = self.noter("Monkey.D.Luffy OP05-119", 20.0)
        moyenne = self.noter("Monkey.D.Luffy OP05-119", 20.0, etat_coche="Satisfaisant")
        self.assertEqual(moyenne.condition_tier, "MP")
        self.assertEqual(moyenne.price_detail["etat_retenu"]["coefficient"], 0.70)
        self.assertLess(moyenne.margin_net, neuve.margin_net)
        self.assertNotIn("etat_retenu", neuve.price_detail)

    def test_trop_beau_pour_etre_vrai_garde_son_score_mais_avertit(self):
        a = self.noter("Monkey.D.Luffy OP05-119", 4.0)
        self.assertIsNotNone(a.deal_score)
        self.assertIn("authenticité", a.price_detail["alerte"])
        normale = self.noter("Monkey.D.Luffy OP05-119", 25.0)
        self.assertNotIn("alerte", normale.price_detail)

    def test_le_verdict_de_l_utilisateur_prime_sur_la_detection(self):
        """Il a regarde l'annonce : « copie » voulait dire autre chose."""
        from datetime import datetime
        self.n += 1
        a = Listing(source=SourcePlatform.VINTED, external_id="revue",
                    title="Monkey.D.Luffy OP05-119 fake", url="https://vinted.test/r",
                    price=20.0, currency="EUR", photo_urls=[],
                    seller_reliability_score=80.0, manual_reviewed_at=datetime.utcnow())
        self.db.add(a)
        self.db.commit()
        _score_listing(self.db, a)
        self.assertNotEqual(a.status, ListingStatus.IGNORED)


if __name__ == "__main__":
    unittest.main()
