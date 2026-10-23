"""
Tests de l'appariement des illustrations alternatives.

CE QUI EST VERIFIE ICI
----------------------
Que la mesure REFUSE quand elle ne sait pas. C'est la seule propriete qui
compte : un appariement confiant et faux poserait 500 EUR sur une carte qui
en vaut 5,80, et une marge calculee dessus ne se verrait pas.

Les images sont fabriquees ici meme, et comparees apres redimensionnement
et reencodage — le traitement que la boutique leur fait subir.
"""
import io
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.appariement_variantes import (
    DISTANCE_IDENTIQUE, apparier, distance, empreinte_binaire,
    empreinte_perceptive, pillow_disponible,
)

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def illustration(graine: int, taille=(240, 336)):
    """Une illustration reproductible, differente a chaque graine."""
    alea = random.Random(graine)
    img = Image.new("RGB", taille, (alea.randrange(256), alea.randrange(256),
                                    alea.randrange(256)))
    dessin = ImageDraw.Draw(img)
    for _ in range(14):
        x, y = alea.randrange(taille[0]), alea.randrange(taille[1])
        dessin.rectangle([x, y, x + alea.randrange(90), y + alea.randrange(90)],
                         fill=(alea.randrange(256), alea.randrange(256),
                               alea.randrange(256)))
    return img


def octets(img, format="WEBP", **options) -> bytes:
    tampon = io.BytesIO()
    img.save(tampon, format=format, **options)
    return tampon.getvalue()


def comme_la_boutique(img) -> bytes:
    """Ce que la boutique sert : plus petit, et reencode plus durement."""
    return octets(img.resize((150, 210)), "WEBP", quality=70)


class TestEmpreinteBinaire(unittest.TestCase):
    def test_deux_fichiers_identiques_ont_la_meme_empreinte(self):
        """Le cas le moins cher : si la boutique reheberge le fichier
        officiel tel quel, il n'y a aucune image a comparer."""
        donnees = b"les memes octets"
        self.assertEqual(empreinte_binaire(donnees), empreinte_binaire(donnees))

    def test_un_octet_de_difference_suffit(self):
        self.assertNotEqual(empreinte_binaire(b"image a"),
                            empreinte_binaire(b"image b"))

    def test_rien_a_empreindre(self):
        for vide in (None, b""):
            self.assertIsNone(empreinte_binaire(vide))


class TestDistance(unittest.TestCase):
    def test_une_empreinte_absente_ne_donne_pas_une_distance_de_zero(self):
        """Zero signifierait « identiques ». Une empreinte manquante
        apparierait alors tout avec tout."""
        self.assertIsNone(distance(None, 5))
        self.assertIsNone(distance(5, None))
        self.assertIsNone(distance(None, None))

    def test_compte_les_bits_qui_different(self):
        self.assertEqual(distance(0b1010, 0b1010), 0)
        self.assertEqual(distance(0b1010, 0b1011), 1)
        self.assertEqual(distance(0b0000, 0b1111), 4)


@unittest.skipIf(Image is None, "Pillow absent")
class TestEmpreintePerceptive(unittest.TestCase):
    def test_pillow_est_signale_comme_disponible(self):
        """Sans cette information, un rapport vide se lirait « les images ne
        se ressemblent pas » au lieu de « rien n'a pu etre compare »."""
        self.assertTrue(pillow_disponible())

    def test_la_meme_illustration_survit_au_reencodage(self):
        """LA propriete qui rend la methode utilisable : les deux sources ne
        servent pas le meme fichier, mais la meme illustration."""
        for graine in (1, 2, 3):
            with self.subTest(graine=graine):
                img = illustration(graine)
                ecart = distance(empreinte_perceptive(octets(img)),
                                 empreinte_perceptive(comme_la_boutique(img)))
                self.assertLessEqual(ecart, DISTANCE_IDENTIQUE)

    def test_deux_illustrations_differentes_restent_distinctes(self):
        ecart = distance(empreinte_perceptive(octets(illustration(1))),
                         empreinte_perceptive(octets(illustration(2))))
        self.assertGreater(ecart, DISTANCE_IDENTIQUE)

    def test_une_image_illisible_ne_rend_pas_d_empreinte(self):
        """Une empreinte inventee serait pire que pas d'empreinte : elle
        apparierait."""
        self.assertIsNone(empreinte_perceptive(b"ceci n'est pas une image"))
        self.assertIsNone(empreinte_perceptive(None))


@unittest.skipIf(Image is None, "Pillow absent")
class TestAppariement(unittest.TestCase):
    def setUp(self):
        self.base, self.p1, self.p2 = (illustration(1), illustration(2),
                                       illustration(3))

    def empreintes(self):
        officielles = {0: empreinte_perceptive(octets(self.base)),
                       1: empreinte_perceptive(octets(self.p1)),
                       2: empreinte_perceptive(octets(self.p2))}
        # Volontairement dans le desordre : l'ordre de lecture ne doit
        # jouer aucun role.
        boutique = {"Manga": empreinte_perceptive(comme_la_boutique(self.p2)),
                    "": empreinte_perceptive(comme_la_boutique(self.base)),
                    "Parallèle": empreinte_perceptive(comme_la_boutique(self.p1))}
        return officielles, boutique

    def test_l_appariement_correct_est_trouve(self):
        rapport = apparier(*self.empreintes())
        self.assertTrue(rapport["fiable"], rapport)
        trouve = {c["rang_officiel"]: c["mention"] for c in rapport["couples"]}
        self.assertEqual(trouve, {0: "", 1: "Parallèle", 2: "Manga"})

    def test_des_illustrations_RESSEMBLANTES_rendent_l_appariement_incertain(self):
        """LE risque reel de la methode. Un parallèle est souvent la MEME
        illustration avec un fond different : si les empreintes se
        rapprochent, il ne faut pas trancher avec aplomb.

        La mesure doit alors refuser, pas deviner."""
        self.p1 = self.base.copy()
        self.p2 = self.base.copy()
        rapport = apparier(*self.empreintes())
        self.assertFalse(rapport["fiable"], rapport)
        self.assertEqual(rapport["verdict"], "appariement incertain")

    def test_des_effectifs_differents_ne_s_apparient_pas(self):
        """Deux rangs officiels pour trois mentions : l'un d'eux serait
        apparie de force."""
        officielles, boutique = self.empreintes()
        officielles.pop(2)
        rapport = apparier(officielles, boutique)
        self.assertFalse(rapport["fiable"])
        self.assertIn("effectifs differents", rapport["verdict"])

    def test_une_image_manquante_arrete_tout(self):
        officielles, boutique = self.empreintes()
        officielles[1] = None
        rapport = apparier(officielles, boutique)
        self.assertFalse(rapport["fiable"])
        self.assertEqual(rapport["couples"], [])

    def test_rien_a_comparer(self):
        self.assertFalse(apparier({}, {})["fiable"])
        self.assertFalse(apparier({0: 1}, {})["fiable"])


if __name__ == "__main__":
    unittest.main()
