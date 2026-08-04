import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.core.language_filter import looks_non_french

class TestLanguageFilter(unittest.TestCase):
    def test_plain_french_title_not_flagged(self):
        self.assertFalse(looks_non_french("Dracaufeu 4/102 très bon état"))
    def test_common_french_words_not_falsely_flagged(self):
        self.assertFalse(looks_non_french("Carte en très bon état de collection"))
    def test_explicit_english_flagged(self):
        self.assertTrue(looks_non_french("Zekrom carte anglaise rare"))
    def test_explicit_japanese_flagged(self):
        self.assertTrue(looks_non_french("Pikachu version japonaise"))

if __name__ == "__main__":
    unittest.main()
