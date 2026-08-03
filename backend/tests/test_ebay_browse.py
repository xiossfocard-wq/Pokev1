import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.ebay_browse import EbayBrowseClient


SAMPLE_ITEM_SUMMARY = {
    "itemId": "v1|123456789|0",
    "title": "Carte Pokemon Dracaufeu VMAX FR",
    "price": {"value": "89.99", "currency": "EUR"},
    "shippingOptions": [{"shippingCost": {"value": "4.50", "currency": "EUR"}}],
    "itemWebUrl": "https://www.ebay.fr/itm/123456789",
    "image": {"imageUrl": "https://i.ebayimg.com/thumbs/abc.jpg"},
    "condition": "Used",
    "seller": {"username": "cardshopfr", "feedbackPercentage": "99.4", "feedbackScore": 1523},
    "itemLocation": {"country": "FR"},
}

SAMPLE_ITEM_SUMMARY_NO_SHIPPING_NO_SELLER_FEEDBACK = {
    "itemId": "v1|987654321|0",
    "title": "Lot cartes Pokemon vrac",
    "price": {"value": "15.0", "currency": "EUR"},
    "shippingOptions": [],
    "itemWebUrl": "https://www.ebay.fr/itm/987654321",
    "image": {},
    "seller": {"username": "newbie2024"},
    "itemLocation": {"country": "FR"},
}


class TestEbayBrowseParsing(unittest.TestCase):
    def test_parse_full_item_summary(self):
        listing = EbayBrowseClient._parse_item_summary(SAMPLE_ITEM_SUMMARY)
        self.assertEqual(listing.item_id, "v1|123456789|0")
        self.assertAlmostEqual(listing.price, 89.99)
        self.assertAlmostEqual(listing.shipping_cost, 4.50)
        self.assertEqual(listing.seller_username, "cardshopfr")
        self.assertAlmostEqual(listing.seller_feedback_percentage, 99.4)
        self.assertEqual(listing.seller_feedback_score, 1523)
        self.assertEqual(listing.item_location_country, "FR")

    def test_parse_item_with_missing_optional_fields(self):
        listing = EbayBrowseClient._parse_item_summary(
            SAMPLE_ITEM_SUMMARY_NO_SHIPPING_NO_SELLER_FEEDBACK
        )
        self.assertIsNone(listing.shipping_cost)
        self.assertIsNone(listing.image_url)
        self.assertIsNone(listing.seller_feedback_percentage)
        self.assertIsNone(listing.seller_feedback_score)

    def test_token_cache_avoids_refetch(self):
        client = EbayBrowseClient(client_id="fake", client_secret="fake")
        client._access_token = "cached-token"
        client._token_expires_at = 9_999_999_999  # loin dans le futur
        # Ne doit pas lever d'exception réseau car on ne devrait pas
        # appeler requests.post grâce au cache
        token = client._get_access_token()
        self.assertEqual(token, "cached-token")


if __name__ == "__main__":
    unittest.main()
