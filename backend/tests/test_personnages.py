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
from app.models import CarteSuivie, Listing, ListingStatus, MarketCardPrice, SourcePlatform
from app.routers.personnages import Chasse, chasser, les_personnages, un_personnage
from app.services import collection, suivi
from app.services.personnages import (cartes_de_mes_personnages, chasser_les_belles_versions,
                                     liste_des_personnages, page_du_personnage, par_qui_commencer,
                                     slug_de)
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

    def test_ce_qui_manque_a_petit_prix(self):
        cartes = self.shanks()
        self.carte("Shanks", 12.0, parallele=True)
        collection.ajouter(self.db, card_id=cartes["parallele"].id)
        p = liste_des_personnages(self.db)[0]
        # Belles versions : 8 (possedee), 12, 45, 300 et une sans cote. A
        # moins de 20 EUR et qui manque : seulement celle a 12 EUR.
        self.assertEqual((p["belles_des"], p["belles_a_petit_prix"], p["cout_belles_a_petit_prix"]),
                         (8.0, 1, 12.0))

    def test_tes_personnages_et_ce_qui_est_en_vente(self):
        c = self.carte("Shanks", 8.0, parallele=True)
        self.db.add(Listing(source=SourcePlatform.VINTED, external_id="1", title="Shanks", description="",
                            url="https://vinted.test/1", price=6.0, currency="EUR", photo_urls=[],
                            matched_card_id=c.id, deal_score=70.0))
        self.db.commit()
        enregistrer_gouts(self.db, ["Shanks"], [], [])
        p = liste_des_personnages(self.db)[0]
        self.assertEqual((p["aime"], p["en_vente"]), (True, 1))

    def test_les_cartes_francaises_par_defaut(self):
        self.carte("Zoro", 6.0, parallele=True, langue="en")
        self.assertEqual(liste_des_personnages(self.db), [])
        self.assertEqual(len(liste_des_personnages(self.db, toutes_langues=True)), 1)


class TestParQuiCommencer(BasePersonnages):
    def test_le_plus_de_belles_versions_a_petit_prix(self):
        for prix in (4.0, 6.0, 9.0):
            self.carte("Perona", prix, parallele=True)
        for prix in (5.0, 7.0):
            self.carte("Nami", prix, parallele=True)
        for prix in (3.0, 4.0):
            self.carte("Zoro", prix, parallele=True)
        self.carte("Sanji", 5.0, parallele=True)          # une seule : pas un projet
        self.carte("Sabo", 60.0, parallele=True)          # trop chere
        conseils = par_qui_commencer(liste_des_personnages(self.db))
        # Perona d'abord (3 cartes) ; puis, a nombre egal, Zoro (7 EUR) avant Nami (12 EUR).
        self.assertEqual([c["slug"] for c in conseils], ["perona", "zoro", "nami"])
        self.assertEqual(conseils[0]["raison"], "3 belles versions à moins de 20\u00a0€ : 19,00\u00a0€ pour les\u00a03.")

    def test_ce_qu_on_a_deja_ne_compte_pas(self):
        a = self.carte("Perona", 4.0, parallele=True)
        for prix in (6.0, 9.0):
            self.carte("Perona", prix, parallele=True)
        collection.ajouter(self.db, card_id=a.id)
        conseil = par_qui_commencer(liste_des_personnages(self.db))[0]
        self.assertEqual(conseil["raison"], "2 belles versions à moins de 20\u00a0€ qui te manquent : 15,00\u00a0€ pour les\u00a02.")

    def test_pas_ceux_qu_on_aime_deja(self):
        for nom in ("Perona", "Nami"):
            for prix in (4.0, 6.0):
                self.carte(nom, prix, parallele=True)
        enregistrer_gouts(self.db, ["Nami"], [], [])
        self.assertEqual([c["slug"] for c in par_qui_commencer(liste_des_personnages(self.db))], ["perona"])

    def test_la_reponse_de_l_api(self):
        self.carte("Shanks", 8.0, parallele=True)
        reponse = les_personnages(False, self.db)
        self.assertEqual(set(reponse), {"personnages", "par_qui_commencer"})
        self.assertEqual(reponse["personnages"][0]["slug"], "shanks")


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



class TestEnVente(BasePersonnages):
    def annonce(self, carte, prix, score, **champs):
        self.n += 1
        a = Listing(source=SourcePlatform.VINTED, external_id=str(self.n), title=f"annonce {self.n}",
                    description="", url=f"https://vinted.test/{self.n}", price=prix, shipping_price=0.0,
                    currency="EUR", photo_urls=[], matched_card_id=carte.id, deal_score=score, **champs)
        self.db.add(a)
        self.db.commit()
        return a

    def test_ses_cartes_en_vente_les_meilleures_affaires_d_abord(self):
        cartes = self.shanks()
        moyenne = self.annonce(cartes["parallele"], 7.0, 55.0)
        bonne = self.annonce(cartes["leader"], 30.0, 82.0)
        self.annonce(self.carte("Nami", 6.0, parallele=True), 4.0, 95.0)  # un autre personnage
        page = page_du_personnage(self.db, "shanks")
        self.assertEqual([a["id"] for a in page["annonces"]], [bonne.id, moyenne.id])
        self.assertEqual(page["annonces"][0]["carte"]["id"], cartes["leader"].id)
        self.assertEqual(page["annonces"][0]["carte"]["version"], "parallèle")

    def test_les_annonces_cachees_ne_reviennent_pas(self):
        cartes = self.shanks()
        self.annonce(cartes["parallele"], 7.0, 90.0, manual_status="hidden")
        self.annonce(cartes["parallele"], 7.0, 90.0, status=ListingStatus.UNAVAILABLE)
        visible = self.annonce(cartes["parallele"], 7.0, 60.0)
        page = page_du_personnage(self.db, "shanks")
        self.assertEqual([a["id"] for a in page["annonces"]], [visible.id])
        toutes = {c["id"]: c for p in page["paliers"] for c in p["cartes"]}
        self.assertEqual(toutes[cartes["parallele"].id]["en_vente"], 1)
        self.assertEqual(toutes[cartes["sp"].id]["en_vente"], 0)


class TestChasse(BasePersonnages):
    def suivies(self):
        return {(s.card_code, s.name_slug): s.prix_max for s in self.db.query(CarteSuivie).all()}

    def test_suivre_ses_belles_versions_manquantes_dans_le_budget(self):
        cartes = self.shanks()
        # 8 EUR (parallele) et 45 EUR (leader) : seule la premiere tient dans 20 EUR.
        # La commune n'est pas une belle version ; la SP depasse le budget.
        resultat = chasser_les_belles_versions(self.db, "shanks", 20.0)
        self.assertEqual(resultat, {"ajoutees": 1, "cout": 8.0})
        p = cartes["parallele"]
        self.assertEqual(self.suivies(), {(p.card_code, p.name_slug): 8.0})

    def test_ni_ce_qu_on_a_ni_ce_qu_on_suit_deja(self):
        cartes = self.shanks()
        collection.ajouter(self.db, card_id=cartes["parallele"].id)
        suivi.suivre(self.db, cartes["leader"].id, 40.0)
        self.assertEqual(chasser_les_belles_versions(self.db, "shanks", 100.0)["ajoutees"], 0)
        l = cartes["leader"]
        self.assertEqual(self.suivies()[(l.card_code, l.name_slug)], 40.0)  # budget choisi conserve

    def test_la_cote_arrondie_devient_le_budget(self):
        c = self.carte("Shanks", 6.18, parallele=True)
        chasser("shanks", Chasse(budget_max=10), self.db)
        self.assertEqual(self.suivies(), {(c.card_code, c.name_slug): 7.0})

    def test_un_personnage_sans_page(self):
        with self.assertRaises(HTTPException) as e:
            chasser("soldat", Chasse(budget_max=10), self.db)
        self.assertEqual(e.exception.status_code, 404)


class TestMesPersonnages(BasePersonnages):
    def test_le_radar_filtre_sur_les_fiches_de_mes_personnages(self):
        fr = self.carte("Shanks", 8.0, parallele=True)
        en = self.carte("Shanks", 6.0, langue="en")   # une annonce peut viser la fiche anglaise
        self.carte("Nami", 6.0, parallele=True)
        self.assertEqual(cartes_de_mes_personnages(self.db), {"personnages": [], "card_ids": []})
        enregistrer_gouts(self.db, ["Shanks"], [], [])
        self.assertEqual(cartes_de_mes_personnages(self.db),
                         {"personnages": ["Shanks"], "card_ids": [fr.id, en.id]})


class TestCollectionParPersonnage(BasePersonnages):
    def test_ce_que_la_collection_compte_de_chaque_personnage(self):
        cartes = self.shanks()
        nami = self.carte("Nami", 6.0, parallele=True)
        soldat = self.carte("Soldat de la Marine", 0.5)
        for c in (cartes["parallele"], cartes["parallele"], cartes["leader"], nami, soldat):
            collection.ajouter(self.db, card_id=c.id)
        resultat = collection.lister(self.db)
        self.assertEqual(resultat["par_personnage"], [
            {"nom": "Shanks", "slug": "shanks", "cartes": 2, "exemplaires": 3, "valeur": 61.0},
            {"nom": "Nami", "slug": "nami", "cartes": 1, "exemplaires": 1, "valeur": 6.0},
        ])
        par_id = {c["id"]: c for c in resultat["cartes"]}
        self.assertEqual(par_id[nami.id]["personnage"], {"nom": "Nami", "slug": "nami"})
        self.assertIsNone(par_id[soldat.id]["personnage"])


class TestSlug(unittest.TestCase):
    def test_les_noms_deviennent_des_adresses(self):
        self.assertEqual(slug_de("Boa Hancock"), "boa-hancock")
        self.assertEqual(slug_de("Gol D. Roger"), "gol-d-roger")
        self.assertEqual(slug_de("Barbe Blanche"), "barbe-blanche")


if __name__ == "__main__":
    unittest.main()
