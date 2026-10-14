"""
Garde-fous de base de la detection de langue.

Volontairement plus courts et plus grossiers que test_language_filter_v3 :
ce sont les cas qui ne doivent jamais regresser, quelle que soit la
sophistication ajoutee ensuite au filtre.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.language_filter import looks_non_french


class TestLanguageFilter(unittest.TestCase):
    def test_plain_french_title_not_flagged(self):
        self.assertFalse(looks_non_french("Monkey D. Luffy OP01-120 très bon état"))

    def test_common_french_words_not_falsely_flagged(self):
        # "en" et "de" sont des mots français ordinaires : ne doivent PAS
        # déclencher le filtre à eux seuls.
        self.assertFalse(looks_non_french("Carte en très bon état de collection"))

    def test_explicit_english_flagged(self):
        self.assertTrue(looks_non_french("One Piece Kaido carte anglaise rare"))
        self.assertTrue(looks_non_french("One Piece Kaido english card"))

    def test_explicit_japanese_flagged(self):
        self.assertTrue(looks_non_french("Luffy version japonaise"))

    def test_condition_field_also_checked(self):
        self.assertTrue(looks_non_french("Kaido", "État japonais, très bon état"))

    def test_none_and_empty_inputs_handled(self):
        self.assertFalse(looks_non_french(None, "", None))

    def test_generic_short_title_not_flagged(self):
        self.assertFalse(looks_non_french("One Piece"))


class TestLanguageFilterV2(unittest.TestCase):
    def test_japanese_script_detected(self):
        self.assertTrue(looks_non_french("ルフィ 美品"))

    def test_korean_script_detected(self):
        self.assertTrue(looks_non_french("원피스 카드"))

    def test_chinese_script_detected(self):
        self.assertTrue(looks_non_french("海贼王 卡片"))

    def test_short_token_jp_detected(self):
        self.assertTrue(looks_non_french("Luffy JP Romance Dawn"))

    def test_short_token_kr_detected(self):
        self.assertTrue(looks_non_french("Zoro KR promo"))

    def test_jp_does_not_match_inside_other_word(self):
        self.assertFalse(looks_non_french("carte enjpolie fictive"))

    def test_generic_french_title_still_passes(self):
        self.assertFalse(looks_non_french("Carte One Piece Luffy très bon état"))

    def test_empty_still_passes(self):
        self.assertFalse(looks_non_french("", None))


# Ce bloc etait place au MILIEU du fichier, avant TestLanguageFilterV2 :
# lance directement (python test_language_filter.py), unittest.main()
# s'executait avant que la seconde classe ne soit definie, et ses tests
# ne tournaient jamais. Invisible en discovery, ou __name__ differe.
if __name__ == "__main__":
    unittest.main()
