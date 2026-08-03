import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.vinted_scraper import VintedScraper


FIXTURE_HTML = """
<html><head><title>Cartes Pokémon</title></head>
<body>
<div id="app">contenu visible non pertinent</div>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "catalog": {
        "items": [
          {
            "id": 111222333,
            "title": "Dracaufeu 4/102 Base Set",
            "price": {"amount": "45.0", "currency_code": "EUR"},
            "url": "https://www.vinted.fr/items/111222333-dracaufeu",
            "photo": {"url": "https://images.vinted.net/photo1.jpg"},
            "user": {"login": "collectionneur75", "feedback_count": 12, "feedback_reputation": 4.8}
          },
          {
            "id": 444555666,
            "title": "Pikachu Illustrator FAKE",
            "price": {"amount": "9999.0", "currency_code": "EUR"},
            "url": "https://www.vinted.fr/items/444555666-pikachu",
            "photo": {"url": "https://images.vinted.net/photo2.jpg"},
            "user": {"login": "newseller", "feedback_count": 0, "feedback_reputation": null}
          }
        ]
      }
    }
  }
}
</script>
</body></html>
"""


class TestVintedJsonExtraction(unittest.TestCase):
    def setUp(self):
        self.scraper = VintedScraper()

    def test_extract_json_blob_finds_next_data(self):
        blob = self.scraper._extract_json_blob(FIXTURE_HTML)
        self.assertIsNotNone(blob)
        self.assertIn("props", blob)

    def test_walk_for_items_finds_both_items(self):
        blob = self.scraper._extract_json_blob(FIXTURE_HTML)
        items = self.scraper._walk_for_items(blob)
        self.assertEqual(len(items), 2)
        ids = {item["id"] for item in items}
        self.assertEqual(ids, {111222333, 444555666})

    def test_parse_raw_item_maps_fields_correctly(self):
        blob = self.scraper._extract_json_blob(FIXTURE_HTML)
        items = self.scraper._walk_for_items(blob)
        parsed = self.scraper._parse_raw_item(items[0])
        self.assertEqual(parsed.item_id, "111222333")
        self.assertEqual(parsed.title, "Dracaufeu 4/102 Base Set")
        self.assertAlmostEqual(parsed.price, 45.0)
        self.assertEqual(parsed.currency, "EUR")
        self.assertEqual(parsed.seller_username, "collectionneur75")
        self.assertEqual(parsed.seller_review_count, 12)

    def test_parse_raw_item_handles_missing_seller_data(self):
        blob = self.scraper._extract_json_blob(FIXTURE_HTML)
        items = self.scraper._walk_for_items(blob)
        parsed = self.scraper._parse_raw_item(items[1])
        self.assertEqual(parsed.seller_review_count, 0)
        self.assertIsNone(parsed.seller_average_rating)

    def test_extract_json_blob_returns_none_on_garbage(self):
        blob = self.scraper._extract_json_blob("<html><body>rien ici</body></html>")
        self.assertIsNone(blob)


if __name__ == "__main__":
    unittest.main()
