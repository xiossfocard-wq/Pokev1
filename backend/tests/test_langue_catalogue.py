"""
Tests du marquage de LANGUE des fiches du catalogue.

POURQUOI CE MARQUAGE EXISTE
---------------------------
Le catalogue est rempli par deux sources qui ne parlent pas la même langue.
Le relevé npm publie « en » et « jp », jamais « fr » : les ~3 870 fiches
qu'il apporte portent donc des noms ANGLAIS. La liste officielle française,
elle, ne couvre que les séries OP09 et suivantes — le jeu français n'a pas
commencé plus tôt.

Résultat : une bonne partie du catalogue garde son nom anglais, et rien ne
le disait. Un utilisateur qui lit « Buggy » croyait lire un nom français.

CE QUE LA VALEUR DIT, ET CE QU'ELLE NE DIT PAS
----------------------------------------------
« en » ne prouve pas qu'une carte n'est jamais parue en français : il dit
qu'on ne l'a pas trouvée dans les séries françaises chargées jusqu'ici. Les
tests ci-dessous vérifient que l'application tient ce langage-là, et pas un
plus affirmatif.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.cardlist_fr import CarteFR
from app.collectors.opcg_dataset import convertir
from app.core import langues
from app.database import Base
from app.models import MarketCardPrice
from app.services.card_catalog import (
    carte_en_dict, rechercher_cartes, valeurs_de_filtres,
)
from app.services.catalog_fr import appliquer_noms_francais
from app.services.catalog_import import importer_catalogue


def entree_npm(code, nom, alternative=False):
    return {"card_number": code, "card_name": nom, "rarity": "C",
            "is_alternate_art": alternative, "card_sets": "-ROMANCE DAWN- [OP-01]"}


class BaseDeTest(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()

    def tearDown(self):
        self.db.close()

    def fiche(self, code):
        return self.db.query(MarketCardPrice).filter_by(card_code=code).first()


class TestSourceAnglaise(unittest.TestCase):
    def test_le_releve_npm_se_declare_anglais(self):
        """Ce paquet publie « en » et « jp », jamais « fr »."""
        lignes = convertir([entree_npm("OP01-001", "Roronoa Zoro")])
        self.assertEqual(lignes[0]["language"], langues.ANGLAIS)

    def test_les_alternatives_aussi(self):
        lignes = convertir([entree_npm("OP01-001", "Roronoa Zoro", alternative=True)])
        self.assertEqual(lignes[0]["language"], langues.ANGLAIS)


class TestBasculeVersLeFrancais(BaseDeTest):
    def test_une_fiche_retrouvee_cote_francais_cesse_d_etre_anglaise(self):
        """Etre dans la liste officielle francaise, c'est la definition meme
        d'une carte francaise."""
        importer_catalogue(self.db, convertir([entree_npm("OP17-001", "Edward Newgate")]))
        self.assertEqual(self.fiche("OP17-001").language, langues.ANGLAIS)

        appliquer_noms_francais(self.db, [
            CarteFR("OP17-001", "Edward Newgate", "L", "LEADER",
                    "Les Guerriers (OP-17)", None, 0),
        ])
        self.assertEqual(self.fiche("OP17-001").language, langues.FRANCAIS)

    def test_une_fiche_absente_de_la_liste_FR_reste_anglaise(self):
        """OP01 n'existe pas en francais : la fiche garde son nom anglais, et
        le dit."""
        importer_catalogue(self.db, convertir([
            entree_npm("OP01-001", "Roronoa Zoro"),
            entree_npm("OP17-001", "Edward Newgate"),
        ]))
        appliquer_noms_francais(self.db, [
            CarteFR("OP17-001", "Edward Newgate", "L", "LEADER",
                    "Les Guerriers (OP-17)", None, 0),
        ])
        self.assertEqual(self.fiche("OP01-001").language, langues.ANGLAIS)
        self.assertEqual(self.fiche("OP17-001").language, langues.FRANCAIS)

    def test_une_carte_creee_par_la_liste_FR_nait_francaise(self):
        appliquer_noms_francais(self.db, [
            CarteFR("OP17-004", "Caborage et Chavipère", "C", "PERSONNAGE",
                    "Les Guerriers (OP-17)", None, 0),
        ])
        self.assertEqual(self.fiche("OP17-004").language, langues.FRANCAIS)


class TestImportManuel(BaseDeTest):
    def test_un_import_muet_n_efface_pas_la_langue_etablie(self):
        """Un fichier de prix sans colonne « langue » ne doit pas defaire ce
        que la liste officielle a etabli."""
        appliquer_noms_francais(self.db, [
            CarteFR("OP17-001", "Edward Newgate", "L", "LEADER", None, None, 0),
        ])
        importer_catalogue(self.db, [
            {"card_code": "OP17-001", "display_name": "Edward Newgate",
             "price_eur": "9,00"},
        ])
        self.assertEqual(self.fiche("OP17-001").language, langues.FRANCAIS)

    def test_la_colonne_langue_est_acceptee(self):
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro",
             "price_eur": "4,00", "langue": "EN"},
        ])
        self.assertEqual(self.fiche("OP01-001").language, "en")


class TestExpositionDansLApi(BaseDeTest):
    def setUp(self):
        super().setUp()
        importer_catalogue(self.db, convertir([
            entree_npm("OP01-001", "Roronoa Zoro"),
            entree_npm("OP01-002", "Trafalgar Law"),
        ]))
        appliquer_noms_francais(self.db, [
            CarteFR("OP17-001", "Edward Newgate", "L", "LEADER", None, None, 0),
        ])

    def test_la_fiche_porte_la_langue_et_son_explication(self):
        anglaise = carte_en_dict(self.fiche("OP01-001"))
        self.assertEqual(anglaise["language"], "en")
        self.assertIn("liste officielle française", anglaise["language_note"])

    def test_l_explication_ne_sur_affirme_pas(self):
        """« pas trouvée dans la liste » et non « n'existe pas en français » :
        la fiche depend de ce qui a ete charge, pas d'une verite absolue."""
        note = carte_en_dict(self.fiche("OP01-001"))["language_note"]
        self.assertIn("n'a pas été trouvée", note)
        self.assertNotIn("n'existe pas", note)

    def test_filtrer_sur_l_anglais(self):
        res = rechercher_cartes(self.db, langue="en")
        self.assertEqual(res["total"], 2)
        self.assertTrue(all(c["language"] == "en" for c in res["cartes"]))

    def test_filtrer_sur_le_francais(self):
        res = rechercher_cartes(self.db, langue="fr")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["cartes"][0]["card_code"], "OP17-001")

    def test_sans_filtre_tout_est_rendu(self):
        """Les cartes anglaises RESTENT au catalogue : elles sont signalees,
        pas masquees."""
        self.assertEqual(rechercher_cartes(self.db)["total"], 3)

    def test_les_comptes_par_langue_sont_rendus(self):
        """« 3 870 cartes » laisserait croire a un catalogue francais complet."""
        comptes = {l["code"]: l["count"]
                   for l in valeurs_de_filtres(self.db)["languages"]}
        self.assertEqual(comptes["en"], 2)
        self.assertEqual(comptes["fr"], 1)

    def test_les_comptes_portent_un_libelle_lisible(self):
        libelles = {l["code"]: l["label"]
                    for l in valeurs_de_filtres(self.db)["languages"]}
        self.assertEqual(libelles["en"], "Anglais")
        self.assertEqual(libelles["fr"], "Français")


class TestLangueInconnue(BaseDeTest):
    def test_une_fiche_sans_langue_reste_visible(self):
        """Les masquer reviendrait a pretendre qu'elles n'existent pas."""
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro", "price_eur": "4,00"},
        ])
        self.assertIsNone(self.fiche("OP01-001").language)
        self.assertEqual(rechercher_cartes(self.db)["total"], 1)

    def test_on_peut_les_isoler(self):
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro", "price_eur": "4,00"},
        ])
        appliquer_noms_francais(self.db, [
            CarteFR("OP17-001", "Edward Newgate", "L", "LEADER", None, None, 0),
        ])
        res = rechercher_cartes(self.db, langue="inconnue")
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["cartes"][0]["card_code"], "OP01-001")

    def test_pas_d_explication_inventee(self):
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro", "price_eur": "4,00"},
        ])
        self.assertIsNone(carte_en_dict(self.fiche("OP01-001"))["language_note"])


if __name__ == "__main__":
    unittest.main()
