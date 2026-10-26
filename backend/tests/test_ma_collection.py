"""
« Ma collection » : les cartes possedees, leur cout et leur valeur.

La valeur d'un exemplaire est la cote ramenee a son etat, la meme decote que
pour juger une annonce. Une carte sans cote n'a pas de valeur estimee, et
les totaux le disent au lieu de la compter pour zero.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Listing, MarketCardPrice, SourcePlatform
from app.pipeline import _score_listing
from app.routers.collection import ajouter_un_exemplaire
from app.schemas import ExemplaireAjout
from app.services import collection, price_index, suivi


class BaseCollection(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.shanks = MarketCardPrice(card_code="OP01-120", name_slug="shanks", display_name="Shanks",
                                      price_eur=24.0, language="fr", source="opecards")
        self.nami = MarketCardPrice(card_code="OP01-016", name_slug="nami", display_name="Nami",
                                    price_eur=None, language="fr")
        self.db.add_all([self.shanks, self.nami])
        self.db.commit()
        price_index._slug_cache = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None


class TestValeur(BaseCollection):
    def test_la_valeur_est_la_cote_ramenee_a_l_etat(self):
        collection.ajouter(self.db, card_id=self.shanks.id, prix_paye=13.05, etat="MP")
        c = collection.lister(self.db)
        ex = c["cartes"][0]["exemplaires"][0]
        self.assertEqual(ex["valeur"], 16.80)          # 24 x 0,70
        self.assertEqual(ex["plus_value"], 3.75)
        self.assertEqual(c["totaux"], {"exemplaires": 1, "valeur": 16.80, "paye": 13.05,
                                       "sans_cote": 0, "sans_prix_paye": 0, "plus_value": 3.75})

    def test_deux_exemplaires_d_une_carte_sont_regroupes(self):
        collection.ajouter(self.db, card_id=self.shanks.id, prix_paye=13.0, etat="MP")
        collection.ajouter(self.db, card_id=self.shanks.id, prix_paye=25.0, etat="NM")
        c = collection.lister(self.db)
        self.assertEqual(len(c["cartes"]), 1)
        self.assertEqual(c["cartes"][0]["valeur"], 16.80 + 24.0)
        self.assertEqual(collection.etat_de_la_carte(self.db, self.shanks), {"exemplaires": 2})

    def test_une_carte_sans_cote_n_est_pas_comptee_pour_zero(self):
        collection.ajouter(self.db, card_id=self.nami.id, prix_paye=3.0)
        c = collection.lister(self.db)
        self.assertIsNone(c["cartes"][0]["exemplaires"][0]["valeur"])
        self.assertIsNone(c["cartes"][0]["exemplaires"][0]["plus_value"])
        self.assertEqual(c["totaux"]["sans_cote"], 1)
        self.assertEqual(c["totaux"]["plus_value"], 0.0)  # rien d'invente

    def test_la_plus_precieuse_d_abord(self):
        collection.ajouter(self.db, card_id=self.nami.id)
        collection.ajouter(self.db, card_id=self.shanks.id)
        self.assertEqual([c["card_code"] for c in collection.lister(self.db)["cartes"]],
                         ["OP01-120", "OP01-016"])

    def test_retirer_un_exemplaire(self):
        collection.ajouter(self.db, card_id=self.shanks.id)
        ex_id = collection.lister(self.db)["cartes"][0]["exemplaires"][0]["id"]
        self.assertTrue(collection.retirer(self.db, ex_id))
        self.assertEqual(collection.lister(self.db)["cartes"], [])
        self.assertFalse(collection.retirer(self.db, ex_id))


class TestAchatDepuisLeRadar(BaseCollection):
    def annonce(self, titre="Shanks OP01-120", prix=9.0, etat="Satisfaisant"):
        a = Listing(source=SourcePlatform.VINTED, external_id="v1", title=titre, url="https://vinted.test/1",
                    price=prix, shipping_price=0.0, currency="EUR", photo_urls=[],
                    seller_reliability_score=80.0, seller_condition=etat)
        self.db.add(a)
        self.db.commit()
        _score_listing(self.db, a)
        return a

    def test_l_annonce_achetee_donne_le_prix_paye_et_l_etat(self):
        a = self.annonce()
        collection.ajouter(self.db, listing_id=a.id)
        ex = collection.lister(self.db)["cartes"][0]["exemplaires"][0]
        self.assertEqual(ex["prix_paye"], 13.05)        # cout reel, frais compris
        self.assertEqual(ex["etat"], "MP")

    def test_ce_que_l_utilisateur_precise_l_emporte(self):
        a = self.annonce()
        collection.ajouter(self.db, listing_id=a.id, prix_paye=12.0, etat="LP")
        ex = collection.lister(self.db)["cartes"][0]["exemplaires"][0]
        self.assertEqual((ex["prix_paye"], ex["etat"]), (12.0, "LP"))

    def test_l_annonce_quitte_le_radar_et_la_carte_ma_liste(self):
        suivi.suivre(self.db, self.shanks.id, 20.0)
        a = self.annonce()
        collection.ajouter(self.db, listing_id=a.id)
        self.db.refresh(a)
        self.assertEqual(a.manual_status, "hidden")
        self.assertEqual(suivi.lister(self.db), [])

    def test_une_annonce_non_identifiee_est_refusee(self):
        a = self.annonce(titre="Carte one piece rare")
        with self.assertRaises(HTTPException) as e:
            ajouter_un_exemplaire(ExemplaireAjout(listing_id=a.id), self.db)
        self.assertEqual(e.exception.status_code, 404)

    def test_il_faut_une_carte_ou_une_annonce(self):
        with self.assertRaises(HTTPException) as e:
            ajouter_un_exemplaire(ExemplaireAjout(), self.db)
        self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
