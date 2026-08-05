import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.language_filter import looks_non_french


class TestLanguageFilter(unittest.TestCase):
    def test_plain_french_title_not_flagged(self):
        self.assertFalse(looks_non_french("Dracaufeu 4/102 très bon état"))

    def test_common_french_words_not_falsely_flagged(self):
        # "en" et "de" sont des mots français ordinaires : ne doivent PAS
        # déclencher le filtre à eux seuls.
        self.assertFalse(looks_non_french("Carte en très bon état de collection"))

    def test_explicit_english_flagged(self):
        self.assertTrue(looks_non_french("Zekrom carte anglaise rare"))
        self.assertTrue(looks_non_french("Zekrom english card"))

    def test_explicit_japanese_flagged(self):
        self.assertTrue(looks_non_french("Pikachu version japonaise"))

    def test_condition_field_also_checked(self):
        self.assertTrue(looks_non_french("Zekrom", "État japonais, très bon état"))

    def test_none_and_empty_inputs_handled(self):
        self.assertFalse(looks_non_french(None, "", None))

    def test_generic_short_title_not_flagged(self):
        self.assertFalse(looks_non_french("Pokémon"))


if __name__ == "__main__":
    unittest.main()


class TestLanguageFilterV2(unittest.TestCase):
    def test_japanese_script_detected(self):
        self.assertTrue(looks_non_french("ピカチュウ 美品"))

    def test_korean_script_detected(self):
        self.assertTrue(looks_non_french("포켓몬 카드"))

    def test_chinese_script_detected(self):
        self.assertTrue(looks_non_french("宝可梦 卡片"))

    def test_short_token_jp_detected(self):
        self.assertTrue(looks_non_french("Dracaufeu JP set de base"))

    def test_short_token_kr_detected(self):
        self.assertTrue(looks_non_french("Pikachu KR promo"))

    def test_jp_does_not_match_inside_other_word(self):
        self.assertFalse(looks_non_french("carte enjpolie fictive"))

    def test_generic_french_title_still_passes(self):
        self.assertFalse(looks_non_french("Carte Pokémon Dracaufeu très bon état"))

    def test_empty_still_passes(self):
        self.assertFalse(looks_non_french("", None))
