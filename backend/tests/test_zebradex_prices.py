import sys, os, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.collectors import zebradex_prices
from app.collectors.zebradex_prices import ZebraDexClient, slugify_name

# ECHANTILLONS REELS recuperes le 04/08/2026 depuis zebradex.fr : des
# copies de la structure reellement servie, pas des reconstructions.
#
# POURQUOI ILS NE SONT PAS PORTES SUR ONE PIECE
# ---------------------------------------------
# Contrairement aux autres fixtures du projet, le nom du jeu est ici
# PORTEUR DE SENS : le parseur d'index de series lit le segment de jeu dans
# l'URL (/fr/tcg/<jeu>/<bloc>/<serie>/<id>), et c'est precisement ce
# decoupage que ces echantillons prouvent. Les reecrire en One Piece
# reviendrait a affirmer que les pages One Piece ont la meme forme — une
# page que personne n'a vue depuis cet environnement, ou le reseau sortant
# vers zebradex.fr est refuse. Le test ne prouverait plus rien, il
# supposerait.
#
# Les tests ci-dessous pointent donc explicitement le collecteur sur le jeu
# de l'echantillon, le temps de le lire — ce qui verifie au passage que le
# segment de jeu est bien devenu un reglage et non une valeur figee.
#
# La structure des pages One Piece de ZebraDex reste A VERIFIER :
# GET /api/admin/debug-zebradex rend la reponse brute pour la comparer.


def _jeu(slug):
    """Pointe le collecteur sur un jeu, le temps d'un test."""
    return mock.patch.object(zebradex_prices.settings, "zebradex_tcg_slug", slug)
REAL_SERIES_INDEX = '''
<a href="https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev04-5/destinees-de-paldea/6">Destinees</a>
<a href="https://zebradex.fr/fr/tcg/pokemon/wizards/set-de-base/set-de-base/119">Set de Base</a>
<a href="https://zebradex.fr/fr/tcg/pokemon/mega-evolution/me05/nuit-noire/460">Nuit Noire</a>
<a href="/fr/tcg/pokemon/ecarlate-et-violet/evsld/produits-scelles-ev/132">Scelles</a>
'''

REAL_SERIES_PAGE = '''
PAF 232 Destinées de Paldea 419,31 €  +9€ (7j)
<a href="https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev04-5/destinees-de-paldea/paf-232/mew-ex/2261">Voir la fiche</a>
PAF 232 Mew ex 419,31 € +9€ quantité : 0 Special Illustration Rare
PAF 234 Destinées de Paldea 232,37 €  +4,66€ (7j)
<a href="https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev04-5/destinees-de-paldea/paf-234/dracaufeu-ex/2263">Voir la fiche</a>
PAF 234 Dracaufeu ex 232,37 € +4,66€ quantité : 0 Special Illustration Rare
PAF 131 Destinées de Paldea 67,04 €  +0,25€ (7j)
<a href="https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev04-5/destinees-de-paldea/paf-131/pikachu/2161">Voir la fiche</a>
PAF 131 Pikachu 67,04 € +0,25€ quantité : 0 Shiny Rare
PAF 226 Destinées de Paldea 1,83 €  +0,04€ (7j)
<a href="https://zebradex.fr/fr/tcg/pokemon/ecarlate-et-violet/ev04-5/destinees-de-paldea/paf-226/pohm/2255">Voir la fiche</a>
PAF 226 Pohm 1,83 € +0,04€ quantité : 0 Illustration Rare
'''


class TestSeriesIndexParsing(unittest.TestCase):
    def test_finds_card_series_only(self):
        with _jeu("pokemon"):
            # 3 series de cartes ; les "produits scelles" sont exclus (ce ne
            # sont pas des cartes a l'unite).
            series = ZebraDexClient.parse_series_index(REAL_SERIES_INDEX)
            self.assertEqual(len(series), 3)
            self.assertNotIn("produits-scelles", " ".join(s.url for s in series))

    def test_extracts_bloc_and_code(self):
        with _jeu("pokemon"):
            series = {s.series_id: s for s in ZebraDexClient.parse_series_index(REAL_SERIES_INDEX)}
            self.assertEqual(series["6"].code, "EV04-5")
            self.assertEqual(series["119"].bloc, "Wizards")

    def test_empty_html_safe(self):
        with _jeu("pokemon"):
            self.assertEqual(ZebraDexClient.parse_series_index(""), [])


class TestSeriesPageParsing(unittest.TestCase):
    def setUp(self):
        # Les echantillons viennent des pages Pokemon : on vise ce jeu le
        # temps de les lire (voir la note en tete de fichier).
        correctif = _jeu("pokemon")
        correctif.start()
        self.addCleanup(correctif.stop)
        self.cards = {c.card_code: c for c in
                      ZebraDexClient.parse_series_page(REAL_SERIES_PAGE, "Destinees de Paldea")}

    def test_all_four_cards_found(self):
        self.assertEqual(len(self.cards), 4)

    def test_each_card_gets_its_own_price(self):
        # Regression : la fenetre de recherche debordait sur la carte
        # precedente, PAF 234 heritait du prix de PAF 232.
        self.assertAlmostEqual(self.cards["PAF 232"].price_eur, 419.31)
        self.assertAlmostEqual(self.cards["PAF 234"].price_eur, 232.37)
        self.assertAlmostEqual(self.cards["PAF 131"].price_eur, 67.04)
        self.assertAlmostEqual(self.cards["PAF 226"].price_eur, 1.83)

    def test_variation_not_mistaken_for_price(self):
        # Regression : "+4,66 EUR" (variation) etait pris pour le prix.
        self.assertAlmostEqual(self.cards["PAF 234"].variation_7d_eur, 4.66)
        self.assertNotAlmostEqual(self.cards["PAF 234"].price_eur, 4.66)

    def test_official_rarity_captured_per_card(self):
        # Regression : la rarete de la carte precedente etait heritee.
        self.assertEqual(self.cards["PAF 131"].rarity, "Shiny Rare")
        self.assertEqual(self.cards["PAF 226"].rarity, "Illustration Rare")
        self.assertEqual(self.cards["PAF 232"].rarity, "Special Illustration Rare")

    def test_price_range_derived_from_variation(self):
        card = self.cards["PAF 234"]
        self.assertAlmostEqual(card.price_low, 232.37 - 4.66, places=2)
        self.assertAlmostEqual(card.price_high, 232.37 + 4.66, places=2)

    def test_price_range_falls_back_when_no_variation(self):
        from app.collectors.zebradex_prices import ZebraDexCardPrice
        card = ZebraDexCardPrice(card_code="X 001", name="Test", name_slug="test", price_eur=100.0)
        self.assertAlmostEqual(card.price_low, 92.0)
        self.assertAlmostEqual(card.price_high, 108.0)

    def test_name_slug_usable_for_matching(self):
        self.assertEqual(self.cards["PAF 232"].name_slug, "mew-ex")

    def test_empty_html_safe(self):
        self.assertEqual(ZebraDexClient.parse_series_page(""), [])


class TestSlugify(unittest.TestCase):
    def test_accents_and_spaces(self):
        self.assertEqual(slugify_name("Salamèche ex"), "salameche-ex")


if __name__ == "__main__":
    unittest.main()


class TestJeuParametrable(unittest.TestCase):
    """Le segment de jeu dans l'URL ZebraDex est devenu un reglage, pour
    viser One Piece sans toucher au code. Ces tests verifient qu'il est bien
    pris en compte, et qu'il n'est pas fige au chargement du module."""

    def test_le_motif_suit_le_jeu_configure(self):
        with _jeu("one-piece"):
            motif_series, _ = zebradex_prices._motifs_du_jeu()
        self.assertIn("one", motif_series.pattern)
        self.assertNotIn("/pokemon/", motif_series.pattern)

    def test_un_echantillon_d_un_autre_jeu_n_est_pas_lu(self):
        """Garde-fou : si le reglage ne servait a rien, les liens Pokemon
        seraient lus alors que le projet vise One Piece."""
        with _jeu("one-piece"):
            self.assertEqual(ZebraDexClient.parse_series_index(REAL_SERIES_INDEX), [])
        with _jeu("pokemon"):
            self.assertEqual(len(ZebraDexClient.parse_series_index(REAL_SERIES_INDEX)), 3)

    def test_le_changement_de_reglage_est_pris_en_compte_apres_import(self):
        """Les motifs etaient compiles a l'import : un reglage change
        ensuite n'avait aucun effet, ce qui rend la configuration trompeuse."""
        with _jeu("un-autre-jeu"):
            motif, _ = zebradex_prices._motifs_du_jeu()
        self.assertIn("un\\-autre\\-jeu", motif.pattern)


if __name__ == "__main__":
    unittest.main()
