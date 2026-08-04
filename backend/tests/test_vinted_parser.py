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


# Échantillon RÉEL récupéré le 04/08/2026 via /api/admin/debug-vinted en
# production (pas une reconstruction/supposition) — c'est ce qui a permis de
# découvrir que la page catalogue n'utilise ni __NEXT_DATA__ ni __NUXT__, et
# de construire le parsing HTML direct ci-dessous.
REAL_CATALOG_SAMPLE = (
    'État: Neuf sans étiquette, 20.00 €, 21.70 €" class="web_ui__Image__content" '
    'data-testid="product-item-id-9568927977--image--img"/></div></div>'
    '<a href="/items/9568927977-pokemon?referrer=catalog" '
    'class="new-item-box__overlay new-item-box__overlay--clickable" '
    'data-testid="product-item-id-9568927977--overlay-link" '
    'title="Pokémon, Marque: Pokémon, État: Neuf sans étiquette, 20.00 €, 21.70 €" '
    'target="_self" rel="noreferrer"><div></div></a>'
    'okémon, État: Très bon état, 2.99 €, 3.84 €" class="web_ui__Image__content" '
    'data-testid="product-item-id-9559647063--image--img"/></div></div>'
    '<a href="/items/9559647063-magicarpe-fr-1998-excellent?referrer=catalog" '
    'class="new-item-box__overlay new-item-box__overlay--clickable" '
    'data-testid="product-item-id-9559647063--overlay-link" '
    'title="Magicarpe FR 19/98 - Excellent, Marque: Pokémon, État: Très bon état, 2.99 €, 3.84 €" '
    'target="_self" rel="noreferrer">'
    '<img src="https://images1.vinted.net/t/05_00373_fake/310x430/4ed3b325.webp" '
    'data-testid="product-item-id-9559647063--image--img"/>'
)


class TestVintedCatalogHtmlParsing(unittest.TestCase):
    """Parsing HTML direct (v2, remplace le blob JSON qui n'existe pas sur
    la page catalogue — voir REAL_CATALOG_SAMPLE ci-dessus)."""

    def test_finds_both_real_items(self):
        listings = VintedScraper._parse_catalog_html(REAL_CATALOG_SAMPLE)
        self.assertEqual(len(listings), 2)

    def test_extracts_id_price_and_url_correctly(self):
        listings = VintedScraper._parse_catalog_html(REAL_CATALOG_SAMPLE)
        by_id = {l.item_id: l for l in listings}

        magicarpe = by_id["9559647063"]
        self.assertEqual(magicarpe.title, "Magicarpe FR 19/98 - Excellent")
        self.assertAlmostEqual(magicarpe.price, 2.99)
        self.assertEqual(magicarpe.url, "https://www.vinted.fr/items/9559647063-magicarpe-fr-1998-excellent")
        self.assertEqual(magicarpe.raw["condition"], "Très bon état")
        self.assertAlmostEqual(magicarpe.raw["price_incl_protection_acheteur"], 3.84)

    def test_generic_title_still_captured(self):
        # Le vendeur n'a pas mis de titre descriptif ("Pokémon" tout seul) :
        # on garde quand même l'annonce, le matching/OCR compenseront.
        listings = VintedScraper._parse_catalog_html(REAL_CATALOG_SAMPLE)
        by_id = {l.item_id: l for l in listings}
        self.assertEqual(by_id["9568927977"].title, "Pokémon")
        self.assertAlmostEqual(by_id["9568927977"].price, 20.00)

    def test_photo_url_matched_by_item_id(self):
        listings = VintedScraper._parse_catalog_html(REAL_CATALOG_SAMPLE)
        by_id = {l.item_id: l for l in listings}
        self.assertEqual(
            by_id["9559647063"].photo_urls,
            ["https://images1.vinted.net/t/05_00373_fake/310x430/4ed3b325.webp"],
        )

    def test_no_duplicate_when_id_appears_twice(self):
        doubled = REAL_CATALOG_SAMPLE + REAL_CATALOG_SAMPLE
        listings = VintedScraper._parse_catalog_html(doubled)
        self.assertEqual(len(listings), 2)

    def test_empty_html_returns_empty_list(self):
        self.assertEqual(VintedScraper._parse_catalog_html(""), [])

    def test_parse_title_attr_without_marque_returns_none(self):
        self.assertIsNone(VintedScraper._parse_title_attr("Rien de pertinent ici"))


if __name__ == "__main__":
    unittest.main()
