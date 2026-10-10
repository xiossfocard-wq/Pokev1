"""
Tests du classement thematique (app/services/card_themes.py).

Ce que ces tests protegent : « donne-moi les cartes par theme » n'a de
valeur que si un theme tient ce qu'il annonce. Un theme « Évoli et ses
evolutions » qui rate Noctali, ou qui ramene Dracaufeu, est pire qu'absent —
l'utilisateur construit une collection en s'y fiant.
"""
import sys, os, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.card_themes import (
    TOUS_LES_THEMES,
    decoder_themes,
    encoder_themes,
    motif_like_pour_theme,
    slugs_connus,
    theme_par_slug,
    themes_de_la_carte,
)


class TestClassementThematique(unittest.TestCase):
    def test_les_accents_ne_changent_pas_le_theme(self):
        """« Évoli » et « Evoli » circulent tous les deux chez les vendeurs
        comme dans les sources."""
        self.assertEqual(
            themes_de_la_carte("Évoli"), themes_de_la_carte("Evoli")
        )
        self.assertIn("evolutions-evoli", themes_de_la_carte("Évoli"))

    def test_toutes_les_evolutions_d_evoli_sont_dans_le_theme(self):
        for nom in ["Évoli", "Aquali", "Voltali", "Pyroli", "Noctali",
                    "Mentali", "Phyllali", "Givrali", "Nymphali"]:
            self.assertIn(
                "evolutions-evoli", themes_de_la_carte(nom),
                f"{nom} manque au theme des evolutions d'Évoli",
            )

    def test_les_noms_anglais_sont_reconnus(self):
        self.assertIn("evolutions-evoli", themes_de_la_carte("Umbreon"))
        self.assertIn("ligne-dracaufeu", themes_de_la_carte("Charizard"))

    def test_la_ligne_de_dracaufeu_est_complete(self):
        for nom in ["Salamèche", "Reptincel", "Dracaufeu"]:
            self.assertIn("ligne-dracaufeu", themes_de_la_carte(nom))

    def test_une_carte_cumule_sujet_et_type(self):
        """Une carte appartient a autant de themes qu'elle en satisfait :
        ce sont deux facons distinctes de chercher la meme carte."""
        themes = themes_de_la_carte("Dracaufeu ex", "Illustration Rare")
        self.assertIn("ligne-dracaufeu", themes)       # sujet
        self.assertIn("illustration-rare", themes)     # type
        self.assertIn("mecanique-ex", themes)          # mecanique

    def test_la_rarete_seule_suffit_pour_un_theme_de_type(self):
        """Selon la serie, l'info est dans le nom ou dans la rarete."""
        themes = themes_de_la_carte("Carte quelconque", "Illustration Rare")
        self.assertIn("illustration-rare", themes)

    def test_un_theme_ne_ramasse_pas_n_importe_quoi(self):
        themes = themes_de_la_carte("Roucool", None)
        self.assertNotIn("evolutions-evoli", themes)
        self.assertNotIn("ligne-dracaufeu", themes)
        self.assertNotIn("legendaires", themes)

    def test_le_classement_se_fait_sur_des_mots_entiers(self):
        """Un nom qui CONTIENT un nom de theme sans etre ce Pokemon ne doit
        pas entrer dans le theme. Sans la contrainte de mot entier, le
        filtre deviendrait du vague a l'oeil."""
        # "pikachute" contient "pikachu" mais n'est pas Pikachu.
        self.assertNotIn("pikachu", themes_de_la_carte("Pikachute"))
        # "mew" ne doit pas s'attraper dans un mot plus long.
        self.assertNotIn("legendaires", themes_de_la_carte("Mewdeleine"))

    def test_raichu_appartient_bien_a_la_famille_de_pikachu(self):
        """Raichu est l'evolution de Pikachu : le theme est une FAMILLE,
        pas un nom exact."""
        themes = themes_de_la_carte("Raichu de Galar")
        self.assertIn("pikachu", themes)

    def test_rayquaza_est_a_la_fois_legendaire_et_dragon(self):
        themes = themes_de_la_carte("Rayquaza VSTAR")
        self.assertIn("legendaires", themes)
        self.assertIn("dragons", themes)
        self.assertIn("mecanique-v", themes)

    def test_nom_vide_ne_casse_rien(self):
        self.assertEqual(themes_de_la_carte("", None), [])
        self.assertEqual(themes_de_la_carte(None, None), [])


class TestEncodageDesThemes(unittest.TestCase):
    """L'encodage avec virgules de bord est ce qui rend le filtre SQL EXACT.
    Sans elles, chercher « ex » ramenerait « mecanique-ex » et inversement."""

    def test_aller_retour(self):
        self.assertEqual(decoder_themes(encoder_themes(["a", "b"])), ["a", "b"])

    def test_liste_vide_reste_filtrable(self):
        # Une seule virgule, pas une chaine vide : la colonne reste non-nulle
        # et le LIKE d'un theme ne peut pas matcher.
        encode = encoder_themes([])
        self.assertEqual(encode, ",")
        self.assertEqual(decoder_themes(encode), [])

    def test_decodage_tolere_le_vide(self):
        self.assertEqual(decoder_themes(None), [])
        self.assertEqual(decoder_themes(""), [])

    def test_le_motif_like_ne_confond_pas_deux_slugs(self):
        """Le point de l'encodage : « mecanique-ex » ne doit pas satisfaire
        le filtre du theme « ex », ni l'inverse."""
        encode = encoder_themes(["mecanique-ex"])
        motif_ex = motif_like_pour_theme("ex").strip("%")
        self.assertNotIn(motif_ex, encode)

        motif_mecanique = motif_like_pour_theme("mecanique-ex").strip("%")
        self.assertIn(motif_mecanique, encode)


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
        self.assertIsNotNone(theme_par_slug("pikachu"))
        self.assertIsNotNone(theme_par_slug("  PIKACHU  "))
        self.assertIsNone(theme_par_slug("theme-inexistant"))

    def test_chaque_theme_attrape_au_moins_une_carte_plausible(self):
        """Garde-fou contre un theme dont les motifs seraient casses : il
        passerait inapercu, en se contentant de ne jamais rien rendre."""
        exemples = {
            "pikachu": ("Pikachu", None),
            "ligne-dracaufeu": ("Dracaufeu", None),
            "evolutions-evoli": ("Noctali", None),
            "starters-kanto": ("Tortank", None),
            "oiseaux-legendaires": ("Sulfura", None),
            "legendaires": ("Lugia", None),
            "dragons": ("Dracolosse", None),
            "spectres": ("Ectoplasma", None),
            "chouchous": ("Ronflex", None),
            "illustration-rare": ("Carte", "Illustration Rare"),
            "secret-rare": ("Carte", "Special Illustration Rare"),
            "full-art": ("Carte", "Full Art"),
            "gold-rainbow": ("Carte", "Hyper Rare"),
            "mecanique-ex": ("Mew ex", None),
            "mecanique-v": ("Zacian V", None),
            "mecanique-gx": ("Pikachu GX", None),
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
