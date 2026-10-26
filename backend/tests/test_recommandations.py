"""
Les idees de collection : ce qu'un connaisseur conseillerait, et pourquoi.

Chaque regle est verifiee dans les deux sens : la carte qui la remplit est
retenue avec sa raison, celle qui ne la remplit pas ne l'est pas. Une
suggestion sans raison claire, ou une raison inventee (une « hausse » de
0,10 EUR, une carte « sous-cotee » face a deux cartes), ne vaudrait rien.
"""
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import CardPriceSnapshot, MarketCardPrice
from app.routers.recommandations import pas_pour_moi, revoir_les_cartes_ecartees
from app.services import card_themes, collection, suivi
from app.services.recommandations import personnage, recommander


class BaseReco(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.db = sessionmaker(bind=moteur)()
        self.n = 0

    def tearDown(self):
        self.db.close()

    def carte(self, nom, prix, rarete="SR (Super Rare)", parallele=False, langue="fr",
              variation=None, code=None):
        self.n += 1
        slug = nom.lower().replace(" ", "-").replace(".", "-") + ("-parallele-1" if parallele else "")
        c = MarketCardPrice(card_code=code or f"OP10-{self.n:03d}", name_slug=slug,
                            display_name=nom + (" (Parallèle 1)" if parallele else ""),
                            rarity=rarete, price_eur=prix, variation_7d_eur=variation,
                            language=langue, source="opecards",
                            theme_slugs=card_themes.encoder_themes(card_themes.themes_de_la_carte(nom, rarete)))
        self.db.add(c)
        self.db.commit()
        return c

    def rubrique(self, resultat, cle):
        return next((r for r in resultat["rubriques"] if r["cle"] == cle), {"cartes": []})

    def codes(self, resultat, cle):
        return [c["card_code"] for c in self.rubrique(resultat, cle)["cartes"]]

    def carte_proposee(self, resultat, code):
        """La carte, dans quelque rubrique qu'elle soit (chacune n'apparait
        qu'une fois)."""
        return next(c for r in resultat["rubriques"] for c in r["cartes"] if c["card_code"] == code)

    def raisons(self, resultat, code, type_):
        return [x["texte"] for x in self.carte_proposee(resultat, code)["raisons"] if x["type"] == type_]


class TestPersonnages(unittest.TestCase):
    def test_les_graphies_du_catalogue(self):
        for nom, attendu in (("Monkey.D.Luffy", "Luffy"), ("Portgas.D.Ace", "Ace"),
                             ("Trafalgar Law", "Law"), ('Eustass"Captain"Kid', "Kid"),
                             ("Roronoa Zoro", "Zoro"), ("Edward.Newgate", "Barbe Blanche")):
            with self.subTest(nom=nom):
                self.assertEqual(personnage(nom)[0], attendu)

    def test_pas_de_faux_ami(self):
        """« ace » dans « Lacey », « law » dans « Lawrence » : non."""
        self.assertEqual(personnage("Lacey")[0], None)
        self.assertEqual(personnage("Lawrence")[0], None)


class TestCoupsDeCoeur(BaseReco):
    def test_une_belle_carte_d_un_personnage_phare_dans_le_budget(self):
        shanks = self.carte("Shanks", 8.5, parallele=True, code="OP10-001")
        r = recommander(self.db, budget_max=20)
        cartes = self.rubrique(r, "coups-de-coeur")["cartes"]
        self.assertEqual([c["card_code"] for c in cartes], ["OP10-001"])
        types = {x["type"] for x in cartes[0]["raisons"]}
        self.assertTrue({"visuel", "personnage"} <= types)
        self.assertIn("Shanks", cartes[0]["avis"])
        self.assertIn("8,50 €", cartes[0]["avis"])

    def test_pas_plus_de_deux_cartes_d_un_meme_personnage(self):
        for i in range(4):
            self.carte("Shanks", 6.0 + i, parallele=True)
        self.carte("Nami", 9.0, parallele=True, code="OP10-099")
        persos = [c["display_name"].split(" (")[0]
                  for c in self.rubrique(recommander(self.db), "coups-de-coeur")["cartes"]]
        self.assertEqual(persos.count("Shanks"), 2)
        self.assertIn("Nami", persos)

    def test_ni_l_ordinaire_banale_ni_la_carte_hors_budget(self):
        self.carte("Shanks", 0.2, rarete="C (Common)", code="OP10-001")       # rien de beau
        self.carte("Shanks", 850.0, parallele=True, code="OP10-002")          # hors budget
        self.carte("Gardien anonyme", 5.0, parallele=True, code="OP10-003")   # personnage inconnu
        self.assertEqual(self.codes(recommander(self.db, budget_max=20), "coups-de-coeur"), [])

    def test_les_cartes_francaises_par_defaut(self):
        self.carte("Zoro", 6.0, parallele=True, langue="en", code="OP01-025")
        self.assertEqual(self.codes(recommander(self.db), "coups-de-coeur"), [])
        self.assertEqual(self.codes(recommander(self.db, toutes_langues=True), "coups-de-coeur"),
                         ["OP01-025"])


class TestMarche(BaseReco):
    def test_une_hausse_mesuree_est_signalee(self):
        self.carte("Hody Jones", 10.0, parallele=True, variation=2.0, code="OP10-001")   # 8 -> 10 : +25 %
        r = recommander(self.db)
        self.assertEqual(self.codes(r, "en-hausse"), ["OP10-001"])
        self.assertEqual(self.raisons(r, "OP10-001", "tendance"), ["en hausse de 25 % ces derniers jours"])

    def test_une_icone_en_hausse_est_un_coup_de_coeur_qui_le_dit(self):
        """Chaque carte n'apparait qu'une fois : dans la premiere rubrique
        qui la retient, avec toutes ses raisons."""
        self.carte("Nami", 10.0, parallele=True, variation=2.0, code="OP10-001")
        r = recommander(self.db)
        self.assertEqual(self.codes(r, "coups-de-coeur"), ["OP10-001"])
        self.assertEqual(self.codes(r, "en-hausse"), [])
        self.assertEqual(self.raisons(r, "OP10-001", "tendance"), ["en hausse de 25 % ces derniers jours"])

    def test_une_variation_de_quelques_centimes_n_est_pas_une_hausse(self):
        self.carte("Nami", 0.5, parallele=True, variation=0.2, code="OP10-001")    # +67 %, mais 0,20 EUR
        self.assertEqual(self.codes(recommander(self.db), "en-hausse"), [])

    def test_une_hausse_sur_un_mois_d_apres_les_releves(self):
        robin = self.carte("Hody Jones", 12.0, parallele=True, code="OP10-001")
        self.db.add(CardPriceSnapshot(card_code=robin.card_code, name_slug=robin.name_slug,
                                      price_eur=9.0, captured_on=date.today() - timedelta(days=20)))
        self.db.commit()
        r = recommander(self.db)
        self.assertEqual(self.codes(r, "en-hausse"), ["OP10-001"])

    def test_moins_chere_que_ses_semblables(self):
        for i, prix in enumerate((14.0, 15.0, 16.0, 15.5, 14.5)):
            self.carte(["Luffy", "Zoro", "Nami", "Sanji", "Robin"][i], prix, parallele=True)
        law = self.carte("Law", 6.0, parallele=True, code="OP10-099")
        r = recommander(self.db)
        self.assertIn("moins chère que les cartes comparables", " ".join(self.raisons(r, "OP10-099", "sous-cotee")))
        self.assertEqual(self.raisons(r, "OP10-001", "sous-cotee"), [])

    def test_un_figurant_bon_marche_n_est_pas_une_pepite(self):
        """Une illustration alternative d'un personnage peu connu est bon
        marche parce qu'elle est peu demandee."""
        for i, prix in enumerate((4.0, 4.5, 5.0, 4.2, 4.8)):
            self.carte(f"Soldat {i}", prix, parallele=True)
        self.carte("Soldat X", 1.0, parallele=True, code="OP10-099")
        self.assertEqual(self.codes(recommander(self.db), "sous-cotees"), [])

    def test_trop_peu_de_comparables_pour_juger(self):
        self.carte("Luffy", 15.0, parallele=True)
        self.carte("Law", 6.0, parallele=True)
        self.assertEqual(self.codes(recommander(self.db), "sous-cotees"), [])


class TestGouts(BaseReco):
    def test_une_carte_possedee_n_est_pas_proposee(self):
        shanks = self.carte("Shanks", 8.5, parallele=True)
        collection.ajouter(self.db, card_id=shanks.id, prix_paye=8.0)
        self.assertEqual(self.codes(recommander(self.db), "coups-de-coeur"), [])

    def test_pas_pour_moi_puis_tout_revoir(self):
        shanks = self.carte("Shanks", 8.5, parallele=True, code="OP10-001")
        pas_pour_moi(shanks.id, self.db)
        self.assertEqual(self.codes(recommander(self.db), "coups-de-coeur"), [])
        revoir_les_cartes_ecartees(self.db)
        self.assertEqual(self.codes(recommander(self.db), "coups-de-coeur"), ["OP10-001"])

    def test_dans_la_lignee_de_ce_qu_on_collectionne(self):
        zoro_ordinaire = self.carte("Roronoa Zoro", 1.0, rarete="R (Rare)")
        self.carte("Roronoa Zoro", 9.0, parallele=True, code="OP10-050")
        collection.ajouter(self.db, card_id=zoro_ordinaire.id)
        r = recommander(self.db)
        self.assertEqual(self.raisons(r, "OP10-050", "collection"), ["tu as déjà 1 carte de Zoro"])
        # Avec une collection, ce qui la prolonge vient en premier.
        self.assertEqual(r["rubriques"][0]["cle"], "pour-ta-collection")
        self.assertEqual(self.codes(r, "pour-ta-collection"), ["OP10-050"])

    def test_le_gout_se_lit_aussi_sur_les_series_sans_version_francaise(self):
        shanks_op01 = self.carte("Shanks", 30.0, rarete="SEC (Secret Rare)", langue="en", code="OP01-120")
        self.carte("Shanks", 9.0, parallele=True, code="OP10-060")
        collection.ajouter(self.db, card_id=shanks_op01.id)
        r = recommander(self.db)
        self.assertEqual(r["rubriques"][0]["cle"], "pour-ta-collection")
        self.assertEqual(self.raisons(r, "OP10-060", "collection"), ["tu as déjà 1 carte de Shanks"])

    def test_une_carte_suivie_ne_se_recommande_pas_elle_meme(self):
        """Suivre la parallele de Shanks ne la rend pas « dans la lignee de
        ta collection » : l'affinite se mesure sur les AUTRES cartes."""
        shanks = self.carte("Shanks", 8.5, parallele=True, code="OP10-001")
        suivi.suivre(self.db, shanks.id, 10.0)
        r = recommander(self.db)
        self.assertEqual(self.raisons(r, "OP10-001", "collection"), [])

    def test_suivre_n_est_pas_posseder(self):
        zoro = self.carte("Roronoa Zoro", 1.0, rarete="R (Rare)")
        self.carte("Roronoa Zoro", 9.0, parallele=True, code="OP10-050")
        suivi.suivre(self.db, zoro.id, 2.0)
        self.assertEqual(self.raisons(recommander(self.db), "OP10-050", "collection"),
                         ["tu suis déjà 1 carte de Zoro"])

    def test_une_carte_suivie_est_signalee(self):
        shanks = self.carte("Shanks", 8.5, parallele=True)
        suivi.suivre(self.db, shanks.id, 10.0)
        carte = self.rubrique(recommander(self.db), "coups-de-coeur")["cartes"][0]
        self.assertTrue(carte["suivie"])


class TestIdeesDeCollection(BaseReco):
    def test_un_equipage_en_versions_alternatives_et_son_cout(self):
        for nom, prix in (("Monkey.D.Luffy", 12.0), ("Roronoa Zoro", 9.0), ("Nami", 7.0)):
            self.carte(nom, prix, parallele=True)
        idees = recommander(self.db)["themes"]
        paille = next(i for i in idees if i["slug"] == "chapeau-de-paille")
        self.assertEqual((paille["nombre"], paille["total_eur"]), (3, 28.0))


if __name__ == "__main__":
    unittest.main()
