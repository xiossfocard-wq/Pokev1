import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.cardmarket_prices import CardmarketPriceClient


FIXTURE_HTML_EN = """
<div class="price-guide">
  <dl>
    <dt>Price Trend</dt><dd>12,50 €</dd>
    <dt>30-days average</dt><dd>14,30 €</dd>
  </dl>
</div>
"""

FIXTURE_HTML_NO_PRICE = "<html><body>Produit introuvable</body></html>"


class TestCardmarketPriceExtraction(unittest.TestCase):
    def setUp(self):
        self.client = CardmarketPriceClient()

    def test_extract_trend_price(self):
        price = self.client._extract_price(FIXTURE_HTML_EN, label_hints=["Price Trend", "Trend"])
        self.assertEqual(price, 12.50)

    def test_extract_30d_average(self):
        price = self.client._extract_price(
            FIXTURE_HTML_EN, label_hints=["30-days average", "30 days average"]
        )
        self.assertEqual(price, 14.30)

    def test_missing_price_returns_none(self):
        price = self.client._extract_price(FIXTURE_HTML_NO_PRICE, label_hints=["Trend"])
        self.assertIsNone(price)

    def test_build_product_url(self):
        url = self.client.build_product_url("Base-Set", "Charizard")
        self.assertEqual(url, "https://www.cardmarket.com/en/Pokemon/Products/Singles/Base-Set/Charizard")


BULK_CSV_SEMICOLON = (
    "Name;Trend;30-days average\n"
    "Dracaufeu VMAX;45.50;48.10\n"
    "Pikachu Illustrator;180000.00;175000.00\n"
)

BULK_CSV_COMMA_ALT_COLUMNS = (
    "Product Name,Price Trend\n"
    "Mewtwo ex,3.20\n"  # séparateur CSV virgule -> décimales en point (pas d'ambiguïté possible)
)

BULK_CSV_BAD_FORMAT = "Foo;Bar\n1;2\n"


class TestBulkPriceGuideParsing(unittest.TestCase):
    def test_parses_semicolon_csv_with_standard_columns(self):
        prices = CardmarketPriceClient._parse_bulk_csv(BULK_CSV_SEMICOLON)
        self.assertIn("Dracaufeu-Vmax", prices)
        self.assertAlmostEqual(prices["Dracaufeu-Vmax"], 45.50)

    def test_handles_alternate_column_names(self):
        prices = CardmarketPriceClient._parse_bulk_csv(BULK_CSV_COMMA_ALT_COLUMNS)
        self.assertIn("Mewtwo-Ex", prices)

    def test_unknown_columns_returns_empty_dict(self):
        prices = CardmarketPriceClient._parse_bulk_csv(BULK_CSV_BAD_FORMAT)
        self.assertEqual(prices, {})

    def test_empty_csv_returns_empty_dict(self):
        prices = CardmarketPriceClient._parse_bulk_csv("")
        self.assertEqual(prices, {})


if __name__ == "__main__":
    unittest.main()
