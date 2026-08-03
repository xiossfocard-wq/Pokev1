import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scoring.quality_text import analyze_text_quality


class TestAnalyzeTextQuality(unittest.TestCase):
    def test_neutral_description(self):
        result = analyze_text_quality("Dracaufeu 4/102", "Carte Pokémon à vendre")
        self.assertEqual(result.score, 50.0)
        self.assertEqual(result.matched_positive, [])
        self.assertEqual(result.matched_negative, [])

    def test_positive_keywords_raise_score(self):
        result = analyze_text_quality(
            "Dracaufeu PSA 10", "Carte near mint, jamais joué, sortie de booster"
        )
        self.assertGreater(result.score, 50.0)
        self.assertIn("psa 10", result.matched_positive)
        self.assertIn("near mint", result.matched_positive)

    def test_negative_keywords_lower_score(self):
        result = analyze_text_quality(
            "Pikachu Illustrator", "Attention rayure visible au dos, coin abimé"
        )
        self.assertLess(result.score, 50.0)
        self.assertIn("rayure", result.matched_negative)

    def test_negation_is_detected_and_not_counted_as_negative(self):
        result = analyze_text_quality("Mewtwo", "Vendue sans rayure, sans défaut")
        self.assertEqual(result.matched_negative, [])
        self.assertIn("rayure", result.negated_negative)
        self.assertIn("défaut", result.negated_negative)
        # les négations donnent un léger bonus, donc score >= 50
        self.assertGreaterEqual(result.score, 50.0)

    def test_score_is_clamped_between_0_and_100(self):
        many_negatives = " ".join(["rayure défaut pli usure taché"] * 5)
        result = analyze_text_quality("", many_negatives)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 100.0)

    def test_handles_none_gracefully(self):
        result = analyze_text_quality(None, None)
        self.assertEqual(result.score, 50.0)


if __name__ == "__main__":
    unittest.main()
