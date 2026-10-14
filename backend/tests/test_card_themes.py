"""
Tests du classement thematique One Piece (app/services/card_themes.py).

Ce que ces tests protegent : « donne-moi les cartes par theme » n'a de
valeur que si un theme tient ce qu'il annonce. Un theme « Chapeau de
Paille » qui rate Nico Robin, ou qui ramene Kaido, est pire qu'absent —
l'utilisateur construit une collection en s'y fiant.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.card_themes import (
    TOUS_LES_THEMES,
    cle_de_recherche,
    decoder_themes,
    encoder_themes,
    motif_like_pour_theme,
    slugs_connus,
    theme_par_slug,
    themes_de_la_carte,
)


class TestClassementThematique(unittest.TestCase):
    def test_les_accents_ne_changent_pas_le_theme(self):
        """« Portgás D. Ace » et « Portgas D. Ace » circulent tous les deux
        chez les vendeurs comme dans les sources."""
        self.assertEqual(
            themes_de_la_carte("Portgás D. Ace"), themes_de_la_carte("Portgas D. Ace")
        )
        self.assertIn("barbe-blanche", themes_de_la_carte("Portgás D. Ace"))

    def test_tout_l_equipage_du_chapeau_de_paille_est_reconnu(self):
        for nom in ["Monkey D. Luffy", "Roronoa Zoro", "Nami", "Usopp", "Sanji",
                    "Tony Tony Chopper", "Nico Robin", "Franky", "Brook", "Jinbe"]:
            self.assertIn(
                "chapeau-de-paille", themes_de_la_carte(nom),
                f"{nom} manque a l'equipage du Chapeau de Paille",
            )

    def test_les_graphies_francaises_anciennes_sont_reconnues(self):
        """Les anciennes traductions circulent encore chez les vendeurs."""
        self.assertIn("chapeau-de-paille", themes_de_la_carte("Zorro"))
        self.assertIn("chapeau-de-paille", themes_de_la_carte("Pipo"))
        self.assertIn("grands-corsaires", themes_de_la_carte("Baggy le Clown"))

    def test_une_carte_cumule_sujet_et_type(self):
        """Une carte appartient a autant de themes qu'elle en satisfait :
        ce sont des facons distinctes de chercher la meme carte."""
        themes = themes_de_la_carte("Monkey D. Luffy", "Secret Rare")
        self.assertIn("chapeau-de-paille", themes)     # equipage
        self.assertIn("pires-generations", themes)     # groupe
        self.assertIn("secret-rare", themes)           # traitement

    def test_un_personnage_peut_appartenir_a_deux_equipages(self):
        """Doflamingo est a la fois Grand Corsaire et chef de sa famille :
        le recouvrement est voulu, pas un defaut."""
        themes = themes_de_la_carte("Donquixote Doflamingo")
        self.assertIn("grands-corsaires", themes)
        self.assertIn("donquixote", themes)

    def test_la_rarete_seule_suffit_pour_un_theme_de_type(self):
        """Selon la source, l'info est dans le nom ou dans la rarete."""
        self.assertIn("secret-rare", themes_de_la_carte("Carte quelconque", "Secret Rare"))
        self.assertIn("super-rare", themes_de_la_carte("Carte quelconque", "SR"))
        self.assertIn("leader", themes_de_la_carte("Carte quelconque", "Leader"))

    def test_les_sigles_du_jeu_sont_lus_comme_des_mots_entiers(self):
        """« SEC » et « SR » sont des raretes, mais ne doivent pas mordre
        dans un nom de personnage qui les contiendrait."""
        self.assertIn("secret-rare", themes_de_la_carte("X", "SEC"))
        self.assertNotIn("secret-rare", themes_de_la_carte("Secretaire", None))
        self.assertNotIn("super-rare", themes_de_la_carte("Sranka", None))

    def test_un_theme_ne_ramasse_pas_n_importe_quoi(self):
        themes = themes_de_la_carte("Personnage inconnu", None)
        self.assertNotIn("chapeau-de-paille", themes)
        self.assertNotIn("marine", themes)
        self.assertNotIn("cent-betes", themes)

    def test_le_classement_se_fait_sur_des_mots_entiers(self):
        """Un nom qui CONTIENT un nom de personnage sans etre ce personnage
        ne doit pas entrer dans le theme."""
        self.assertNotIn("chapeau-de-paille", themes_de_la_carte("Namibie"))
        self.assertNotIn("equipage-kid", themes_de_la_carte("Kidnappeur"))

    def test_les_amiraux_sont_dans_la_marine(self):
        for nom in ["Sakazuki", "Akainu", "Kuzan", "Aokiji", "Borsalino",
                    "Kizaru", "Monkey D. Garp", "Sengoku"]:
            self.assertIn("marine", themes_de_la_carte(nom), f"{nom} hors Marine")

    def test_nom_vide_ne_casse_rien(self):
        self.assertEqual(themes_de_la_carte("", None), [])
        self.assertEqual(themes_de_la_carte(None, None), [])


class TestCleDeRecherche(unittest.TestCase):
    """La recherche doit rester insensible a la casse et aux accents : le
    `lower()` de SQLite ne traite que l'ASCII, et personne ne tape les
    accents."""

    def test_normalisation(self):
        self.assertEqual(cle_de_recherche("Portgás D. Ace", "OP02-013"),
                         "portgas d. ace op02-013")

    def test_les_graphies_convergent(self):
        self.assertEqual(cle_de_recherche("PORTGÁS"), cle_de_recherche("portgas"))

    def test_les_espaces_multiples_sont_reduits(self):
        self.assertEqual(cle_de_recherche("  Monkey   D.  Luffy  "), "monkey d. luffy")

    def test_sans_code(self):
        self.assertEqual(cle_de_recherche("Shanks"), "shanks")


class TestEncodageDesThemes(unittest.TestCase):
    """L'encodage avec virgules de bord est ce qui rend le filtre SQL EXACT."""

    def test_aller_retour(self):
        self.assertEqual(decoder_themes(encoder_themes(["a", "b"])), ["a", "b"])

    def test_liste_vide_reste_filtrable(self):
        encode = encoder_themes([])
        self.assertEqual(encode, ",")
        self.assertEqual(decoder_themes(encode), [])

    def test_decodage_tolere_le_vide(self):
        self.assertEqual(decoder_themes(None), [])
        self.assertEqual(decoder_themes(""), [])

    def test_le_motif_like_ne_confond_pas_deux_slugs(self):
        """« equipage-kid » ne doit pas satisfaire le filtre du theme
        « kid », ni l'inverse."""
        encode = encoder_themes(["equipage-kid"])
        self.assertNotIn(motif_like_pour_theme("kid").strip("%"), encode)
        self.assertIn(motif_like_pour_theme("equipage-kid").strip("%"), encode)


class TestCatalogueDesThemes(unittest.TestCase):
    def test_les_slugs_sont_uniques(self):
        slugs = slugs_connus()
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_chaque_theme_est_decrit(self):
        """Un theme sans libelle ni description n'est pas choisissable dans
        une interface."""
        for theme in TOUS_LES_THEMES:
            self.assertTrue(theme.label, f"{theme.slug} sans libelle")
            self.assertTrue(theme.description, f"{theme.slug} sans description")
            self.assertIn(theme.famille, ("sujet", "type"))

    def test_recherche_par_slug(self):
        self.assertIsNotNone(theme_par_slug("chapeau-de-paille"))
        self.assertIsNotNone(theme_par_slug("  CHAPEAU-DE-PAILLE  "))
        self.assertIsNone(theme_par_slug("theme-inexistant"))

    def test_chaque_theme_attrape_au_moins_une_carte_plausible(self):
        """Garde-fou contre un theme dont les motifs seraient casses : il
        passerait inapercu, en se contentant de ne jamais rien rendre."""
        exemples = {
            "chapeau-de-paille": ("Monkey D. Luffy", None),
            "pires-generations": ("Basil Hawkins", None),
            "equipage-heart": ("Trafalgar Law", None),
            "equipage-kid": ("Eustass Kid", None),
            "equipage-roux": ("Shanks", None),
            "cent-betes": ("Kaido", None),
            "big-mom": ("Charlotte Katakuri", None),
            "barbe-blanche": ("Edward Newgate", None),
            "barbe-noire": ("Marshall D. Teach", None),
            "marine": ("Smoker", None),
            "grands-corsaires": ("Dracule Mihawk", None),
            "revolutionnaires": ("Sabo", None),
            "donquixote": ("Trebol", None),
            "secret-rare": ("Carte", "Secret Rare"),
            "super-rare": ("Carte", "Super Rare"),
            "manga-rare": ("Carte", "Manga Rare"),
            "alternative": ("Carte", "Alternative Art"),
            "leader": ("Carte", "Leader"),
            "promo": ("Carte", "Promo"),
        }
        self.assertEqual(
            set(exemples), set(slugs_connus()),
            "un theme a ete ajoute ou renomme sans exemple dans ce test",
        )
        for slug, (nom, rarete) in exemples.items():
            self.assertIn(
                slug, themes_de_la_carte(nom, rarete),
                f"le theme {slug} ne reconnait meme pas {nom!r}",
            )


if __name__ == "__main__":
    unittest.main()
