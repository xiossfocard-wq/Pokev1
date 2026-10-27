"""
Une page par personnage apprecie : toutes ses cartes, de la plus accessible
a la plus rare, et les conseils pour en faire une collection.
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
from app.models import MarketCardPrice
from app.routers.personnages import un_personnage
from app.services import collection, suivi
from app.services.personnages import liste_des_personnages, page_du_personnage, slug_de
from app.services.recommandations import analyse_de_la_carte, enregistrer_gouts, recommander


class BasePersonnages(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.n = 0

    def tearDown(self):
        self.db.close()

    def carte(self, nom, prix, rarete="SR (Super Rare)", parallele=False, langue="fr", image=True):
        self.n += 1
        slug = nom.lower().replace(" ", "-").replace(".", "-") + ("-parallele-1" if parallele else "")
        c = MarketCardPrice(card_code=f"OP10-{self.n:03d}", name_slug=slug,
                            display_name=nom + (" (Parallèle 1)" if parallele else ""),
                            rarity=rarete, price_eur=prix, language=langue, source="opecards",
                            image_url=f"https://img.test/{self.n}.png" if image else None)
        self.db.add(c)
        self.db.commit()
        return c

    def shanks(self):
        """Une gamme realiste : de la commune au graal."""
        return {
            "commune": self.carte("Shanks", 0.3, rarete="C (Common)"),
            "parallele": self.carte("Shanks", 8.0, parallele=True),
            "leader": self.carte("Shanks", 45.0, rarete="L (Leader)", parallele=True),
            "sp": self.carte("Shanks", 300.0, rarete="SP CARD (Special)"),
            "inconnue": self.carte("Shanks", None, parallele=True),
        }


class TestListe(BasePersonnages):
    def test_seuls_les_personnages_apprecies_ont_une_page(self):
        self.carte("Shanks", 8.0, parallele=True)
        self.carte("Soldat de la Marine", 0.2)
        self.assertEqual([p["nom"] for p in liste_des_personnages(self.db)], ["Shanks"])

    def test_les_icones_d_abord(self):
        self.carte("Perona", 4.0, parallele=True)
        self.carte("Nami", 6.0, parallele=True)
        self.assertEqual([p["nom"] for p in liste_des_personnages(self.db)], ["Nami", "Perona"])

    def test_le_resume_d_un_personnage(self):
        cartes = self.shanks()
        collection.ajouter(self.db, card_id=cartes["parallele"].id)
        p = liste_des_personnages(self.db)[0]
        self.assertEqual({k: p[k] for k in ("slug", "calibre", "cartes", "belles", "prix_min", "prix_max",
                                            "possedees", "belles_possedees")},
                         {"slug": "shanks", "calibre": "icone", "cartes": 5, "belles": 4, "prix_min": 0.3,
                          "prix_max": 300.0, "possedees": 1, "belles_possedees": 1})

    def test_les_cartes_francaises_par_defaut(self):
        self.carte("Zoro", 6.0, parallele=True, langue="en")
        self.assertEqual(liste_des_personnages(self.db), [])
        self.assertEqual(len(liste_des_personnages(self.db, toutes_langues=True)), 1)


class TestPage(BasePersonnages):
    def test_un_personnage_sans_page(self):
        self.assertIsNone(page_du_personnage(self.db, "soldat"))
        with self.assertRaises(HTTPException) as e:
            un_personnage("soldat", False, self.db)
        self.assertEqual(e.exception.status_code, 404)

    def test_de_la_plus_accessible_a_la_plus_rare(self):
        self.shanks()
        page = page_du_personnage(self.db, "shanks")
        self.assertEqual([(p["cle"], [c["price_eur"] for c in p["cartes"]]) for p in page["paliers"]],
                         [("petits-prix", [0.3]), ("abordables", [8.0]), ("pieces", [45.0]),
                          ("graals", [300.0]), ("sans-cote", [None])])

    def test_chaque_carte_dit_sa_version_et_ce_qu_on_en_a(self):
        cartes = self.shanks()
        collection.ajouter(self.db, card_id=cartes["parallele"].id)
        suivi.suivre(self.db, cartes["leader"].id, 40.0)
        toutes = {c["id"]: c for p in page_du_personnage(self.db, "shanks")["paliers"] for c in p["cartes"]}
        self.assertEqual(toutes[cartes["commune"].id]["version"], "ordinaire")
        self.assertEqual(toutes[cartes["parallele"].id]["version"], "parallèle")
        self.assertEqual(toutes[cartes["parallele"].id]["exemplaires"], 1)
        self.assertTrue(toutes[cartes["leader"].id]["suivie"])

    def test_dans_mes_gouts(self):
        self.shanks()
        self.assertFalse(page_du_personnage(self.db, "shanks")["aime"])
        enregistrer_gouts(self.db, ["Shanks"], [], [])
        self.assertTrue(page_du_personnage(self.db, "shanks")["aime"])


class TestConseils(BasePersonnages):
    def conseils(self):
        return {c["cle"]: c for c in page_du_personnage(self.db, "shanks")["conseils"]}

    def test_pour_commencer_et_le_graal(self):
        cartes = self.shanks()
        c = self.conseils()
        self.assertEqual(c["pour-commencer"]["carte"]["id"], cartes["parallele"].id)
        self.assertEqual(c["graal"]["carte"]["id"], cartes["sp"].id)
        self.assertIn("300,00\u00a0€", c["graal"]["texte"])

    def test_une_belle_version_deja_possedee_n_est_pas_conseillee(self):
        cartes = self.shanks()
        collection.ajouter(self.db, card_id=cartes["parallele"].id)
        self.assertEqual(self.conseils()["pour-commencer"]["carte"]["id"], cartes["leader"].id)

    def test_le_bon_rapport_face_aux_semblables(self):
        for nom in ("Luffy", "Zoro", "Nami", "Sanji", "Robin"):
            self.carte(nom, 15.0, parallele=True)
        bon = self.carte("Shanks", 5.0, parallele=True)
        self.carte("Shanks", 30.0, parallele=True)
        # 5 EUR : la plus abordable ET le bon rapport — une carte ne sert
        # qu'un conseil, le premier.
        c = self.conseils()
        self.assertEqual(c["pour-commencer"]["carte"]["id"], bon.id)
        self.assertNotIn("bon-plan", c)

    def test_ce_qui_monte(self):
        debut = self.carte("Shanks", 6.0, parallele=True)          # la plus abordable : « pour commencer »
        montante = self.carte("Shanks", 12.0, parallele=True)      # 9 -> 12 : +33 %
        montante.variation_7d_eur = 3.0
        self.db.commit()
        c = self.conseils()
        self.assertEqual(c["pour-commencer"]["carte"]["id"], debut.id)
        self.assertEqual(c["monte"]["carte"]["id"], montante.id)
        self.assertIn("33\u00a0%", c["monte"]["texte"])

    def test_la_fiche_d_une_carte_mene_a_son_personnage(self):
        c = self.carte("Boa Hancock", 9.0, parallele=True)
        self.assertEqual(analyse_de_la_carte(self.db, c)["personnage"], {"nom": "Boa Hancock", "slug": "boa-hancock"})
        self.assertIsNone(analyse_de_la_carte(self.db, self.carte("Soldat", 1.0))["personnage"])

    def test_le_projet_d_un_personnage_mene_a_sa_page(self):
        self.carte("Boa Hancock", 9.0, parallele=True)
        enregistrer_gouts(self.db, ["Boa Hancock"], [], [])
        projet = recommander(self.db)["projets"][0]
        self.assertEqual((projet["nature"], projet["slug"]), ("personnage", "boa-hancock"))
        self.assertIsNotNone(page_du_personnage(self.db, projet["slug"]))



class TestSlug(unittest.TestCase):
    def test_les_noms_deviennent_des_adresses(self):
        self.assertEqual(slug_de("Boa Hancock"), "boa-hancock")
        self.assertEqual(slug_de("Gol D. Roger"), "gol-d-roger")
        self.assertEqual(slug_de("Barbe Blanche"), "barbe-blanche")


if __name__ == "__main__":
    unittest.main()
