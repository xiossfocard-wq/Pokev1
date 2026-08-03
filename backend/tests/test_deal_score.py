import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scoring.deal_score import calculate_deal_score, DealScoreWeights, QualityBlend
from app.scoring.seller_reliability import score_ebay_seller, score_vinted_seller


class TestQualityBlend(unittest.TestCase):
    def test_falls_back_to_text_when_no_vision(self):
        blend = QualityBlend(text_score=70.0, vision_score=None)
        self.assertEqual(blend.combined(), 70.0)

    def test_vision_weighted_more_than_text(self):
        blend = QualityBlend(text_score=0.0, vision_score=100.0, vision_weight=0.65)
        self.assertAlmostEqual(blend.combined(), 65.0)


class TestCalculateDealScore(unittest.TestCase):
    def test_perfect_inputs_give_100(self):
        score = calculate_deal_score(
            margin_score_0_100=100,
            quality_blend=QualityBlend(text_score=100, vision_score=100),
            seller_score_0_100=100,
        )
        self.assertAlmostEqual(score, 100.0)

    def test_zero_inputs_give_0(self):
        score = calculate_deal_score(
            margin_score_0_100=0,
            quality_blend=QualityBlend(text_score=0, vision_score=0),
            seller_score_0_100=0,
        )
        self.assertAlmostEqual(score, 0.0)

    def test_weights_change_outcome(self):
        # Marge excellente mais qualité/vendeur médiocres
        blend = QualityBlend(text_score=20, vision_score=20)
        margin_heavy = calculate_deal_score(
            90, blend, 20, weights=DealScoreWeights(margin=0.8, quality=0.1, seller=0.1)
        )
        quality_heavy = calculate_deal_score(
            90, blend, 20, weights=DealScoreWeights(margin=0.1, quality=0.8, seller=0.1)
        )
        self.assertGreater(margin_heavy, quality_heavy)

    def test_weights_are_normalized_even_if_not_summing_to_1(self):
        blend = QualityBlend(text_score=50, vision_score=50)
        score = calculate_deal_score(
            50, blend, 50, weights=DealScoreWeights(margin=5, quality=3, seller=2)
        )
        self.assertAlmostEqual(score, 50.0)

    def test_out_of_range_input_raises(self):
        blend = QualityBlend(text_score=50, vision_score=50)
        with self.assertRaises(ValueError):
            calculate_deal_score(150, blend, 50)


class TestSellerReliability(unittest.TestCase):
    def test_ebay_missing_data_returns_neutral_estimate(self):
        result = score_ebay_seller(None, None)
        self.assertTrue(result.is_estimated)

    def test_ebay_high_feedback_many_reviews(self):
        result = score_ebay_seller(feedback_percentage=99.5, feedback_score=500)
        self.assertGreater(result.score, 90)
        self.assertFalse(result.is_estimated)

    def test_ebay_high_feedback_but_few_reviews_is_discounted(self):
        confident = score_ebay_seller(feedback_percentage=100, feedback_score=500)
        unconfident = score_ebay_seller(feedback_percentage=100, feedback_score=2)
        self.assertGreater(confident.score, unconfident.score)
        self.assertTrue(unconfident.is_estimated)

    def test_vinted_no_reviews_is_neutral(self):
        result = score_vinted_seller(review_count=0, average_rating=None)
        self.assertTrue(result.is_estimated)

    def test_vinted_good_rating_many_reviews(self):
        result = score_vinted_seller(review_count=50, average_rating=4.9)
        self.assertGreater(result.score, 85)


if __name__ == "__main__":
    unittest.main()
