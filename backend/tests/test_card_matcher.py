import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.matching.card_matcher import guess_card_from_title


class TestCardMatcher(unittest.TestCase):
    def test_extracts_set_number(self):
        match = guess_card_from_title("Dracaufeu 4/102 Base Set holo TBE")
        self.assertEqual(match.set_number, "4/102")
        self.assertEqual(match.confidence, "medium")

    def test_no_set_number_lowers_confidence(self):
        match = guess_card_from_title("Carte Pokemon Dracaufeu rare")
        self.assertIsNone(match.set_number)
        self.assertEqual(match.confidence, "low")

    def test_noise_words_removed(self):
        match = guess_card_from_title("Lot cartes pokemon Pikachu vintage TBE")
        self.assertNotIn("Lot", match.card_name_guess)
        self.assertNotIn("Pokemon", match.card_name_guess)

    def test_empty_title_returns_none(self):
        self.assertIsNone(guess_card_from_title(""))

    def test_slug_is_capitalized_and_hyphenated(self):
        match = guess_card_from_title("dracaufeu vmax 4/102")
        self.assertEqual(match.card_slug, "Dracaufeu-Vmax")


if __name__ == "__main__":
    unittest.main()
