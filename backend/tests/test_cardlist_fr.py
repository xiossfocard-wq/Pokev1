"""
Tests de la liste officielle FRANÇAISE (collectors/cardlist_fr.py) et du
passage du catalogue aux noms français (services/catalog_fr.py).

Ces tests tournent contre un EXTRAIT REEL du site, releve le 22/10/2026 et
conserve dans fixtures/cardlist_fr_op17.html — pas contre une page
reconstituee de memoire. C'est une precaution apprise a ses depens : la
premiere source du projet avait ete parsee a l'aveugle, et ne couvrait
meme pas One Piece.

Ce qui est verifie ici tient en une phrase : que les noms FRANCAIS arrivent
bien jusqu'au catalogue, sans dupliquer les fiches ni effacer les prix.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors import card_images
from app.collectors.cardlist_fr import (
    MARQUE_ALTERNATIVE, analyser_page, nom_avec_variante, nombre_annonce,
    rang_de_parallele, series_disponibles, _nettoyer_serie, _texte,
)
from app.database import Base
from app.models import MarketCardPrice
from app.services.catalog_fr import appliquer_noms_francais
from app.services.catalog_import import importer_catalogue

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "cardlist_fr_op17.html")


def page() -> str:
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


class TestNettoyageTexte(unittest.TestCase):
    def test_entites_decodees(self):
        """Les noms en portent vraiment : « J&#039;ai », « &quot;Gang&quot; »."""
        self.assertEqual(_texte("J&#039;ai envie"), "J'ai envie")
        self.assertEqual(_texte("Capone &quot;Gang&quot; Bege"),
                         'Capone "Gang" Bege')

    def test_balise_echappee_retiree(self):
        """LE piege de l'ordre des operations. Les libelles de series
        contiennent « &lt;br class=&quot;spInline&quot;&gt; » : retirer les
        balises AVANT de decoder laisse passer la balise, qui n'apparait
        qu'au decodage."""
        brut = "BOOSTER &lt;br class=&quot;spInline&quot;&gt;-SANG ROYAL- [OP-10]"
        self.assertNotIn("<br", _texte(brut))
        self.assertNotIn("spInline", _texte(brut))

    def test_double_encodage(self):
        """Certains libelles sont encodes deux fois."""
        self.assertEqual(_texte("L&amp;apos;HÉRITAGE"), "L'HÉRITAGE")


class TestNettoyageSerie(unittest.TestCase):
    def test_prefixe_produit_retire_et_code_garde(self):
        self.assertEqual(_nettoyer_serie("BOOSTER -SANG ROYAL- [OP-10]"),
                         "Sang Royal (OP-10)")

    def test_liaisons_francaises_en_minuscules(self):
        self.assertEqual(
            _nettoyer_serie("BOOSTER -LES GUERRIERS LES PLUS PUISSANTS AU MONDE- [OP-17]"),
            "Les Guerriers les plus Puissants au Monde (OP-17)")

    def test_serie_sans_code(self):
        self.assertEqual(_nettoyer_serie("Carte promo"), "Carte promo")

    def test_serie_vide(self):
        for vide in (None, "", "-", "   "):
            self.assertIsNone(_nettoyer_serie(vide))


class TestAnalysePage(unittest.TestCase):
    def setUp(self):
        self.cartes = analyser_page(page())
        self.par_code = {}
        for c in self.cartes:
            self.par_code.setdefault(c.card_code, []).append(c)

    def test_les_noms_sont_en_francais(self):
        """La raison d'etre de ce module. « Hive » s'appelle « Ruche », et
        « Buggy » s'appelle « Baggy » : un vendeur francais qui ecrit
        « Baggy » ne rencontrait jamais la fiche anglaise."""
        noms = {c.display_name for c in self.cartes}
        self.assertIn("Ruche", noms)
        self.assertIn(nom_avec_variante("Baggy", 1), noms)
        self.assertIn("Caborage et Chavipère", noms)

    def test_apostrophes_et_guillemets_intacts(self):
        noms = {c.display_name for c in self.cartes}
        self.assertIn('Capone "Gang" Bege', noms)
        self.assertTrue(any(n.startswith("J'ai aucune envie") for n in noms))

    def test_la_variante_est_dans_l_id_pas_dans_le_code(self):
        """Le <span> du code est IDENTIQUE pour toutes les variantes ; seul
        l'id du bloc les distingue (« OP17-001 » / « OP17-001_p1 »). Un
        parseur qui ne lirait que le code les confondrait."""
        variantes = self.par_code["OP17-001"]
        self.assertEqual(len(variantes), 2)
        self.assertEqual({v.rang_variante for v in variantes}, {0, 1})
        self.assertEqual({v.card_code for v in variantes}, {"OP17-001"})

    def test_le_rang_de_la_parallele_est_dans_le_nom(self):
        """Le RANG, pas seulement la mention. Releve le 22/10/2026 sur
        OPECards : les trois impressions de OP15-118-SEC valent 10,50 €,
        22,00 € et 695,00 €. Les regrouper sous un seul « (Parallèle) »,
        c'etait accepter de se tromper d'un facteur soixante-six."""
        alt = next(c for c in self.cartes if c.rang_variante == 1
                   and c.card_code == "OP17-001")
        self.assertEqual(alt.display_name, "Edward Newgate (Parallèle 1)")
        autre = next(c for c in self.cartes if c.card_code == "OP17-005")
        self.assertEqual(autre.display_name, "Edward Newgate (Parallèle 2)")

    def test_images_en_webp_et_absolues(self):
        """Le site FR sert du WEBP. Tant que le code attendait du PNG,
        CHAQUE visuel echouait — en silence, un 404 se lisant comme
        « cette carte n'a pas d'image »."""
        for carte in self.cartes:
            self.assertIsNotNone(carte.image_url, carte.card_code)
            self.assertTrue(carte.image_url.endswith(".webp"), carte.image_url)
            self.assertTrue(carte.image_url.startswith("https://"), carte.image_url)

    def test_le_cache_buster_est_retire(self):
        for carte in self.cartes:
            self.assertNotIn("?", carte.image_url)

    def test_raretes_et_types(self):
        leader = next(c for c in self.cartes if c.rang_variante == 0
                      and c.card_code == "OP17-001")
        self.assertEqual(leader.rarity, "L")
        self.assertEqual(leader.card_type, "LEADER")
        lieu = next(c for c in self.cartes if c.card_code == "OP17-057")
        self.assertEqual(lieu.card_type, "LIEU")

    def test_serie_rattachee_a_chaque_carte(self):
        for carte in self.cartes:
            self.assertEqual(carte.series_name,
                             "Les Guerriers les plus Puissants au Monde (OP-17)")

    def test_reimpressions_d_autres_series_presentes(self):
        """Une page de serie contient aussi des reimpressions venues
        d'ailleurs (EB04, P-084). Les ecarter perdrait des cartes reelles."""
        codes = {c.card_code for c in self.cartes}
        self.assertIn("EB04-061", codes)
        self.assertIn("P-084", codes)

    def test_page_vide_ne_plante_pas(self):
        self.assertEqual(analyser_page("<html><body></body></html>"), [])


class TestSeriesEtCompte(unittest.TestCase):
    def test_menu_deroulant_lu(self):
        series = series_disponibles(page())
        self.assertEqual(series.get("622117"),
                         "Les Guerriers les plus Puissants au Monde (OP-17)")
        self.assertEqual(series.get("622901"), "Carte promo")

    def test_aucun_residu_de_balise_dans_les_libelles(self):
        for libelle in series_disponibles(page()).values():
            self.assertNotIn("<", libelle)
            self.assertNotIn("&", libelle)

    def test_compte_annonce_par_la_page(self):
        """Sert de controle : extraire bien moins que le compte annonce
        signale que le parseur a rate quelque chose."""
        self.assertEqual(nombre_annonce(page()), 169)


class TestExtensionImage(unittest.TestCase):
    def test_le_webp_est_essaye_en_premier(self):
        urls = card_images.urls_candidates("OP17-001")
        self.assertTrue(urls[0].endswith(".webp"), urls[0])

    def test_le_png_reste_un_repli(self):
        urls = card_images.urls_candidates("OP17-001")
        self.assertTrue(any(u.endswith(".png") for u in urls))


class TestApplicationDesNomsFrancais(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()
        # Le catalogue tel qu'il est AVANT : des noms anglais, et des prix
        # de reference qu'il ne faut surtout pas perdre.
        importer_catalogue(self.db, [
            {"card_code": "OP17-057", "display_name": "Hive", "price_eur": "0,80"},
            {"card_code": "P-084", "display_name": "Buggy (Parallèle 1)",
             "price_eur": "120,00"},
            {"card_code": "OP17-001", "display_name": "Edward Newgate",
             "price_eur": "9,00"},
        ])

    def tearDown(self):
        self.db.close()

    def appliquer(self):
        return appliquer_noms_francais(self.db, analyser_page(page()))

    def fiche(self, code, rang=0):
        for l in self.db.query(MarketCardPrice).filter_by(card_code=code).all():
            if rang_de_parallele(l.name_slug) == rang:
                return l
        return None

    def test_la_fiche_est_renommee_pas_dupliquee(self):
        """LE piege. Le catalogue est indexe sur (code, slug du nom) : passer
        par l'import creerait une seconde fiche « Baggy » a cote de
        « Buggy », pour la meme carte."""
        self.appliquer()
        fiches = self.db.query(MarketCardPrice).filter_by(card_code="P-084").all()
        self.assertEqual(len(fiches), 1)
        self.assertEqual(fiches[0].display_name, nom_avec_variante("Baggy", 1))

    def test_le_prix_de_reference_survit_au_renommage(self):
        """Cette source dit comment la carte s'appelle, pas ce qu'elle vaut."""
        self.appliquer()
        self.assertEqual(self.fiche("OP17-057").price_eur, 0.80)
        self.assertEqual(self.fiche("P-084", rang=1).price_eur, 120.0)

    def test_le_slug_suit_le_nouveau_nom(self):
        """Sans cela le rapprochement par nom chercherait encore l'anglais."""
        self.appliquer()
        self.assertEqual(self.fiche("OP17-057").name_slug, "ruche")

    def test_les_renommages_sont_rendus_visibles(self):
        """« 412 renommees » ne veut rien dire tant qu'on n'a pas vu que
        « Buggy » est devenu « Baggy »."""
        rapport = self.appliquer()
        avant_apres = {(e["avant"], e["apres"]) for e in rapport["exemples"]}
        self.assertIn(("Hive", "Ruche"), avant_apres)
        self.assertGreaterEqual(rapport["renommees"], 2)

    def test_les_cartes_inconnues_sont_creees(self):
        rapport = self.appliquer()
        self.assertGreater(rapport["creees"], 0)
        self.assertIsNotNone(self.fiche("OP17-004"))

    def test_le_visuel_observe_est_enregistre(self):
        """Une adresse lue sur la page vaut mieux qu'une adresse deduite, et
        elle evite un aller-retour reseau par carte."""
        self.appliquer()
        fiche = self.fiche("OP17-057")
        self.assertTrue((fiche.image_url or "").endswith("OP17-057.webp"),
                        fiche.image_url)

    def test_une_carte_absente_de_la_page_reste_intacte(self):
        """Le renommage ne touche que ce que la page contient : une carte
        qu'elle ne mentionne pas garde son nom et son prix."""
        importer_catalogue(self.db, [
            {"card_code": "OP01-001", "display_name": "Roronoa Zoro",
             "price_eur": "4,00"},
        ])
        self.appliquer()
        intacte = self.fiche("OP01-001")
        self.assertEqual(intacte.display_name, "Roronoa Zoro")
        self.assertEqual(intacte.price_eur, 4.0)

    def test_relancer_ne_change_plus_rien(self):
        """L'operation doit etre idempotente : la relancer ne doit ni
        dupliquer ni re-signaler des renommages qui ont deja eu lieu."""
        self.appliquer()
        total = self.db.query(MarketCardPrice).count()
        second = self.appliquer()
        self.assertEqual(self.db.query(MarketCardPrice).count(), total)
        self.assertEqual(second["renommees"], 0)
        self.assertEqual(second["creees"], 0)

    def test_les_themes_suivent_le_nom_francais(self):
        self.appliquer()
        parallele = self.fiche("P-084", rang=1)
        self.assertIn("alternative", parallele.theme_slugs or "")


if __name__ == "__main__":
    unittest.main()


class TestSeriesConnues(unittest.TestCase):
    """Le menu deroulant du site est la source de verite, mais une seule
    requete en echec ne doit pas emporter tout le chargement : l'utilisateur
    se retrouverait avec un catalogue anglais sans comprendre pourquoi."""

    class SessionEnPanne:
        def __init__(self):
            self.headers = {}

        def get(self, *a, **k):
            raise OSError("reseau coupe")

    def test_le_repli_rend_la_liste_gravee(self):
        from app.collectors.cardlist_fr import ClientListeFR, SERIES_CONNUES
        series = ClientListeFR(session=self.SessionEnPanne()).series()
        self.assertEqual(series, dict(SERIES_CONNUES))

    def test_la_liste_gravee_couvre_op09_a_op17(self):
        """Constat, pas supposition : le menu du site ne propose ni OP01 ni
        OP08. Le jeu francais commence a OP09."""
        from app.collectors.cardlist_fr import SERIES_CONNUES
        libelles = " | ".join(SERIES_CONNUES.values())
        for serie in ("OP-09", "OP-13", "OP-17"):
            self.assertIn(serie, libelles)
        for absente in ("OP-01", "OP-08"):
            self.assertNotIn(absente, libelles)

    def test_la_liste_gravee_contient_les_decks_et_les_promos(self):
        from app.collectors.cardlist_fr import SERIES_CONNUES
        libelles = " | ".join(SERIES_CONNUES.values())
        self.assertIn("ST-15", libelles)
        self.assertIn("ST-36", libelles)
        self.assertIn("promo", libelles.lower())
