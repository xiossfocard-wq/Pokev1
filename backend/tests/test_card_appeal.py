"""
Tests du signal d'attrait One Piece (app/scoring/card_appeal.py).

Trois signaux independants de l'etat physique : la rarete, le caractere
precoce de l'edition, et la popularite du personnage. Ils donnent un bonus
plafonne au score final — un faux negatif ne fait pas disparaitre l'annonce,
il la prive juste du bonus.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scoring.card_appeal import detect_card_appeal


class TestRarete(unittest.TestCase):
    def test_manga_rare_est_le_palier_le_plus_haut(self):
        r = detect_card_appeal("Monkey D. Luffy OP01-120 Manga Rare")
        self.assertEqual(r["rarity_tier"], "Manga Rare")
        self.assertGreaterEqual(r["appeal_bonus"], 30)

    def test_secret_rare_reconnue_en_toutes_lettres_et_en_sigle(self):
        for titre in ["Shanks Secret Rare", "Shanks SEC"]:
            self.assertEqual(detect_card_appeal(titre)["rarity_tier"], "Secret Rare", titre)

    def test_alternative_reconnue_sous_ses_graphies(self):
        for titre in ["Zoro alt art", "Zoro alternative art", "Zoro parallele"]:
            self.assertEqual(detect_card_appeal(titre)["rarity_tier"], "Alternative", titre)

    def test_super_rare_reconnue(self):
        for titre in ["Nami Super Rare", "Nami SR"]:
            self.assertEqual(detect_card_appeal(titre)["rarity_tier"], "Super Rare", titre)

    def test_la_plus_rare_l_emporte_quand_plusieurs_mentions(self):
        """Un titre qui annonce « SR Manga Rare » doit etre classe au palier
        le plus haut, pas au premier rencontre dans le texte."""
        r = detect_card_appeal("Luffy SR Manga Rare alt art")
        self.assertEqual(r["rarity_tier"], "Manga Rare")

    def test_aucune_rarete_annoncee(self):
        r = detect_card_appeal("Carte One Piece sans precision")
        self.assertIsNone(r["rarity_tier"])


class TestEditionPrecoce(unittest.TestCase):
    """Le champ garde le nom `is_vintage` pour ne pas casser le schema, mais
    il faut le lire comme « edition precoce » : le jeu date de 2022."""

    def test_romance_dawn_est_precoce(self):
        for titre in ["Carte Romance Dawn", "Luffy OP-01", "Luffy OP01-120"]:
            self.assertTrue(detect_card_appeal(titre)["is_vintage"], titre)

    def test_premiere_edition_est_precoce(self):
        self.assertTrue(detect_card_appeal("Zoro 1ère édition")["is_vintage"])

    def test_une_serie_recente_ne_l_est_pas(self):
        self.assertFalse(detect_card_appeal("Carte OP-09 Emperors in the New World")["is_vintage"])


class TestPopularite(unittest.TestCase):
    def test_les_personnages_phares_sont_reconnus(self):
        for nom in ["Luffy", "Zoro", "Trafalgar Law", "Shanks", "Mihawk", "Portgas D. Ace"]:
            self.assertTrue(detect_card_appeal(f"Carte {nom} OP01")["is_popular_pokemon"], nom)

    def test_les_graphies_francaises_anciennes_comptent(self):
        self.assertTrue(detect_card_appeal("Carte Zorro")["is_popular_pokemon"])

    def test_un_personnage_secondaire_ne_declenche_rien(self):
        r = detect_card_appeal("Carte One Piece personnage obscur")
        self.assertFalse(r["is_popular_pokemon"])
        self.assertIsNone(r["popular_pokemon_matched"])

    def test_le_personnage_reconnu_est_rendu(self):
        r = detect_card_appeal("Monkey D. Luffy Leader")
        self.assertEqual(r["popular_pokemon_matched"], "luffy")


class TestBonus(unittest.TestCase):
    def test_le_bonus_est_plafonne(self):
        """Il ne doit jamais ecraser marge et qualite dans le score final."""
        r = detect_card_appeal("Monkey D. Luffy Manga Rare Romance Dawn OP-01 1ère édition")
        self.assertLessEqual(r["appeal_bonus"], 30)

    def test_les_signaux_s_additionnent(self):
        seul = detect_card_appeal("Carte Super Rare")["appeal_bonus"]
        cumule = detect_card_appeal("Luffy Super Rare Romance Dawn")["appeal_bonus"]
        self.assertGreater(cumule, seul)

    def test_titre_vide_ne_casse_rien(self):
        r = detect_card_appeal("", "")
        self.assertEqual(r["appeal_bonus"], 0)
        self.assertIsNone(r["rarity_tier"])


if __name__ == "__main__":
    unittest.main()
