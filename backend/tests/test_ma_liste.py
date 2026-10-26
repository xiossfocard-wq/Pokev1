"""
« Ma liste » : suivre une carte, avec un budget, et etre alerte.

Un collectionneur chasse SA carte, a SON prix. Ces tests verrouillent :
- le budget se compare au cout REEL (protection acheteur et port compris) ;
- une annonce dans le budget alerte quel que soit son score, une seule fois ;
- un lot « dont » la carte n'alerte pas ;
- la liste survit a une base reconstruite (lignes renumerotees) ;
- le seuil de notification regle dans le tableau de bord est enfin lu.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (AppSettings, Listing, ListingStatus, MarketCardPrice,
                        NotificationSent, SourcePlatform)
from app import pipeline
from app.pipeline import _maybe_notify, _score_listing
from app.notifications.telegram import format_deal_alert
from app.routers.suivi import ne_plus_suivre_une_carte, suivre_une_carte
from app.schemas import SuiviUpdate
from app.services import price_index, suivi
from fastapi import HTTPException


class BaseListe(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.shanks = MarketCardPrice(card_code="OP01-120", name_slug="shanks",
                                      display_name="Shanks", rarity="SEC (Secret Rare)",
                                      price_eur=24.0, language="fr", source="opecards")
        self.db.add(self.shanks)
        self.db.commit()
        price_index._slug_cache = None
        self.n = 0

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def annonce(self, titre="Shanks OP01-120", prix=20.0, etat="Très bon état"):
        self.n += 1
        a = Listing(source=SourcePlatform.VINTED, external_id=str(self.n), title=titre,
                    description="", url=f"https://vinted.test/{self.n}", price=prix,
                    shipping_price=0.0, currency="EUR", photo_urls=[],
                    seller_reliability_score=80.0, seller_condition=etat)
        self.db.add(a)
        self.db.commit()
        _score_listing(self.db, a)
        self.db.refresh(a)
        return a


class TestSuivre(BaseListe):
    def test_suivre_puis_lister(self):
        entree = suivi.suivre(self.db, self.shanks.id, 30.0)
        self.assertEqual(entree["prix_max"], 30.0)
        self.assertEqual([e["card_code"] for e in suivi.lister(self.db)], ["OP01-120"])

    def test_changer_le_budget_ne_cree_pas_de_doublon(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        suivi.suivre(self.db, self.shanks.id, 45.0)
        liste = suivi.lister(self.db)
        self.assertEqual(len(liste), 1)
        self.assertEqual(liste[0]["prix_max"], 45.0)

    def test_ne_plus_suivre(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        ne_plus_suivre_une_carte(self.shanks.id, self.db)
        self.assertEqual(suivi.lister(self.db), [])
        with self.assertRaises(HTTPException):
            ne_plus_suivre_une_carte(self.shanks.id, self.db)

    def test_une_carte_inconnue_est_refusee(self):
        with self.assertRaises(HTTPException) as e:
            suivre_une_carte(9999, SuiviUpdate(prix_max=10.0), self.db)
        self.assertEqual(e.exception.status_code, 404)

    def test_un_budget_negatif_ou_nul_est_refuse(self):
        with self.assertRaises(ValueError):
            SuiviUpdate(prix_max=0)

    def test_la_liste_survit_a_une_base_reconstruite(self):
        """Les lignes renumerotees, la liste designe toujours la bonne carte."""
        suivi.suivre(self.db, self.shanks.id, 30.0)
        self.db.delete(self.shanks)
        self.db.add(MarketCardPrice(id=500, card_code="OP01-120", name_slug="shanks",
                                    display_name="Shanks", price_eur=24.0))
        self.db.commit()
        entree = suivi.lister(self.db)[0]
        self.assertEqual(entree["id"], 500)
        self.assertFalse(entree["introuvable"])

    def test_une_carte_disparue_du_catalogue_est_signalee(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        self.db.delete(self.shanks)
        self.db.commit()
        self.assertTrue(suivi.lister(self.db)[0]["introuvable"])


class TestBudget(BaseListe):
    def test_le_budget_se_compare_au_cout_reel(self):
        """20 EUR affiches = 24,60 EUR payes. Budget 22 : hors budget."""
        suivi.suivre(self.db, self.shanks.id, 22.0)
        a = self.annonce(prix=20.0)
        self.assertEqual(a.purchase_cost_eur, 24.60)
        self.assertFalse(suivi.budget_pour_annonce(self.db, a)["dans_le_budget"])
        suivi.suivre(self.db, self.shanks.id, 25.0)
        self.assertTrue(suivi.budget_pour_annonce(self.db, a)["dans_le_budget"])

    def test_une_carte_non_suivie_n_a_pas_de_budget(self):
        self.assertIsNone(suivi.budget_pour_annonce(self.db, self.annonce()))

    def test_un_lot_dont_la_carte_n_est_pas_dans_le_budget(self):
        suivi.suivre(self.db, self.shanks.id, 100.0)
        lot = self.annonce(titre="Lot de 30 cartes dont Shanks OP01-120", prix=20.0)
        self.assertFalse(suivi.budget_pour_annonce(self.db, lot)["dans_le_budget"])

    def test_la_liste_montre_la_moins_chere_et_le_nombre_dans_le_budget(self):
        suivi.suivre(self.db, self.shanks.id, 20.0)
        self.annonce(prix=25.0)
        self.annonce(prix=12.0)
        entree = suivi.lister(self.db)[0]
        self.assertEqual(entree["annonces"]["nombre"], 2)
        self.assertEqual(entree["annonces"]["dans_le_budget"], 1)
        self.assertEqual(entree["annonces"]["moins_chere"]["price_eur"], 12.0)


@mock.patch.object(pipeline.settings, "telegram_chat_id", "chat")
@mock.patch.object(pipeline.settings, "telegram_bot_token", "jeton")
@mock.patch.object(pipeline.settings, "smtp_host", None)
class TestAlertes(BaseListe):
    def envoyer(self, annonce):
        with mock.patch.object(pipeline, "send_telegram_message", return_value=True) as envoi:
            _maybe_notify(self.db, annonce)
        return envoi

    def test_dans_le_budget_alerte_meme_sous_le_seuil(self):
        self.db.add(AppSettings(key="deal_score_threshold", value=101.0))
        self.db.commit()
        suivi.suivre(self.db, self.shanks.id, 30.0)
        envoi = self.envoyer(self.annonce(prix=20.0))
        self.assertEqual(envoi.call_count, 1)
        self.assertIn("Carte de ta liste", envoi.call_args[0][2])

    def test_une_seule_alerte_par_annonce(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        a = self.annonce(prix=20.0)
        self.envoyer(a)
        _score_listing(self.db, a)   # renotee : le statut NOTIFIED est reecrit
        self.assertEqual(self.envoyer(a).call_count, 0)
        self.assertEqual(self.db.query(NotificationSent).count(), 1)

    def test_le_seuil_des_reglages_est_lu(self):
        """Avant : la valeur fixe de la configuration, jamais celle du
        tableau de bord."""
        a = self.annonce(prix=8.0)
        self.db.add(AppSettings(key="deal_score_threshold", value=a.deal_score + 1))
        self.db.commit()
        self.assertEqual(self.envoyer(a).call_count, 0)
        self.db.merge(AppSettings(key="deal_score_threshold", value=a.deal_score - 1))
        self.db.commit()
        self.assertEqual(self.envoyer(a).call_count, 1)

    def test_une_carte_gradee_de_ma_liste_alerte_sans_score(self):
        """Pas de cote pour une PSA 10, donc pas de score : le budget suffit."""
        suivi.suivre(self.db, self.shanks.id, 80.0)
        gradee = self.annonce(titre="Shanks OP01-120 PSA 10", prix=60.0)
        self.assertIsNone(gradee.deal_score)
        self.assertEqual(self.envoyer(gradee).call_count, 1)

    def test_le_message_d_une_carte_suivie_donne_le_budget(self):
        a = self.annonce(prix=20.0)
        texte = format_deal_alert(a, "collection", {"prix_max": 30.0, "dans_le_budget": True})
        self.assertIn("dans ton budget de 30,00 €", texte)


if __name__ == "__main__":
    unittest.main()
