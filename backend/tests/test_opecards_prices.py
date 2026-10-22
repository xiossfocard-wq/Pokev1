"""
Tests des prix de référence (collectors/opecards_prices.py) et de leur
application au catalogue (services/catalog_prices.py).

Ces tests tournent contre un EXTRAIT REEL d'OPECards.fr, relevé le
22/10/2026 et conservé dans fixtures/opecards_op15_prix.html.

Ce qui est vérifié ici tient en une phrase : qu'un prix atterrisse sur LA
BONNE carte. C'est la seule chose qui compte, parce qu'une erreur de
rapprochement ne se voit pas — elle produit un chiffre plausible, une marge
plausible, et une « bonne affaire » qui n'existe pas.

LE CAS QUI A CHANGE LE MODELE
-----------------------------
Trois entrées portent le code OP15-118-SEC :

    Ener                10,50 €
    Ener (Version 2)    22,00 €
    Ener (Version 3)   695,00 €

Le catalogue regroupait jusque-là toutes les illustrations alternatives
d'un code sous une seule fiche. Il aurait annoncé 22 € pour une carte qui
en vaut 695.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.collectors.cardlist_fr import CarteFR
from app.collectors.opecards_prices import (
    ClientOPECards, analyser_page, derniere_page, rang_de_version,
    separer_code_et_rarete, series_francaises,
)
from app.database import Base
from app.models import MarketCardPrice
from app.services.catalog_fr import appliquer_noms_francais
from app.services.catalog_prices import appliquer_prix

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "opecards_op15_prix.html")


def page() -> str:
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


def carte_fr(code, nom, rang=0, rarete="SEC"):
    return CarteFR(code, nom, rarete, "PERSONNAGE", "Aventure (OP-15)", None, rang)


class TestSeparationCodeRarete(unittest.TestCase):
    """Le site colle le code et la rarete dans un seul libelle."""

    def test_rarete_detachee(self):
        self.assertEqual(separer_code_et_rarete("OP15-118-SEC"), ("OP15-118", "SEC"))
        self.assertEqual(separer_code_et_rarete("OP15-086-SR"), ("OP15-086", "SR"))

    def test_rarete_d_une_seule_lettre(self):
        """« -R » ne doit pas etre confondu avec la fin du numero."""
        self.assertEqual(separer_code_et_rarete("OP15-116-R"), ("OP15-116", "R"))
        self.assertEqual(separer_code_et_rarete("OP15-022-L"), ("OP15-022", "L"))

    def test_rarete_avec_ponctuation(self):
        self.assertEqual(separer_code_et_rarete("ST01-001-DON!!"),
                         ("ST01-001", "DON!!"))

    def test_sans_rarete_le_code_passe_entier(self):
        """Couper au dernier tiret donnerait « OP15 » / « 118 »."""
        self.assertEqual(separer_code_et_rarete("OP15-118"), ("OP15-118", None))

    def test_vide(self):
        self.assertEqual(separer_code_et_rarete(""), (None, None))


class TestRangDeVersion(unittest.TestCase):
    def test_la_version_2_est_la_premiere_alternative(self):
        """La numerotation rendue est celle des ALTERNATIVES, pour
        correspondre aux suffixes « _p1 », « _p2 » de la liste officielle."""
        self.assertEqual(rang_de_version("Ener (Version 2)"), ("Ener", 1))
        self.assertEqual(rang_de_version("Ener (Version 3)"), ("Ener", 2))

    def test_sans_version_c_est_l_ordinaire(self):
        self.assertEqual(rang_de_version("Ener"), ("Ener", 0))

    def test_une_parenthese_qui_n_est_pas_une_version_reste_dans_le_nom(self):
        nom, rang = rang_de_version("Capone \"Gang\" Bege")
        self.assertEqual(rang, 0)
        self.assertIn("Gang", nom)


class TestAnalysePage(unittest.TestCase):
    def setUp(self):
        self.cartes = analyser_page(page())
        self.par_cle = {(c.card_code, c.rang_variante): c for c in self.cartes}

    def test_les_trois_versions_ont_des_prix_distincts(self):
        """LE cas qui justifie tout le reste : 66 fois l'ecart."""
        self.assertEqual(self.par_cle[("OP15-118", 0)].price_eur, 10.50)
        self.assertEqual(self.par_cle[("OP15-118", 1)].price_eur, 22.00)
        self.assertEqual(self.par_cle[("OP15-118", 2)].price_eur, 695.00)

    def test_le_nom_ne_garde_pas_la_mention_de_version(self):
        """Le rang est une donnee a part, pas un bout de chaine."""
        for rang in (0, 1, 2):
            self.assertEqual(self.par_cle[("OP15-118", rang)].display_name, "Ener")

    def test_une_baisse_est_negative(self):
        """Le signe vient de la CLASSE CSS (text-success = baisse) et non du
        texte : la classe ne depend pas du formatage du gabarit."""
        self.assertEqual(self.par_cle[("OP15-086", 1)].variation_eur, -3.00)

    def test_une_hausse_est_positive(self):
        self.assertEqual(self.par_cle[("OP15-113", 1)].variation_eur, 0.10)

    def test_pas_de_variation_quand_il_n_y_en_a_pas(self):
        self.assertIsNone(self.par_cle[("OP15-118", 0)].variation_eur)

    def test_rarete_recuperee(self):
        self.assertEqual(self.par_cle[("OP15-118", 0)].rarity, "SEC")
        self.assertEqual(self.par_cle[("OP15-116", 1)].rarity, "R")

    def test_accents_du_nom_intacts(self):
        self.assertEqual(self.par_cle[("OP15-116", 1)].display_name,
                         "Gum Gum Carabine Dorée")

    def test_image_et_lien(self):
        carte = self.par_cle[("OP15-118", 2)]
        self.assertTrue(carte.image_url.startswith("https://static.opecards.fr/"))
        self.assertTrue(carte.detail_url.endswith("/cards/op15-118-sec-version-3-ener"))

    def test_page_vide_ne_plante_pas(self):
        self.assertEqual(analyser_page("<html><body></body></html>"), [])


class TestSeriesEtPagination(unittest.TestCase):
    def test_seul_le_groupe_francais_est_retenu(self):
        """Le menu liste aussi les series japonaises et anglaises. Les
        prendre inscrirait au catalogue des cartes jamais imprimees en
        francais."""
        series = series_francaises(page())
        libelles = " | ".join(series.values())
        self.assertIn("OP15", libelles)
        self.assertNotIn("Romance Dawn", libelles)   # OP01, anglais et japonais
        self.assertNotIn("Two Legends", libelles)    # OP08, anglais seul

    def test_le_jeu_francais_commence_a_op09(self):
        """Constat, pas supposition : le groupe francais ne contient ni OP01
        ni OP08. Le catalogue ne doit donc pas promettre ces series."""
        libelles = " ".join(series_francaises(page()).values())
        self.assertIn("OP09", libelles)
        self.assertNotIn("OP01 ", libelles)

    def test_derniere_page(self):
        self.assertEqual(derniere_page(page()), 7)

    def test_une_page_sans_pagination_vaut_une_page(self):
        self.assertEqual(derniere_page("<html></html>"), 1)


class TestConstructionDesUrl(unittest.TestCase):
    def setUp(self):
        self.client = ClientOPECards()

    def test_premiere_page_sans_numero(self):
        self.assertIn("/cards?", self.client.url(page=1, serie="770"))

    def test_pages_suivantes_numerotees(self):
        self.assertIn("/cards/3?", self.client.url(page=3, serie="770"))

    def test_langue_et_serie_transmises(self):
        url = self.client.url(page=1, serie="770")
        self.assertIn("serie=770", url)
        self.assertIn("language=FR", url)


class TestApplicationDesPrix(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=moteur)
        self.db = sessionmaker(bind=moteur)()
        # Le catalogue officiel : trois impressions distinctes du meme code.
        appliquer_noms_francais(self.db, [
            carte_fr("OP15-118", "Ener", 0),
            carte_fr("OP15-118", "Ener (Parallèle 1)", 1),
            carte_fr("OP15-118", "Ener (Parallèle 2)", 2),
            carte_fr("OP15-086", "Nami (Parallèle 1)", 1, "SR"),
        ])

    def tearDown(self):
        self.db.close()

    def fiche(self, code, rang=0):
        from app.collectors.cardlist_fr import rang_de_parallele
        for l in self.db.query(MarketCardPrice).filter_by(card_code=code).all():
            if rang_de_parallele(l.name_slug) == rang:
                return l
        return None

    def appliquer(self):
        return appliquer_prix(self.db, analyser_page(page()))

    def test_chaque_version_recoit_SON_prix(self):
        """Le test qui compte. Si le rapprochement se trompe de variante, la
        carte a 695 € s'affiche a 22 € — et l'erreur ne se voit pas, puisque
        22 € est un prix parfaitement plausible."""
        self.appliquer()
        self.assertEqual(self.fiche("OP15-118", 0).price_eur, 10.50)
        self.assertEqual(self.fiche("OP15-118", 1).price_eur, 22.00)
        self.assertEqual(self.fiche("OP15-118", 2).price_eur, 695.00)

    def test_la_variation_est_enregistree(self):
        self.appliquer()
        self.assertEqual(self.fiche("OP15-086", 1).variation_7d_eur, -3.00)

    def test_une_carte_absente_du_catalogue_n_est_pas_creee(self):
        """Cette source dit ce que valent les cartes, pas lesquelles
        existent. Creer ici donnerait une fiche sans serie ni visuel."""
        rapport = self.appliquer()
        self.assertGreater(rapport["sans_fiche"], 0)
        self.assertIsNone(self.fiche("OP15-113", 1))

    def test_le_reste_de_la_fiche_n_est_pas_touche(self):
        """Seuls le prix et sa variation sont ecrits ici."""
        avant = self.fiche("OP15-118", 2)
        nom, serie = avant.display_name, avant.series_name
        self.appliquer()
        apres = self.fiche("OP15-118", 2)
        self.assertEqual(apres.display_name, nom)
        self.assertEqual(apres.series_name, serie)

    def test_un_ecart_enorme_est_signale_pas_tu(self):
        """Un prix qui est multiplie par soixante est peut-etre reel — ces
        cartes bougent vite — mais c'est aussi la signature d'un
        rapprochement qui a derape. Une marge fausse ne se voit pas."""
        self.fiche("OP15-118", 2).price_eur = 10.0
        self.db.commit()
        rapport = self.appliquer()
        codes = {e["code"] for e in rapport["ecarts_suspects"]}
        self.assertIn("OP15-118", codes)

    def test_un_ecart_normal_n_est_pas_signale(self):
        self.fiche("OP15-118", 2).price_eur = 680.0
        self.db.commit()
        rapport = self.appliquer()
        self.assertEqual(rapport["ecarts_suspects"], [])

    def test_le_compte_des_cartes_encore_sans_prix_est_rendu(self):
        """« 4 chiffrees » ne dit pas si le catalogue est couvert."""
        rapport = self.appliquer()
        self.assertEqual(rapport["sans_prix_restantes"], 0)

    def test_relancer_ne_change_plus_rien(self):
        self.appliquer()
        second = self.appliquer()
        self.assertEqual(second["chiffrees"], 0)
        self.assertGreater(second["inchangees"], 0)

    def test_les_changements_sont_montres(self):
        rapport = self.appliquer()
        self.assertTrue(any(e["apres"] == 695.00 for e in rapport["exemples"]))


if __name__ == "__main__":
    unittest.main()


class TestSeriesFrancaisesConnues(unittest.TestCase):
    class SessionEnPanne:
        def __init__(self):
            self.headers = {}

        def get(self, *a, **k):
            raise OSError("reseau coupe")

    def test_le_repli_rend_la_liste_gravee(self):
        from app.collectors.opecards_prices import SERIES_FR_CONNUES
        series = ClientOPECards(session=self.SessionEnPanne()).series()
        self.assertEqual(series, dict(SERIES_FR_CONNUES))

    def test_aucune_serie_japonaise_ou_anglaise_gravee(self):
        """Les prendre inscrirait au catalogue des prix de cartes jamais
        imprimees en francais."""
        from app.collectors.opecards_prices import SERIES_FR_CONNUES
        libelles = " | ".join(SERIES_FR_CONNUES.values())
        self.assertNotIn("Romance Dawn", libelles)
        self.assertNotIn("Two Legends", libelles)
        self.assertNotIn("Starter Deck", libelles)

    def test_les_deux_sources_couvrent_les_memes_series(self):
        """Une serie chiffree sans fiche, ou une fiche jamais chiffree,
        viendrait d'un desaccord entre les deux listes."""
        import re
        from app.collectors.cardlist_fr import SERIES_CONNUES
        from app.collectors.opecards_prices import SERIES_FR_CONNUES

        def code_principal(libelle):
            """Le PREMIER code du libelle.

            Le site officiel libelle certains produits groupes
            « [OP15-EB04] » : c'est un seul produit, pas deux series. Lire
            les deux codes ferait croire a une serie EB04 separee, absente
            d'OPECards — un faux ecart.
            """
            trouve = re.search(r"\b((?:OP|ST|EB|PRB)-?\d{2})\b", libelle)
            return trouve.group(1).replace("-", "") if trouve else None

        officielles = {c for c in map(code_principal, SERIES_CONNUES.values()) if c}
        prix = {c for c in map(code_principal, SERIES_FR_CONNUES.values()) if c}

        manquantes = officielles - prix
        self.assertEqual(manquantes, set(),
                         f"series sans source de prix : {sorted(manquantes)}")
