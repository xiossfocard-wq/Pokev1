"""
Tests du catalogue issu du releve de la liste officielle
(collectors/opcg_dataset.py) et de ce que son arrivee change ailleurs.

Pourquoi ces tests existent : le catalogue etait vide, et un catalogue vide
vide tout le reste. Cette source le remplit pour de bon — 3868 fiches reelles
— mais elle introduit deux situations que le code ne rencontrait jamais, et
qui sont precisement celles qui peuvent mentir a l'utilisateur :

  1. Une carte SANS PRIX connu. Il ne doit en sortir ni marge, ni score, ni
     tendance — et surtout pas un 0.00 EUR qui se lirait comme « sans
     valeur ». Il faut aussi qu'un import sans prix n'EFFACE pas les prix
     deja connus.

  2. Un code qui designe DEUX cartes, l'ordinaire et son illustration
     alternative. Sur ce marche l'alternative vaut plusieurs fois
     l'ordinaire : les confondre ne fait pas une petite imprecision, ca
     fabrique une bonne affaire qui n'existe pas.
"""
import gzip
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors import opcg_dataset
from app.collectors.opcg_dataset import (
    _nettoyer_serie, _rarete_lisible, charger_catalogue, charger_instantane,
    convertir, ecrire_instantane,
)
from app.database import Base
from app.models import MarketCardPrice
from app.services.card_themes import themes_de_la_carte
from app.services.catalog_import import importer_catalogue
from app.services.price_index import find_price_for_listing


def entree(code, nom, rarete="C", alternative=False, serie="-ROMANCE DAWN- [OP-01]"):
    """Une entree brute, a la forme exacte que publie la source."""
    return {
        "card_number": code, "card_name": nom, "rarity": rarete,
        "is_alternate_art": alternative, "card_sets": serie,
    }


class BaseDeTest(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()

    def tearDown(self):
        self.db.close()

    def cartes(self):
        return self.db.query(MarketCardPrice).all()


class TestNettoyageSerie(unittest.TestCase):
    def test_tirets_et_crochets_deviennent_lisibles(self):
        self.assertEqual(_nettoyer_serie("-ROMANCE DAWN- [OP-01]"),
                         "Romance Dawn (OP-01)")

    def test_les_mots_de_liaison_restent_en_minuscules(self):
        """« Kingdoms Of Intrigue » se lit mal ; ce n'est pas de l'anglais."""
        self.assertEqual(_nettoyer_serie("-KINGDOMS OF INTRIGUE- [OP-04]"),
                         "Kingdoms of Intrigue (OP-04)")
        self.assertEqual(_nettoyer_serie("-AWAKENING OF THE NEW ERA- [OP-05]"),
                         "Awakening of the New Era (OP-05)")

    def test_apostrophe_ne_coupe_pas_le_mot(self):
        """« KAMI'S » doit donner « Kami's », pas « Kami'S »."""
        self.assertIn("Kami's", _nettoyer_serie("-ADVENTURE ON KAMI'S ISLAND- [OP-15]"))

    def test_serie_absente(self):
        for vide in (None, "", "-", "   "):
            self.assertIsNone(_nettoyer_serie(vide))

    def test_sans_code_entre_crochets(self):
        self.assertEqual(_nettoyer_serie("-PARAMOUNT WAR-"), "Paramount War")


class TestRarete(unittest.TestCase):
    def test_le_code_brut_reste_en_tete(self):
        """Les motifs de themes testent « \\bsr\\b », et les vendeurs
        francais ecrivent « SR » : le code doit rester present."""
        self.assertEqual(_rarete_lisible("SR"), "SR (Super Rare)")
        self.assertEqual(_rarete_lisible("SEC"), "SEC (Secret Rare)")
        self.assertEqual(_rarete_lisible("L"), "L (Leader)")

    def test_rarete_inconnue_passe_telle_quelle(self):
        """Une rarete ajoutee par l'editeur apres coup ne doit pas
        disparaitre parce qu'elle n'est pas dans la table."""
        self.assertEqual(_rarete_lisible("XYZ"), "XYZ")

    def test_rarete_absente(self):
        self.assertIsNone(_rarete_lisible(None))


class TestConversion(unittest.TestCase):
    def test_l_alternative_est_marquee_dans_le_nom(self):
        lignes = convertir([
            entree("OP01-001", "Roronoa Zoro", "L"),
            entree("OP01-001", "Roronoa Zoro", "L", alternative=True),
        ])
        noms = sorted(l["display_name"] for l in lignes)
        # Le rang est dans le nom, meme ici ou cette source n'en distingue
        # qu'un seul : la liste officielle FR numerote les siennes, et les
        # deux doivent se rapprocher sur la meme cle.
        self.assertEqual(noms, ["Roronoa Zoro", "Roronoa Zoro (Parallèle 1)"])

    def test_un_code_donne_deux_fiches_au_plus(self):
        """La source republie une meme alternative dans plusieurs coffrets.
        Une annonce francaise dit « parallele » sans jamais dire de quel
        coffret : une distinction que le titre ne porte pas est une
        distinction qu'on ne saurait pas rapprocher."""
        lignes = convertir([
            entree("OP01-001", "Roronoa Zoro", "L"),
            entree("OP01-001", "Roronoa Zoro", "L", alternative=True),
            entree("OP01-001", "Roronoa Zoro", "L", alternative=True,
                   serie="Premium Card Collection -25th Edition-"),
        ])
        self.assertEqual(len(lignes), 2)

    def test_la_langue_est_dite(self):
        """Cette source publie « en » et « jp », jamais « fr ». Le nom repris
        est donc l'anglais, et la fiche doit le dire — sinon l'utilisateur
        croit lire un nom francais."""
        lignes = convertir([entree("OP01-001", "Roronoa Zoro")])
        self.assertEqual(lignes[0]["language"], "en")

    def test_aucun_prix_n_est_invente(self):
        lignes = convertir([entree("OP01-001", "Roronoa Zoro")])
        self.assertEqual(lignes[0]["price_eur"], "")

    def test_entrees_inutilisables_ecartees(self):
        lignes = convertir([
            entree("", "Sans code"),
            entree("OP01-005", ""),
            {"card_number": "OP01-006", "card_name": "Bonne"},
        ])
        self.assertEqual([l["card_code"] for l in lignes], ["OP01-006"])


class TestInstantane(unittest.TestCase):
    def test_aller_retour(self):
        lignes = convertir([
            entree("OP01-001", "Roronoa Zoro", "L"),
            entree("OP01-001", "Roronoa Zoro", "L", alternative=True),
        ])
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "x.csv.gz")
            ecrire_instantane(lignes, chemin)
            relu = charger_instantane(chemin)
        self.assertEqual(len(relu), 2)
        self.assertEqual(relu[0]["card_code"], "OP01-001")
        self.assertIn("Parallèle", relu[1]["display_name"])

    def test_instantane_absent_rend_une_liste_vide(self):
        """Pas d'exception : l'appelant doit pouvoir le DIRE a
        l'utilisateur plutot que de planter."""
        self.assertEqual(charger_instantane("/introuvable/nulle/part.csv.gz"), [])

    def test_l_instantane_du_depot_est_la_et_complet(self):
        """Il existe pour que l'application marche en local SANS reseau.
        S'il disparaissait du depot, le catalogue serait vide hors ligne et
        personne ne s'en apercevrait avant d'etre hors ligne."""
        lignes = charger_instantane()
        self.assertGreater(len(lignes), 3000,
                           "instantane du depot absent ou tronque")
        colonnes = set(lignes[0])
        for attendue in ("card_code", "display_name", "series_name", "rarity"):
            self.assertIn(attendue, colonnes)


class TestChargement(BaseDeTest):
    def test_les_cartes_entrent_sans_prix_et_c_est_dit(self):
        rapport = charger_catalogue(self.db)
        self.assertEqual(rapport["rejetees"], 0, rapport.get("rejets"))
        self.assertGreater(rapport["creees"], 3000)
        # Le compte des cartes sans prix doit etre rendu : sans lui, « 3868
        # importees » se lirait comme un catalogue complet.
        self.assertEqual(rapport["sans_prix"], rapport["importees"])
        self.assertIn("ne publie pas de prix", rapport["prix"])

        en_base = self.cartes()
        self.assertTrue(all(c.price_eur is None for c in en_base))

    def test_l_instantane_manquant_est_dit_pas_tu(self):
        original = opcg_dataset.CHEMIN_INSTANTANE
        opcg_dataset.CHEMIN_INSTANTANE = "/introuvable/nulle/part.csv.gz"
        try:
            rapport = charger_catalogue(self.db)
        finally:
            opcg_dataset.CHEMIN_INSTANTANE = original
        self.assertIn("erreur", rapport)
        self.assertEqual(self.cartes(), [])

    def test_le_repli_reseau_est_dit(self):
        """Un rafraichissement qui echoue doit se rabattre sur l'instantane
        EN LE DISANT. Un repli silencieux ferait croire que les donnees
        servies viennent d'etre rafraichies."""
        class RegistreEnPanne:
            def get(self, *a, **k):
                raise OSError("reseau coupe")

        rapport = charger_catalogue(self.db, rafraichir=True,
                                    session=RegistreEnPanne())
        self.assertIn("avertissement", rapport)
        self.assertIn("reseau coupe", rapport["avertissement"])
        self.assertGreater(rapport["creees"], 3000)


class TestThemesDerives(unittest.TestCase):
    def test_la_parallele_rejoint_le_theme_alternative(self):
        """C'est ce qui la rend trouvable dans l'explorateur. Le theme se
        deduit du nom, sans table de correspondance a tenir a jour."""
        self.assertIn("alternative",
                      themes_de_la_carte("Roronoa Zoro (Parallèle)", "L (Leader)"))

    def test_l_ordinaire_n_y_est_pas(self):
        self.assertNotIn("alternative",
                         themes_de_la_carte("Roronoa Zoro", "L (Leader)"))

    def test_la_rarete_de_la_source_declenche_bien_les_themes(self):
        """Le format « SR (Super Rare) » doit satisfaire les motifs, sinon
        les themes de rarete resteraient vides sur tout le catalogue."""
        self.assertIn("secret-rare", themes_de_la_carte("Nami", "SEC (Secret Rare)"))
        self.assertIn("super-rare", themes_de_la_carte("Kaido", "SR (Super Rare)"))
        self.assertIn("leader", themes_de_la_carte("Kaido", "L (Leader)"))
        self.assertIn("promo", themes_de_la_carte("Shanks", "P (Promo)"))


class TestVarianteDepartagee(BaseDeTest):
    """Le coeur du risque : un code designe deux cartes aux prix sans
    rapport. On met des prix tres differents pour que l'erreur se voie."""

    def setUp(self):
        super().setUp()
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro",
             "rarity": "L (Leader)", "price_eur": "4,00"},
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro (Parallèle)",
             "rarity": "L (Leader)", "price_eur": "180,00"},
        ])

    def match(self, titre):
        return find_price_for_listing(self.db, titre, "")

    def test_parallele_annoncee_retient_la_parallele(self):
        m = self.match("Roronoa Zoro parallèle OP01-001 française")
        self.assertEqual(m.row.price_eur, 180.0)
        self.assertEqual(m.confidence, "high")

    def test_alt_art_est_la_meme_chose_que_parallele(self):
        """Le vendeur ecrit « alt art », le catalogue dit « Parallele »."""
        for mot in ("alt art", "alternative", "alt"):
            m = self.match(f"Roronoa Zoro OP01-001 {mot}")
            self.assertEqual(m.row.price_eur, 180.0, f"echec sur « {mot} »")

    def test_sans_variante_annoncee_c_est_l_ordinaire(self):
        """Le cas le plus courant, et celui qui coutait le plus cher : un
        titre qui ne dit rien designe l'impression ordinaire."""
        m = self.match("Carte One Piece Roronoa Zoro OP01-001 FR")
        self.assertEqual(m.row.price_eur, 4.0)

    def test_leader_est_confirme_par_la_rarete_sans_fausse_alerte(self):
        """« Leader » est un TYPE de carte, pas une variante d'impression :
        OP01-001 est bien un Leader, sa rarete le dit. Signaler un doute ici
        marquerait presque toutes les annonces de Leaders comme douteuses, et
        une alerte qui se declenche toujours ne s'ecoute plus."""
        m = self.match("Carte One Piece Roronoa Zoro OP01-001 Leader FR")
        self.assertIsNone(m.warning)
        self.assertEqual(m.confidence, "high")

    def test_variante_introuvable_sur_un_code_ambigu_est_signalee(self):
        m = self.match("Roronoa Zoro OP01-001 manga rare")
        self.assertEqual(m.confidence, "low")
        self.assertIsNotNone(m.warning)

    def test_code_sans_ambiguite_n_est_pas_signale(self):
        """Quand le code ne designe qu'une fiche, il EST l'identification :
        avertir sans pouvoir proposer d'alternative n'apprend rien."""
        importer_catalogue(self.db, [
            {"card_code": "ST01-001", "display_name": "Monkey.D.Luffy",
             "price_eur": "2,40"},
        ])
        m = self.match("Monkey D Luffy ST01-001 secret rare")
        self.assertEqual(m.confidence, "high")
        self.assertIsNone(m.warning)


class TestPrixInconnuNeMentPas(BaseDeTest):
    def test_un_import_sans_prix_n_efface_pas_un_prix_connu(self):
        """LE piege. Importer la liste officielle par-dessus un catalogue
        deja chiffre effacerait tous les prix de reference d'un coup — et
        avec eux toutes les marges et tous les scores."""
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro",
             "price_eur": "42,00"},
        ])
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro",
             "series_name": "Romance Dawn (OP-01)", "price_eur": ""},
        ])
        carte = self.cartes()[0]
        self.assertEqual(carte.price_eur, 42.0)
        # Le reste de la fiche a bien ete mis a jour, lui.
        self.assertEqual(carte.series_name, "Romance Dawn (OP-01)")

    def test_un_prix_illisible_reste_un_rejet(self):
        """Absence et erreur de saisie ne sont pas la meme chose. Avaler un
        « 12,5O € » (avec la lettre O) comme une absence ferait disparaitre
        l'erreur sans que personne l'apprenne."""
        rapport = importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro", "price_eur": "12,5O €"},
        ])
        self.assertEqual(rapport["rejetees"], 1)
        self.assertIn("illisible", rapport["rejets"][0]["raison"])

    def test_un_prix_absent_est_accepte_et_compte(self):
        rapport = importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Zoro", "price_eur": ""},
        ])
        self.assertEqual(rapport["rejetees"], 0)
        self.assertEqual(rapport["sans_prix"], 1)
        self.assertIsNone(self.cartes()[0].price_eur)

    def test_la_mediane_ne_plante_pas_quand_aucun_prix_n_est_connu(self):
        """Toutes les cartes de la liste officielle arrivent sans prix :
        c'est le cas NORMAL au premier chargement, pas un cas limite."""
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro", "price_eur": ""},
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro (Parallèle)",
             "price_eur": ""},
        ])
        m = find_price_for_listing(self.db, "Roronoa Zoro OP01-001", "")
        self.assertIsNotNone(m, "la carte doit rester IDENTIFIABLE sans prix")
        self.assertIsNone(m.row.price_eur)

    def test_une_carte_sans_prix_reste_identifiee(self):
        """Identification et valorisation sont deux choses. Sans prix on
        connait quand meme la carte, donc son visuel et sa fiche."""
        importer_catalogue(self.db, [
            {"card_code": "OP05-118", "display_name": "Kaido", "price_eur": ""},
        ])
        m = find_price_for_listing(self.db, "Kaido OP05-118 carte one piece FR", "")
        self.assertIsNotNone(m)
        self.assertEqual(m.row.card_code, "OP05-118")
        self.assertIsNotNone(m.to_dict().get("matched_card_id"))


if __name__ == "__main__":
    unittest.main()
