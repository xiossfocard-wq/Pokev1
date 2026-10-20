"""
Tests de l'import de catalogue (services/catalog_import.py).

Pourquoi cette piece existe : le catalogue n'avait qu'UNE facon d'etre
rempli, et quand cette source s'est revelee ne pas couvrir One Piece il
n'est rien reste. Ce chemin-ci ne depend ni du reseau ni de la forme d'une
page.

Ce qui est verifie ici, surtout : que rien ne disparait en silence. Un
import qui avalerait la moitie d'un fichier sans le dire reproduirait
exactement le silence qui a laisse croire que le catalogue se remplissait
alors qu'il restait vide.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MarketCardPrice
from app.services import catalog_import
from app.services.catalog_import import analyser, importer_catalogue


class BaseDeTest(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()

    def tearDown(self):
        self.db.close()

    def importer(self, contenu):
        lignes, erreur = analyser(contenu)
        self.assertIsNone(erreur, erreur)
        return importer_catalogue(self.db, lignes)

    def cartes(self):
        return self.db.query(MarketCardPrice).all()


class TestPrixFrancais(unittest.TestCase):
    """La virgule decimale est le cas NORMAL : la source de prix visee est
    une boutique francaise."""

    def test_formats_acceptes(self):
        for brut, attendu in [
            ("12,50 €", 12.50),
            ("12.50", 12.50),
            ("€ 7,00", 7.00),
            ("1 234,56 €", 1234.56),
            ("1 234,56", 1234.56),      # espace insecable
            ("1.234,56", 1234.56),           # milliers a l'europeenne
            ("1,234.56", 1234.56),           # milliers a l'anglaise
            ("0,99", 0.99),
            (12.5, 12.5),
            (12, 12.0),
        ]:
            with self.subTest(brut=brut):
                self.assertAlmostEqual(catalog_import._nettoyer_prix(brut), attendu, places=2)

    def test_prix_illisibles(self):
        for brut in (None, "", "   ", "sur demande", "€", "-5,00"):
            with self.subTest(brut=brut):
                self.assertIsNone(catalog_import._nettoyer_prix(brut))


class TestLecture(unittest.TestCase):
    def test_csv_point_virgule(self):
        lignes, erreur = analyser("card_code;display_name;price_eur\nOP01-120;Luffy;412,00")
        self.assertIsNone(erreur)
        self.assertEqual(len(lignes), 1)

    def test_csv_virgule(self):
        lignes, erreur = analyser("card_code,display_name,price_eur\nOP01-120,Luffy,412.00")
        self.assertIsNone(erreur)
        self.assertEqual(len(lignes), 1)

    def test_json_liste(self):
        lignes, erreur = analyser('[{"card_code":"OP01-120","display_name":"Luffy","price_eur":412}]')
        self.assertIsNone(erreur)
        self.assertEqual(len(lignes), 1)

    def test_json_enveloppe(self):
        lignes, erreur = analyser('{"cartes":[{"card_code":"OP01-120","display_name":"Luffy","price_eur":412}]}')
        self.assertIsNone(erreur)
        self.assertEqual(len(lignes), 1)

    def test_fichier_vide(self):
        self.assertEqual(analyser("")[1], "fichier vide")

    def test_json_casse_le_dit(self):
        lignes, erreur = analyser('[{"card_code": ')
        self.assertIn("JSON illisible", erreur)


class TestImport(BaseDeTest):
    def test_creation(self):
        rapport = self.importer(
            "card_code;display_name;price_eur;series_name;rarity\n"
            "OP01-120;Monkey D. Luffy;412,00;Romance Dawn;Secret Rare\n"
        )
        self.assertEqual(rapport["creees"], 1)
        self.assertEqual(rapport["rejetees"], 0)

        carte = self.cartes()[0]
        self.assertEqual(carte.card_code, "OP01-120")
        self.assertEqual(carte.display_name, "Monkey D. Luffy")
        self.assertAlmostEqual(carte.price_eur, 412.00)
        self.assertEqual(carte.series_name, "Romance Dawn")
        self.assertEqual(carte.rarity, "Secret Rare")

    def test_les_champs_derives_sont_calcules(self):
        """Themes et cle de recherche ne sont pas demandes a la source :
        sans eux le filtre par theme et la recherche libre resteraient
        vides, et personne ne saurait pourquoi."""
        self.importer("code;nom;prix\nOP01-120;Monkey D. Luffy;412,00\n")
        carte = self.cartes()[0]
        self.assertTrue(carte.theme_slugs and carte.theme_slugs != ",")
        self.assertIn("chapeau-de-paille", carte.theme_slugs)
        self.assertTrue(carte.search_key)

    def test_les_intitules_francais_sont_acceptes(self):
        """Une source exportee a la main n'utilisera pas nos intitules."""
        rapport = self.importer(
            "code;nom;prix;serie;rarete\nOP01-025;Roronoa Zoro;188,00;Romance Dawn;SR\n")
        self.assertEqual(rapport["creees"], 1)
        self.assertEqual(self.cartes()[0].display_name, "Roronoa Zoro")

    def test_le_code_est_normalise(self):
        """« OP01 4 » et « OP01-004 » designent la meme carte : sans
        normalisation, l'import en creerait deux."""
        self.importer("code;nom;prix\nOP01 4;Nami;3,40\n")
        self.assertEqual(self.cartes()[0].card_code, "OP01-004")

    def test_reimporter_met_a_jour_sans_dupliquer(self):
        self.importer("code;nom;prix\nOP01-120;Monkey D. Luffy;412,00\n")
        rapport = self.importer("code;nom;prix\nOP01-120;Monkey D. Luffy;389,00\n")

        self.assertEqual(rapport["creees"], 0)
        self.assertEqual(rapport["mises_a_jour"], 1)
        self.assertEqual(len(self.cartes()), 1)
        self.assertAlmostEqual(self.cartes()[0].price_eur, 389.00)

    def test_le_separateur_du_code_est_indifferent(self):
        self.importer("code;nom;prix\nOP01-120;Luffy;412,00\n")
        self.importer("code;nom;prix\nop01 120;Luffy;400,00\n")
        self.assertEqual(len(self.cartes()), 1, "la meme carte ne doit pas être créée deux fois")


class TestSlugCompatibleAvecLeRapprochement(BaseDeTest):
    """Le slug ecrit par l'import doit avoir EXACTEMENT la forme que le
    parseur de titre produit, sinon le rapprochement par nom complet ne se
    declenche jamais — en silence.

    Trouve en important de vraies cartes : « Monkey D. Luffy » donnait
    « monkey-d.-luffy » avec le point, la ou le parseur produit
    « monkey-d-luffy ». Le prix retombait alors sur le nom usuel, moins
    sur, sans que rien ne le signale.
    """

    def test_le_slug_est_celui_que_le_parseur_cherche(self):
        from app.matching.title_parser import extract_name_candidates
        from app.services.catalog_import import slug_de_nom

        for nom, titre in [
            ("Monkey D. Luffy", "Carte One Piece Monkey D. Luffy OP01-120"),
            ("Portgás D. Ace", "One Piece Portgas D. Ace OP02-013"),
            ("Charlotte Katakuri", "One Piece Charlotte Katakuri"),
            ("Roronoa Zoro", "One Piece Roronoa Zoro"),
        ]:
            with self.subTest(nom=nom):
                self.assertIn(slug_de_nom(nom), extract_name_candidates(titre))

    def test_la_ponctuation_et_les_accents_disparaissent(self):
        from app.services.catalog_import import slug_de_nom
        self.assertEqual(slug_de_nom("Monkey D. Luffy"), "monkey-d-luffy")
        self.assertEqual(slug_de_nom("Portgás D. Ace"), "portgas-d-ace")

    def test_une_annonce_retrouve_sa_carte_importee(self):
        """La preuve de bout en bout : importer puis rapprocher."""
        from app.services import price_index
        from app.services.price_index import find_price_for_listing

        self.importer(
            "code;nom;prix;serie\n"
            "OP01-120;Monkey D. Luffy;412,00;Romance Dawn\n"
            "OP02-013;Portgás D. Ace;88,00;Paramount War\n"
        )
        price_index._slug_cache = []
        price_index._slug_cache_at = None
        self.addCleanup(setattr, price_index, "_slug_cache", [])

        m = find_price_for_listing(self.db, "Carte One Piece Monkey D. Luffy neuve")
        self.assertIsNotNone(m, "le nom complet doit retrouver la carte importee")
        self.assertEqual(m.row.display_name, "Monkey D. Luffy")
        self.assertIn("monkey-d-luffy", m.reason)


class TestRienNeDisparaitEnSilence(BaseDeTest):
    """Le point central. Un rejet muet est ce qui a laisse croire que le
    catalogue se remplissait alors qu'il restait vide."""

    def test_chaque_rejet_porte_son_numero_et_sa_raison(self):
        rapport = self.importer(
            "code;nom;prix\n"
            "OP01-120;Monkey D. Luffy;412,00\n"   # bonne
            "PASUNCODE;Carte X;10,00\n"           # code invalide
            "OP01-025;;188,00\n"                  # nom manquant
            "OP01-016;Nami;sur demande\n"         # prix illisible
        )
        self.assertEqual(rapport["creees"], 1)
        self.assertEqual(rapport["rejetees"], 3)

        par_ligne = {r["ligne"]: r["raison"] for r in rapport["rejets"]}
        self.assertIn("code de carte", par_ligne[2])
        self.assertIn("nom de carte absent", par_ligne[3])
        self.assertIn("prix", par_ligne[4])

    def test_tous_les_rejets_sont_rendus_pas_un_echantillon(self):
        lignes = "code;nom;prix\n" + "".join(
            f"MAUVAIS{i};Carte {i};10,00\n" for i in range(40))
        rapport = self.importer(lignes)
        self.assertEqual(rapport["rejetees"], 40)
        self.assertEqual(len(rapport["rejets"]), 40)

    def test_les_comptes_s_additionnent(self):
        """lues = importees + rejetees. Sans ca, une ligne pourrait
        disparaitre sans apparaitre nulle part."""
        rapport = self.importer(
            "code;nom;prix\n"
            "OP01-120;Luffy;412,00\nOP01-025;Zoro;188,00\nMAUVAIS;X;1,00\n")
        self.assertEqual(rapport["lues"], rapport["importees"] + rapport["rejetees"])

    def test_une_ligne_refusee_n_empeche_pas_les_autres(self):
        rapport = self.importer(
            "code;nom;prix\nMAUVAIS;X;1,00\nOP01-120;Luffy;412,00\n")
        self.assertEqual(rapport["creees"], 1)
        self.assertEqual(len(self.cartes()), 1)

    def test_fichier_trop_grand_refuse_sans_rien_ecrire(self):
        trop = [{"card_code": f"OP01-{i:03d}", "display_name": f"C{i}", "price_eur": 1}
                for i in range(catalog_import.MAX_LIGNES + 1)]
        rapport = importer_catalogue(self.db, trop)
        self.assertIn("erreur", rapport)
        self.assertEqual(rapport["importees"], 0)
        self.assertEqual(len(self.cartes()), 0)


if __name__ == "__main__":
    unittest.main()
