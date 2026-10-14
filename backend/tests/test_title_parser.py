import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.matching.title_parser import (
    extract_card_codes, extract_set_number, extract_name_candidates,
    extract_variant, normalize,
)


class TestExtractCardCodes(unittest.TestCase):
    def test_code_one_piece_avec_tiret(self):
        self.assertIn("OP01 120", extract_card_codes("Carte One Piece Luffy OP01-120"))

    def test_code_non_padde_complete(self):
        """La source zero-padde ses codes : « OP01 4 » dans une annonce doit
        retrouver « OP01 004 » dans l'index."""
        self.assertIn("OP01 004", extract_card_codes("Carte One Piece Nami OP01-4"))

    def test_code_deja_padde_conserve(self):
        self.assertIn("OP02 013", extract_card_codes("Portgas D. Ace OP02-013 SR"))

    def test_prefixes_de_series(self):
        for titre, attendu in [
            ("Luffy OP01-120 SR", "OP01 120"),
            ("Deck ST01-012", "ST01 012"),
            ("Extra Booster EB01-006", "EB01 006"),
        ]:
            with self.subTest(titre=titre):
                self.assertIn(attendu, extract_card_codes(titre), titre)

    def test_no_code_returns_empty(self):
        self.assertEqual(extract_card_codes("Belle carte One Piece holo"), [])


class TestExtractSetNumber(unittest.TestCase):
    """Le format « X/Y ».

    One Piece ne l'emploie pas : ses cartes sont numerotees « OP01-120 ».
    La fonction reste appelee par le rapprochement, et ces tests la
    couvrent, mais sur One Piece elle ne rend pratiquement jamais rien —
    c'est le code carte qui fait le travail.
    """

    def test_numero_sur_deux_parties(self):
        self.assertEqual(extract_set_number("carte 4/102 serie de base"), ("004", "102"))

    def test_numero_moderne(self):
        self.assertEqual(extract_set_number("carte 232/193"), ("232", "193"))

    def test_espaces_autour_du_slash(self):
        self.assertEqual(extract_set_number("carte 19 / 98 excellent"), ("019", "098"))

    def test_none_when_absent(self):
        self.assertIsNone(extract_set_number("carte One Piece sans numero"))


class TestExtractNameCandidates(unittest.TestCase):
    def test_groupes_avant_mots_isoles(self):
        candidates = extract_name_candidates("Charlotte Katakuri rare")
        self.assertIn("charlotte-katakuri", candidates)
        self.assertLess(
            candidates.index("charlotte-katakuri"), candidates.index("charlotte")
        )

    def test_suffixe_seul_exclu(self):
        """« leader » seul ne doit jamais etre un candidat : sinon toute
        annonce contenant ce mot matcherait n'importe quelle carte Leader."""
        self.assertNotIn("leader", extract_name_candidates("Monkey D. Luffy Leader holo"))

    def test_suffixe_garde_en_fin_de_groupe(self):
        """Mais il doit rester DANS le groupe : un Leader et un Personnage
        du meme nom sont deux cartes differentes."""
        self.assertIn(
            "monkey-d-luffy-leader",
            extract_name_candidates("Carte One Piece Monkey D. Luffy Leader"),
        )

    def test_noise_words_excluded_as_single(self):
        candidates = extract_name_candidates("carte one piece Zoro holo rare")
        self.assertIn("zoro", candidates)
        for bruit in ("carte", "one", "piece", "holo", "rare"):
            self.assertNotIn(bruit, candidates, f"« {bruit} » n'est pas un nom de carte")

    def test_accents_normalized(self):
        self.assertIn("portgas-d-ace", extract_name_candidates("Portgás D. Ace brillante"))

    def test_pure_numbers_excluded_as_single(self):
        self.assertNotIn("120", extract_name_candidates("Luffy OP01-120"))

    def test_empty_input_safe(self):
        self.assertEqual(extract_name_candidates(""), [])


class TestExtractVariant(unittest.TestCase):
    """Le garde-fou « le titre annonce une variante que la carte retenue
    n'a pas ». Tant que le vocabulaire de variantes etait celui d'un autre
    jeu, il ne se declenchait JAMAIS sur One Piece."""

    def test_variantes_du_jeu_reconnues(self):
        for titre, attendu in [
            ("Carte One Piece Monkey D. Luffy Leader", "leader"),
            ("Carte One Piece Zoro parallele", "parallele"),
            ("One Piece Shanks manga rare", "manga"),
            ("One Piece Mihawk alternative", "alternative"),
        ]:
            with self.subTest(titre=titre):
                self.assertEqual(extract_variant(titre), attendu)

    def test_aucune_variante_annoncee(self):
        self.assertIsNone(extract_variant("Carte One Piece Nami OP01-004 neuve"))


class TestNomsOnePiece(unittest.TestCase):
    """Regressions trouvees en construisant le rapprochement sur One Piece.

    Les deux defauts ci-dessous faisaient echouer le rapprochement par nom
    sur les personnages les plus demandes du jeu, en silence : l'annonce
    retombait sur « aucun prix trouve » sans que rien ne signale pourquoi.
    """

    def test_le_nom_du_jeu_ne_pollue_pas_les_candidats(self):
        """« One Piece » figure dans presque toutes les annonces. Tant qu'il
        n'etait pas traite comme du bruit, le meilleur candidat etait
        « one-piece-monkey-luffy », qui ne correspond a aucune carte."""
        candidats = extract_name_candidates("Carte One Piece Monkey D. Luffy neuve")
        self.assertIn("monkey-d-luffy", candidats)
        for c in candidats:
            self.assertFalse(c.startswith("one-"), f"candidat pollue : {c}")
            self.assertFalse(c.startswith("piece-"), f"candidat pollue : {c}")

    def test_l_initiale_est_conservee(self):
        """One Piece utilise constamment l'initiale « D. ». La tokenisation
        jetait les lettres isolees, produisant « monkey-luffy » la ou l'index
        contient « monkey-d-luffy »."""
        for titre, attendu in [
            ("One Piece Monkey D. Luffy", "monkey-d-luffy"),
            ("One Piece Portgas D. Ace SR", "portgas-d-ace"),
            ("One Piece Marshall D. Teach", "marshall-d-teach"),
        ]:
            self.assertIn(attendu, extract_name_candidates(titre), titre)

    def test_l_initiale_ne_forme_pas_un_candidat_a_elle_seule(self):
        """Gardee comme mot, « d » reste du remplissage : aucun candidat ne
        doit commencer ou finir par elle."""
        for c in extract_name_candidates("One Piece Monkey D. Luffy"):
            self.assertNotEqual(c, "d")
            self.assertFalse(c.startswith("d-"), c)
            self.assertFalse(c.endswith("-d"), c)


class TestNormalize(unittest.TestCase):
    def test_accents_and_case(self):
        self.assertEqual(normalize("Romance DAWN"), "romance dawn")

    def test_none_safe(self):
        self.assertEqual(normalize(None), "")


# Ce bloc etait place au MILIEU du fichier : lance directement, unittest
# s'executait avant que les classes suivantes ne soient definies, et leurs
# tests ne tournaient jamais. Invisible en discovery, ou __name__ differe.
if __name__ == "__main__":
    unittest.main()
