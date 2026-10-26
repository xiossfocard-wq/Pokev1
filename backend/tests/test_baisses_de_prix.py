"""
Une annonce deja connue dont le vendeur change le prix.

LE DEFAUT
---------
Revue dans une collecte, une annonce connue ne recevait qu'une nouvelle date
de derniere vue. Un vendeur qui baissait sa carte de 40 a 25 EUR restait
affiche a 40 : pas de nouveau calcul, pas d'alerte, alors qu'une baisse est
precisement le moment ou une annonce devient une affaire.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import pipeline
from app.collectors.vinted_scraper import VintedListing
from app.database import Base
from app.models import Listing, ListingStatus, MarketCardPrice, NotificationSent
from app.notifications.contenu import lignes_de_l_affaire
from app.services import price_index, suivi


def article(prix, item_id="v1"):
    return VintedListing(item_id=item_id, title="Shanks OP01-120", price=prix, currency="EUR",
                         url=f"https://www.vinted.fr/items/{item_id}",
                         raw={"condition": "Très bon état"})


@mock.patch.object(pipeline.settings, "vinted_enabled", True)
@mock.patch.object(pipeline.settings, "smtp_host", None)
@mock.patch.object(pipeline.settings, "telegram_chat_id", "chat")
@mock.patch.object(pipeline.settings, "telegram_bot_token", "jeton")
class TestBaisses(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.shanks = MarketCardPrice(card_code="OP01-120", name_slug="shanks", display_name="Shanks",
                                      price_eur=42.0, language="fr", source="opecards")
        self.db.add(self.shanks)
        self.db.commit()
        price_index._slug_cache = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def collecter(self, *articles):
        """Un cycle de collecte Vinted ; rend le nombre d'alertes envoyees."""
        with mock.patch.object(pipeline._vinted_scraper, "search_card_listings",
                               return_value=list(articles)), \
             mock.patch.object(pipeline, "send_telegram_message", return_value=True) as envoi:
            pipeline.run_vinted_check(self.db)
        return envoi.call_count

    def annonce(self):
        return self.db.query(Listing).filter_by(external_id="v1").one()

    def test_le_nouveau_prix_est_repris_et_l_annonce_renotee(self):
        self.collecter(article(40.0))
        avant = self.annonce().savings_eur
        self.collecter(article(25.0))
        a = self.annonce()
        self.assertEqual(a.price, 25.0)
        self.assertEqual(a.price_initial, 40.0)
        self.assertIsNotNone(a.price_changed_at)
        self.assertGreater(a.savings_eur, avant)

    def test_un_prix_inchange_ne_renote_pas(self):
        self.collecter(article(40.0))
        with mock.patch.object(pipeline, "_score_listing") as notation:
            self.collecter(article(40.0))
        notation.assert_not_called()
        self.assertIsNone(self.annonce().price_initial)

    def test_une_baisse_dans_le_budget_alerte(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        self.assertEqual(self.collecter(article(40.0)), 0)   # hors budget, score bas
        self.assertEqual(self.collecter(article(22.0)), 1)   # 22 EUR = ~26,90 payes

    def test_une_seconde_baisse_apres_une_alerte_realerte(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        self.assertEqual(self.collecter(article(22.0)), 1)
        self.assertEqual(self.collecter(article(22.0)), 0)   # meme prix : pas de doublon
        self.assertEqual(self.collecter(article(18.0)), 1)   # nouvelle baisse
        self.assertEqual(self.collecter(article(20.0)), 0)   # hausse : rien
        self.assertEqual(self.db.query(NotificationSent).count(), 2)

    def test_une_annonce_masquee_n_alerte_pas(self):
        suivi.suivre(self.db, self.shanks.id, 30.0)
        self.collecter(article(40.0))
        a = self.annonce()
        a.manual_status = "hidden"
        self.db.commit()
        self.assertEqual(self.collecter(article(15.0)), 0)

    def test_une_annonce_indisponible_qui_reapparait_revient(self):
        self.collecter(article(40.0))
        a = self.annonce()
        a.status = ListingStatus.UNAVAILABLE
        self.db.commit()
        self.collecter(article(40.0))
        self.assertNotEqual(self.annonce().status, ListingStatus.UNAVAILABLE)

    def test_l_alerte_dit_la_baisse(self):
        self.collecter(article(40.0))
        self.collecter(article(25.0))
        lignes = dict(lignes_de_l_affaire(self.annonce()))
        self.assertEqual(lignes["↓ Baisse de prix"], "40,00 € → 25,00 €")

    def test_le_port_ebay_est_repris(self):
        a = Listing(source="ebay", external_id="e1", title="Shanks OP01-120", url="https://ebay.test/e1",
                    price=30.0, shipping_price=2.0, currency="EUR", photo_urls=[])
        self.db.add(a)
        self.db.commit()
        with mock.patch.object(pipeline, "send_telegram_message", return_value=True):
            self.assertTrue(pipeline._revoir_annonce(self.db, a, 28.0, port=0.0))
        self.assertEqual((a.price, a.shipping_price, a.price_initial), (28.0, 0.0, 30.0))


if __name__ == "__main__":
    unittest.main()
