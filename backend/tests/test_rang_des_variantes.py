"""
Le prix retenu pour une annonce, selon la version de la carte qu'elle annonce.

LE DEFAUT QUE CES TESTS VERROUILLENT
------------------------------------
La version d'une fiche etait lue sur la fin de son nom : « shanks-parallele »
-> « parallele ». Depuis que chaque illustration alternative a sa propre
fiche — « shanks-parallele-1 », « shanks-parallele-2 » —, cette lecture ne
reconnaissait plus rien, et les trois fiches d'un code passaient pour des
impressions ordinaires. La MEDIANE de leurs prix etait retenue.

Consequence : pour chaque carte ayant une illustration alternative, une
annonce de la carte ordinaire etait evaluee au prix du parallele. Une
« Shanks OP17-022 » a 5 EUR s'affichait comme une affaire face a 13 EUR,
alors que la carte vaut 0,75 EUR.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import MarketCardPrice
from app.services import price_index


class TestRangDesVariantes(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        # OP17-022 tel que la liste officielle et la boutique le donnent :
        # l'ordinaire, le parallele, le manga.
        for nom, slug, prix in (("Shanks", "shanks", 0.75),
                                ("Shanks (Parallèle 1)", "shanks-parallele-1", 13.0),
                                ("Shanks (Parallèle 2)", "shanks-parallele-2", 850.0)):
            self.db.add(MarketCardPrice(card_code="OP17-022", name_slug=slug,
                                        display_name=nom, rarity="SR", price_eur=prix,
                                        language="fr", source="opecards"))
        # Un code a UN seul parallele.
        for nom, slug, prix in (("Roronoa Zoro", "roronoa-zoro", 2.0),
                                ("Roronoa Zoro (Parallèle 1)", "roronoa-zoro-parallele-1", 40.0)):
            self.db.add(MarketCardPrice(card_code="OP01-025", name_slug=slug,
                                        display_name=nom, rarity="SR", price_eur=prix,
                                        language="en", source="opecards"))
        self.db.commit()
        price_index._slug_cache = None

    def tearDown(self):
        self.db.close()
        price_index._slug_cache = None

    def prix(self, titre):
        return price_index.find_price_for_listing(self.db, titre)

    def test_une_annonce_sans_mention_vaut_l_impression_ordinaire(self):
        """LE test. Avant correction : 13 EUR, le prix du parallele."""
        m = self.prix("Shanks OP17-022")
        self.assertEqual(m.row.price_eur, 0.75)
        self.assertEqual(m.confidence, "high")

    def test_parallele_et_alt_designent_la_premiere_alternative(self):
        for titre in ("Shanks OP17-022 parallèle", "Shanks OP17-022 alt art",
                      "Shanks OP17-022 alternative"):
            with self.subTest(titre=titre):
                self.assertEqual(self.prix(titre).row.price_eur, 13.0)

    def test_manga_designe_la_seconde_alternative(self):
        """Appariement etabli en comparant les images des deux sources."""
        m = self.prix("Shanks OP17-022 manga")
        self.assertEqual(m.row.price_eur, 850.0)
        self.assertEqual(m.confidence, "high")

    def test_jamais_la_mediane_de_plusieurs_versions(self):
        """La mediane de deux alternatives retombe sur la plus chere : c'est
        elle qui gonflait les marges."""
        prix = {self.prix(t).row.price_eur for t in (
            "Shanks OP17-022", "Shanks OP17-022 parallèle", "Shanks OP17-022 manga")}
        self.assertEqual(prix, {0.75, 13.0, 850.0})

    def test_un_manga_introuvable_donne_un_ordre_de_grandeur_signale(self):
        """Le code n'a qu'un parallele : rien ne prouve que ce soit le manga.
        On le retient pour l'ordre de grandeur, mais marque incertain."""
        m = self.prix("Roronoa Zoro OP01-025 manga")
        self.assertEqual(m.row.price_eur, 40.0)
        self.assertEqual(m.confidence, "low")
        self.assertIsNotNone(m.warning)

    def test_l_ordinaire_d_un_code_a_un_seul_parallele(self):
        self.assertEqual(self.prix("Roronoa Zoro OP01-025").row.price_eur, 2.0)


if __name__ == "__main__":
    unittest.main()
