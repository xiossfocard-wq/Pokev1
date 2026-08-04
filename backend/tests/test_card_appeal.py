import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.scoring.card_appeal import detect_card_appeal


class TestCardAppeal(unittest.TestCase):
    def test_sir_detected_with_max_rarity_bonus(self):
        r = detect_card_appeal("Dracaufeu ex Special Illustration Rare 199/165")
        self.assertEqual(r["rarity_tier"], "Special/Secret Illustration Rare")
        self.assertGreaterEqual(r["appeal_bonus"], 30)

    def test_sir_abbreviation_detected(self):
        r = detect_card_appeal("Mew SIR SV08 rare")
        self.assertEqual(r["rarity_tier"], "Special/Secret Illustration Rare")

    def test_illustration_rare_detected(self):
        r = detect_card_appeal("Pikachu Illustration Rare 251")
        self.assertEqual(r["rarity_tier"], "Illustration Rare")

    def test_vintage_set_detected(self):
        r = detect_card_appeal("Dracaufeu Set de Base 4/102")
        self.assertTrue(r["is_vintage"])

    def test_popular_pokemon_detected(self):
        r = detect_card_appeal("Pikachu holo rare")
        self.assertTrue(r["is_popular_pokemon"])
        self.assertEqual(r["popular_pokemon_matched"], "pikachu")

    def test_plain_common_card_no_bonus(self):
        r = detect_card_appeal("Ptitard commune 34/165")
        self.assertEqual(r["appeal_bonus"], 0)
        self.assertIsNone(r["rarity_tier"])
        self.assertFalse(r["is_vintage"])

    def test_bonus_is_capped_at_30(self):
        r = detect_card_appeal("Pikachu SIR vintage Set de Base 1999 Shadowless")
        self.assertLessEqual(r["appeal_bonus"], 30)

    def test_empty_text_handled(self):
        r = detect_card_appeal("", "")
        self.assertEqual(r["appeal_bonus"], 0)


if __name__ == "__main__":
    unittest.main()
