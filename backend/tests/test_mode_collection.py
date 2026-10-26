"""
Le mode collection, et les reglages du score enfin appliques.

POURQUOI
--------
La marge supposait une revente sur Cardmarket : cote moins 5 % de decote,
moins les frais de vente, moins le port de reexpedition. Pour un
collectionneur, qui garde la carte, c'etait la mauvaise question. Une
« Shanks OP01-120 » etat moyen payee 13,05 EUR, frais compris, pour une
cote ramenee a 16,80 EUR affichait -0,66 EUR de marge : elle coutait
pourtant 3,75 EUR de moins que sur Cardmarket.

Et les poids du score reglables dans le tableau de bord n'etaient jamais
lus : calculate_deal_score etait appele sans eux.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AppSettings, Listing, ListingStatus, MarketCardPrice, SourcePlatform
from app.notifications.contenu import lignes_de_l_affaire
from app.notifications.telegram import format_deal_alert
from app.pipeline import _score_listing, calculer_deal_score
from app.routers.settings_router import update_settings
from app.schemas import SettingsUpdate
from app.services import price_index
from app.settings_service import load_app_settings


class BaseNotation(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.db.add(MarketCardPrice(card_code="OP01-120", name_slug="shanks",
                                    display_name="Shanks", rarity="SEC (Secret Rare)",
                                    price_eur=24.0, language="fr", source="opecards"))
        self.db.commit()
        price_index._slug_cache = None
        self.n = 0

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def regler(self, **valeurs):
        for cle, valeur in valeurs.items():
            self.db.merge(AppSettings(key=cle, value=valeur))
        self.db.commit()

    def noter(self, titre="Shanks OP01-120", prix=9.0, etat="Satisfaisant"):
        self.n += 1
        annonce = Listing(source=SourcePlatform.VINTED, external_id=str(self.n), title=titre,
                          description="", url=f"https://vinted.test/{self.n}", price=prix,
                          shipping_price=0.0, currency="EUR", photo_urls=[],
                          seller_reliability_score=80.0, seller_condition=etat)
        self.db.add(annonce)
        self.db.commit()
        _score_listing(self.db, annonce)
        self.db.refresh(annonce)
        return annonce


class TestEconomie(BaseNotation):
    def test_l_economie_compare_le_cout_paye_a_la_cote_ajustee(self):
        """LE cas : 9 EUR affiches, 13,05 payes ; cote 24 ramenee a 16,80
        pour l'etat MP. Marge de revente negative, mais 3,75 EUR d'economie."""
        a = self.noter()
        self.assertEqual(a.purchase_cost_eur, 13.05)
        self.assertEqual(a.savings_eur, 3.75)
        self.assertAlmostEqual(a.savings_ratio, 3.75 / 16.80, places=4)
        self.assertLess(a.margin_net, 0)

    def test_payer_plus_que_la_cote_n_est_pas_une_economie(self):
        a = self.noter(prix=20.0, etat="Très bon état")
        self.assertLess(a.savings_eur, 0)

    def test_le_mode_collection_est_le_mode_par_defaut(self):
        self.assertEqual(load_app_settings(self.db)["mode_evaluation"], "collection")


class TestScoreSelonLeMode(BaseNotation):
    def test_une_affaire_de_collectionneur_score_mieux_en_mode_collection(self):
        a = self.noter()
        collection = calculer_deal_score(a, load_app_settings(self.db))
        self.regler(mode_evaluation="revente")
        revente = calculer_deal_score(a, load_app_settings(self.db))
        self.assertGreater(collection, revente)

    def test_la_moitie_de_la_cote_donne_tous_les_points_d_affaire(self):
        """Poids tout sur l'affaire : le score vaut la part d'affaire, plus
        le bonus d'attrait de la carte (Shanks, SEC), plafonne a 100."""
        from app.scoring.card_appeal import detect_card_appeal
        self.regler(margin_weight=1.0, quality_weight=0.0, seller_weight=0.0)
        bonus = detect_card_appeal("Shanks OP01-120", "")["appeal_bonus"]
        moitie = self.noter(prix=5.0, etat="Très bon état")   # 9,35 payes pour 24
        self.assertGreaterEqual(moitie.savings_ratio, 0.5)
        self.assertEqual(moitie.deal_score, 100.0)
        sans_affaire = self.noter(prix=30.0, etat="Très bon état")
        self.assertEqual(sans_affaire.deal_score, bonus)


class TestPoidsReglables(BaseNotation):
    def test_les_poids_du_tableau_de_bord_sont_appliques(self):
        """Avant : les curseurs etaient enregistres, puis ignores."""
        a = self.noter()
        avant = calculer_deal_score(a, load_app_settings(self.db))
        self.regler(margin_weight=0.0, quality_weight=0.0, seller_weight=1.0)
        apres = calculer_deal_score(a, load_app_settings(self.db))
        self.assertNotEqual(avant, apres)

    def test_trois_poids_a_zero_ne_cassent_pas_la_notation(self):
        self.regler(margin_weight=0.0, quality_weight=0.0, seller_weight=0.0)
        self.assertIsNotNone(self.noter().deal_score)

    def test_changer_de_mode_recalcule_les_scores_deja_stockes(self):
        a = self.noter()
        score_collection = a.deal_score
        update_settings(SettingsUpdate(mode_evaluation="revente"), self.db)
        self.db.refresh(a)
        self.assertLess(a.deal_score, score_collection)
        self.assertEqual(a.status, ListingStatus.SCORED)

    def test_un_autre_reglage_ne_recalcule_rien(self):
        a = self.noter()
        a.deal_score = 1.0      # marqueur : un recalcul l'effacerait
        self.db.commit()
        update_settings(SettingsUpdate(min_listing_price=2.0), self.db)
        self.db.refresh(a)
        self.assertEqual(a.deal_score, 1.0)


class TestAlertes(BaseNotation):
    def test_l_alerte_dit_le_cout_paye_et_l_economie(self):
        a = self.noter()
        lignes = dict(lignes_de_l_affaire(a, "collection"))
        self.assertIn("13,05 € payé", lignes["Prix"])
        self.assertIn("16,80 €", lignes["Cote"])
        self.assertTrue(lignes["Économie"].startswith("3,75 € sous la cote"))
        self.assertNotIn("Marge de revente estimée", lignes)

    def test_en_mode_revente_l_alerte_donne_la_marge(self):
        lignes = dict(lignes_de_l_affaire(self.noter(), "revente"))
        self.assertIn("Marge de revente estimée", lignes)
        self.assertNotIn("Économie", lignes)

    def test_un_titre_avec_des_chevrons_ne_casse_pas_le_message_telegram(self):
        a = self.noter(titre="Shanks OP01-120 <3 top")
        self.assertIn("&lt;3", format_deal_alert(a))


class TestRepassage(BaseNotation):
    def test_une_annonce_sans_economie_calculee_est_renotee(self):
        """Notee par une version precedente : elle revient dans la file."""
        from app.pipeline import rescore_unpriced_listings
        a = self.noter()
        a.savings_eur = None
        self.db.commit()
        self.assertEqual(rescore_unpriced_listings(self.db)["examined"], 1)
        self.db.refresh(a)
        self.assertEqual(a.savings_eur, 3.75)


if __name__ == "__main__":
    unittest.main()
