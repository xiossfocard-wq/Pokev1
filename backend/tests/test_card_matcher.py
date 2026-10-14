import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.matching.card_matcher import guess_card_from_title


class TestCardMatcher(unittest.TestCase):
    def test_le_code_carte_donne_la_confiance(self):
        """La confiance ne reposait que sur le format « X/Y », que One Piece
        n'emploie pas : toute annonce du jeu ressortait en confiance basse,
        aussi precise soit-elle."""
        match = guess_card_from_title("Monkey D. Luffy OP01-120 Romance Dawn holo TBE")
        self.assertEqual(match.card_code, "OP01-120")
        self.assertEqual(match.confidence, "medium")

    def test_le_code_est_normalise(self):
        match = guess_card_from_title("Carte One Piece Nami OP01-4")
        self.assertEqual(match.card_code, "OP01-004")

    def test_le_code_sort_du_nom_devine(self):
        match = guess_card_from_title("Monkey D. Luffy OP01-120")
        self.assertNotIn("OP01", match.card_name_guess)

    def test_sans_code_la_confiance_baisse(self):
        match = guess_card_from_title("Carte One Piece Roronoa Zoro rare")
        self.assertIsNone(match.card_code)
        self.assertIsNone(match.set_number)
        self.assertEqual(match.confidence, "low")

    def test_noise_words_removed(self):
        match = guess_card_from_title("Lot cartes one piece Nami vintage TBE")
        self.assertNotIn("Lot", match.card_name_guess)
        self.assertNotIn("One", match.card_name_guess)

    def test_empty_title_returns_none(self):
        self.assertIsNone(guess_card_from_title(""))

    def test_slug_is_capitalized_and_hyphenated(self):
        match = guess_card_from_title("monkey d. luffy leader op01-003")
        self.assertEqual(match.card_slug, "Monkey-D-Luffy-Leader")

    def test_leader_fait_partie_du_nom(self):
        """Contrairement a « SEC » ou « SR », qui qualifient le tirage,
        « Leader » designe une autre carte : il ne doit pas etre efface."""
        match = guess_card_from_title("Carte One Piece Monkey D. Luffy Leader")
        self.assertIn("Leader", match.card_name_guess)


if __name__ == "__main__":
    unittest.main()
