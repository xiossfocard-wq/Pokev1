"""
Tests du controle de justesse des prix et de langue des cartes.

Chaque anomalie est verifiee dans les deux sens : qu'elle est trouvee quand
elle est la, et qu'elle n'est PAS signalee sur une carte saine. Un controle
qui crie a chaque carte ne serait plus lu.
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
from app.services import controle_qualite as cq


class BaseEnMemoire(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()

    def tearDown(self):
        self.db.close()

    def carte(self, code, nom, prix=None, rarete="C", langue="fr",
              slug=None, source="opecards"):
        self.db.add(MarketCardPrice(
            card_code=code, display_name=nom, rarity=rarete, language=langue,
            name_slug=slug or nom.lower().replace(" ", "-"),
            price_eur=prix, source=source if prix is not None else None))
        self.db.commit()

    def toutes(self):
        return self.db.query(MarketCardPrice).all()


class TestPrix(BaseEnMemoire):
    def test_une_variante_bradee_par_rapport_a_sa_base_est_signalee(self):
        """Le defaut historique : le manga a 0,75 EUR, l'ordinaire a 850."""
        self.carte("OP17-022", "Shanks", 850.0, "SR")
        self.carte("OP17-022", "Shanks (Parallèle 2)", 0.75, "SR",
                   slug="shanks-parallele-2")
        r = cq.controler_prix(self.toutes())
        self.assertEqual(r["variantes_moins_cheres_que_la_base"]["nombre"], 1)

    def test_une_variante_plus_chere_n_est_pas_signalee(self):
        self.carte("OP17-022", "Shanks", 0.75, "SR")
        self.carte("OP17-022", "Shanks (Parallèle 2)", 850.0, "SR",
                   slug="shanks-parallele-2")
        r = cq.controler_prix(self.toutes())
        self.assertEqual(r["variantes_moins_cheres_que_la_base"]["nombre"], 0)

    def test_un_prix_aberrant_pour_sa_rarete_est_signale(self):
        for i in range(10):
            self.carte(f"OP10-{i:03d}", f"Commune {i}", 0.20 + i * 0.02)
        self.carte("OP10-099", "Commune a 50 euros", 50.0)
        r = cq.controler_prix(self.toutes())
        signales = [e["code"] for e in r["prix_aberrants_pour_la_rarete"]["exemples"]]
        self.assertEqual(signales, ["OP10-099"])

    def test_une_rarete_trop_peu_representee_n_est_pas_jugee(self):
        """Une mediane sur trois cartes ne dit rien."""
        self.carte("OP10-001", "SEC 1", 300.0, "SEC")
        self.carte("OP10-002", "SEC 2", 2.0, "SEC")
        r = cq.controler_prix(self.toutes())
        self.assertEqual(r["prix_aberrants_pour_la_rarete"]["nombre"], 0)

    def test_un_prix_venu_d_une_autre_source_est_signale(self):
        """Un reste de l'ancien index Pokemon ne dit pas ce que vaut une
        carte francaise."""
        self.carte("OP10-001", "Nami", 3.0, source="opecards")
        self.carte("SV01-001", "Pikachu", 2.0, langue=None, source="zebradex")
        r = cq.controler_prix(self.toutes())
        self.assertEqual(r["prix_hors_source_francaise"]["nombre"], 1)
        self.assertEqual(r["prix_par_source"], {"opecards": 1, "zebradex": 1})


class TestLangue(BaseEnMemoire):
    def test_une_carte_anglaise_dans_une_serie_francaise_est_signalee(self):
        self.carte("OP09-001", "Shanks", langue="fr")
        self.carte("OP09-002", "Lucky Roux", langue="en")
        r = cq.controler_langue(self.toutes())
        self.assertEqual(r["anglaises_dans_une_serie_francaise"]["nombre"], 1)
        self.assertEqual(r["anglaises_dans_une_serie_francaise"]["par_serie"], {"OP09": 1})

    def test_une_carte_d_une_serie_absente_du_jeu_francais_est_normale(self):
        """OP01 n'existe qu'en anglais : sa carte anglaise n'est pas une
        anomalie, elle est simplement signalee « nom anglais »."""
        self.carte("OP09-001", "Shanks", langue="fr")
        self.carte("OP01-001", "Roronoa Zoro", langue="en")
        r = cq.controler_langue(self.toutes())
        self.assertEqual(r["anglaises_dans_une_serie_francaise"]["nombre"], 0)
        self.assertEqual(r["anglaises_hors_jeu_francais"], 1)

    def test_une_carte_chiffree_en_francais_mais_marquee_anglaise(self):
        """La boutique francaise ne vend que des cartes francaises."""
        self.carte("OP01-120", "Monkey.D.Luffy", 4.0, langue="en", source="opecards")
        r = cq.controler_langue(self.toutes())
        self.assertEqual(r["chiffrees_en_francais_mais_marquees_anglaises"]["nombre"], 1)


class TestAnnonces(BaseEnMemoire):
    def annonce(self, titre, statut=ListingStatus.SCORED):
        self.db.add(Listing(source=SourcePlatform.VINTED, external_id=titre[:20],
                            title=titre, url="https://vinted.test", price=10.0,
                            status=statut))
        self.db.commit()

    def test_les_annonces_que_le_filtre_actuel_ecarterait(self):
        self.annonce("Carte one piece Katakuri op03-099 alt art EN psa 10")
        self.annonce("Monkey D. Luffy OP01-120 très bon état")
        r = cq.controler_annonces(self.db)
        self.assertEqual(r["annonces_visibles"], 2)
        self.assertEqual(r["que_le_filtre_actuel_ecarterait"]["nombre"], 1)

    def test_une_annonce_deja_ecartee_n_est_pas_recomptee(self):
        self.annonce("Buggy SP Wanted US", statut=ListingStatus.IGNORED)
        r = cq.controler_annonces(self.db)
        self.assertEqual(r["annonces_visibles"], 0)


if __name__ == "__main__":
    unittest.main()
