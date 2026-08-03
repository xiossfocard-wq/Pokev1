import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scoring.margin import calculate_margin, normalize_margin_ratio, FeeConfig


class TestCalculateMargin(unittest.TestCase):
    def test_clear_good_deal(self):
        # Carte annoncée 20€ + 3€ de port sur Vinted, cote Cardmarket 60€
        result = calculate_margin(
            listing_price=20.0,
            listing_shipping=3.0,
            reference_price=60.0,
            resale_channel="cardmarket",
        )
        self.assertGreater(result.net_margin, 0)
        self.assertAlmostEqual(result.listing_total_cost, 23.0)
        # 60 * (1 - 0.10 haircut) = 54 ; fees = 54*0.015 = 0.81 ; reship 2.5
        self.assertAlmostEqual(result.reference_price_used, 54.0, places=2)
        self.assertAlmostEqual(result.resale_fees, 0.81, places=2)
        self.assertAlmostEqual(result.net_resale_value, 54.0 - 0.81 - 2.5, places=2)

    def test_bad_deal_overpriced(self):
        # Annonce à 55€ pour une carte qui vaut 40€ -> marge négative
        result = calculate_margin(
            listing_price=55.0,
            listing_shipping=4.0,
            reference_price=40.0,
        )
        self.assertLess(result.net_margin, 0)
        self.assertLess(result.margin_ratio, 0)

    def test_ebay_channel_applies_higher_fees(self):
        common_kwargs = dict(listing_price=20.0, listing_shipping=0.0, reference_price=60.0)
        cardmarket_result = calculate_margin(**common_kwargs, resale_channel="cardmarket")
        ebay_result = calculate_margin(**common_kwargs, resale_channel="ebay")
        self.assertGreater(cardmarket_result.net_margin, ebay_result.net_margin)

    def test_negative_price_raises(self):
        with self.assertRaises(ValueError):
            calculate_margin(listing_price=-1, listing_shipping=0, reference_price=10)

    def test_zero_cost_no_division_error(self):
        result = calculate_margin(listing_price=0, listing_shipping=0, reference_price=10)
        self.assertEqual(result.margin_ratio, 0.0)

    def test_custom_fee_config(self):
        cfg = FeeConfig(
            seller_fee_ratio={"cardmarket": 0.05, "ebay": 0.13, "vinted": 0.0},
            payment_fee_ratio=0.0,
            reshipping_cost_eur=0.0,
            reference_price_haircut=0.0,
        )
        result = calculate_margin(
            listing_price=10, listing_shipping=0, reference_price=100,
            resale_channel="cardmarket", fee_config=cfg,
        )
        # reference_price_used = 100 (pas de haircut), fees = 100*0.05 = 5
        self.assertAlmostEqual(result.reference_price_used, 100.0)
        self.assertAlmostEqual(result.resale_fees, 5.0)
        self.assertAlmostEqual(result.net_resale_value, 95.0)
        self.assertAlmostEqual(result.net_margin, 85.0)


class TestNormalizeMarginRatio(unittest.TestCase):
    def test_negative_ratio_clips_to_zero(self):
        self.assertEqual(normalize_margin_ratio(-0.5), 0.0)

    def test_ratio_at_cap(self):
        self.assertEqual(normalize_margin_ratio(1.0, cap_ratio=1.0), 100.0)

    def test_ratio_above_cap_clips_to_100(self):
        self.assertEqual(normalize_margin_ratio(2.5, cap_ratio=1.0), 100.0)

    def test_ratio_midpoint(self):
        self.assertAlmostEqual(normalize_margin_ratio(0.5, cap_ratio=1.0), 50.0)

    def test_invalid_cap_raises(self):
        with self.assertRaises(ValueError):
            normalize_margin_ratio(0.5, cap_ratio=0)


if __name__ == "__main__":
    unittest.main()
