import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.matching.title_parser import (
    extract_card_codes, extract_set_number, extract_name_candidates, normalize,
)


class TestExtractCardCodes(unittest.TestCase):
    def test_zebradex_style_code_zero_padded(self):
        # ZebraDex zero-pad ses codes : "PAF 5" dans une annonce doit
        # matcher "PAF 005" dans l'index.
        self.assertIn("PAF 005", extract_card_codes("Carte PAF 5 rare"))

    def test_code_with_dash(self):
        self.assertIn("EV01 045", extract_card_codes("pokemon EV01-045 FR"))

    def test_already_padded_code_kept(self):
        self.assertIn("PAF 232", extract_card_codes("Mew ex PAF 232 SIR"))

    def test_no_code_returns_empty(self):
        self.assertEqual(extract_card_codes("Belle carte pokemon holo"), [])


class TestExtractSetNumber(unittest.TestCase):
    def test_classic_vintage_number(self):
        self.assertEqual(extract_set_number("Dracaufeu 4/102 set de base"), ("004", "102"))

    def test_modern_number(self):
        self.assertEqual(extract_set_number("Mew ex 232/193"), ("232", "193"))

    def test_spaces_around_slash(self):
        self.assertEqual(extract_set_number("carte 19 / 98 excellent"), ("019", "098"))

    def test_none_when_absent(self):
        self.assertIsNone(extract_set_number("carte pokemon sans numero"))


class TestExtractNameCandidates(unittest.TestCase):
    def test_pairs_come_before_single_words(self):
        candidates = extract_name_candidates("Mew ex rare")
        self.assertIn("mew-ex", candidates)
        self.assertLess(candidates.index("mew-ex"), candidates.index("mew"))

    def test_suffix_alone_is_excluded(self):
        # "ex" seul ne doit jamais etre un candidat : sinon toute annonce
        # contenant "ex" matcherait n'importe quelle carte "ex".
        self.assertNotIn("ex", extract_name_candidates("Dracaufeu ex holo"))

    def test_noise_words_excluded_as_single(self):
        candidates = extract_name_candidates("carte pokemon Pikachu holo rare")
        self.assertIn("pikachu", candidates)
        self.assertNotIn("carte", candidates)
        self.assertNotIn("pokemon", candidates)

    def test_accents_normalized(self):
        self.assertIn("salameche", extract_name_candidates("Salamèche brillante"))

    def test_pure_numbers_excluded_as_single(self):
        self.assertNotIn("102", extract_name_candidates("Dracaufeu 4/102"))

    def test_empty_input_safe(self):
        self.assertEqual(extract_name_candidates(""), [])


class TestNormalize(unittest.TestCase):
    def test_accents_and_case(self):
        self.assertEqual(normalize("Écarlate ET Violet"), "ecarlate et violet")

    def test_none_safe(self):
        self.assertEqual(normalize(None), "")


if __name__ == "__main__":
    unittest.main()
