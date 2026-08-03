import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.zebradex_prices import ZebraDexPriceClient


# Échantillon synthétique inspiré de la structure textuelle observée sur une
# page série ZebraDex réelle (code + nom + prix + variation + quantité
# répétés) — pas une copie verbatim d'une page, une reconstruction pour les
# besoins du test.
SAMPLE_SERIES_TEXT = (
    "245 items PAF 232 Destinées de Paldea 429,39 € -12€ (7j) "
    "PAF 232 Mew ex 429,39 € -12€ quantité : 0 Special Illustration Rare "
    "PAF 234 Destinées de Paldea 228,60 € +13€ (7j) "
    "PAF 234 Dracaufeu ex 228,60 € +13€ quantité : 0 Special Illustration Rare "
    "PAF 160 Destinées de Paldea 42,97 € – "
    "PAF 160 Ronflex 42,97 € – quantité : 0"
)

SAMPLE_NO_CARDS_TEXT = "<html><body>Aucun résultat</body></html>"


class TestZebraDexSeriesParsing(unittest.TestCase):
    def test_parses_all_cards_in_sample(self):
        prices = ZebraDexPriceClient._parse_series_text(SAMPLE_SERIES_TEXT)
        self.assertEqual(len(prices), 3)

    def test_extracts_correct_price_per_card(self):
        prices = ZebraDexPriceClient._parse_series_text(SAMPLE_SERIES_TEXT)
        self.assertAlmostEqual(prices["Dracaufeu-Ex"], 228.60)
        self.assertAlmostEqual(prices["Mew-Ex"], 429.39)
        self.assertAlmostEqual(prices["Ronflex"], 42.97)

    def test_does_not_pick_up_the_summary_line_price(self):
        # Le nom extrait doit être celui de la carte ("Mew ex"), pas celui
        # de la série ("Destinées de Paldea") qui précède dans le texte.
        prices = ZebraDexPriceClient._parse_series_text(SAMPLE_SERIES_TEXT)
        self.assertNotIn("Destinees-De-Paldea", prices)

    def test_no_matching_content_returns_empty_dict(self):
        prices = ZebraDexPriceClient._parse_series_text(SAMPLE_NO_CARDS_TEXT)
        self.assertEqual(prices, {})

    def test_empty_text_returns_empty_dict(self):
        self.assertEqual(ZebraDexPriceClient._parse_series_text(""), {})


if __name__ == "__main__":
    unittest.main()
