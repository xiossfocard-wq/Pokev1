import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.collectors.zebradex_prices import ZebraDexClient, slugify_name

# ECHANTILLONS REELS recuperes le 04/08/2026 depuis zebradex.fr
# (pas des reconstructions : copies de la structure reellement servie).
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
        # 3 series de cartes ; les "produits scelles" sont exclus (ce ne
        # sont pas des cartes a l'unite).
        series = ZebraDexClient.parse_series_index(REAL_SERIES_INDEX)
        self.assertEqual(len(series), 3)
        self.assertNotIn("produits-scelles", " ".join(s.url for s in series))

    def test_extracts_bloc_and_code(self):
        series = {s.series_id: s for s in ZebraDexClient.parse_series_index(REAL_SERIES_INDEX)}
        self.assertEqual(series["6"].code, "EV04-5")
        self.assertEqual(series["119"].bloc, "Wizards")

    def test_empty_html_safe(self):
        self.assertEqual(ZebraDexClient.parse_series_index(""), [])


class TestSeriesPageParsing(unittest.TestCase):
    def setUp(self):
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
