"""
Tests de la route /api/admin/diagnostic-variantes.

LE DEFAUT QUI A MOTIVE CES TESTS
--------------------------------
La route n'avait aucun test, et elle est devenue aveugle sans que rien ne le
signale. Elle ne retenait que l'impression ordinaire et les mentions encore
inconnues. Tant qu'aucune mention n'avait de rang, ça revenait au meme. Mais
des que « Parallele » a recu le rang 1, pour un code « ordinaire +
Parallele + Super Leader Parallele » elle ne comparait plus que deux
impressions aux trois fiches officielles, concluait « effectifs
differents », et ne pouvait donc JAMAIS mesurer la mention qui restait a
etablir — precisement celle pour laquelle elle existe.

Tout est simule ici : la source des prix, les telechargements, la base. Les
images, elles, sont de vraies images, comparees apres reencodage.
"""
import io
import os
import random
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.collectors.opecards_prices import (
    VARIANTE_SANS_RANG, PrixCarte, rang_de_version, marqueur_de_variante,
)
from app.database import Base
from app.models import MarketCardPrice
from app.routers import admin

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None


def illustration(graine: int):
    alea = random.Random(graine)
    img = Image.new("RGB", (240, 336), (alea.randrange(256), alea.randrange(256),
                                        alea.randrange(256)))
    dessin = ImageDraw.Draw(img)
    for _ in range(14):
        x, y = alea.randrange(240), alea.randrange(336)
        dessin.rectangle([x, y, x + alea.randrange(90), y + alea.randrange(90)],
                         fill=(alea.randrange(256), alea.randrange(256),
                               alea.randrange(256)))
    return img


def octets(img, taille=None, qualite=90) -> bytes:
    if taille:
        img = img.resize(taille)
    tampon = io.BytesIO()
    img.save(tampon, format="WEBP", quality=qualite)
    return tampon.getvalue()


def candidature(code, nom_affiche, image_url):
    nom, rang = rang_de_version(nom_affiche)
    return PrixCarte(card_code=f"{code}-L", display_name=nom, rang_variante=rang,
                     rarity="L", price_eur=1.0, variation_eur=None,
                     image_url=image_url, detail_url=None,
                     variante=marqueur_de_variante(nom_affiche))


@unittest.skipIf(Image is None, "Pillow absent")
class TestDiagnosticVariantes(unittest.TestCase):
    def setUp(self):
        moteur = create_engine("sqlite://", poolclass=StaticPool,
                               connect_args={"check_same_thread": False})
        Base.metadata.create_all(moteur)
        self.Session = sessionmaker(bind=moteur)

        # Trois illustrations distinctes, et ce que chaque source en sert :
        # l'officiel en pleine taille, la boutique reduite et reencodee.
        self.images = {}
        db = self.Session()
        for rang, (slug, graine) in enumerate((("monkey-d-luffy", 1),
                                               ("monkey-d-luffy-parallele-1", 2),
                                               ("monkey-d-luffy-parallele-2", 3))):
            officielle = f"https://officiel.test/OP17-079_{rang}.webp"
            self.images[officielle] = octets(illustration(graine))
            self.images[f"https://boutique.test/OP17-079_{rang}.webp"] = octets(
                illustration(graine), taille=(150, 210), qualite=70)
            db.add(MarketCardPrice(card_code="OP17-079", name_slug=slug,
                                   display_name="Monkey D. Luffy", rarity="L",
                                   image_url=officielle))
        # Un second code dont toutes les mentions ont DEJA un rang.
        for rang, (slug, graine) in enumerate((("shanks", 4),
                                               ("shanks-parallele-1", 5))):
            officielle = f"https://officiel.test/OP17-022_{rang}.webp"
            self.images[officielle] = octets(illustration(graine))
            self.images[f"https://boutique.test/OP17-022_{rang}.webp"] = octets(
                illustration(graine), taille=(150, 210), qualite=70)
            db.add(MarketCardPrice(card_code="OP17-022", name_slug=slug,
                                   display_name="Shanks", rarity="SR",
                                   image_url=officielle))
        db.commit()
        db.close()

        # La boutique, telle que relevee sur OP17 le 23/10/2026.
        self.releve = [
            candidature("OP17-079", "Monkey D. Luffy",
                        "https://boutique.test/OP17-079_0.webp"),
            candidature("OP17-079", "Monkey D. Luffy (Parallèle)",
                        "https://boutique.test/OP17-079_1.webp"),
            candidature("OP17-079", "Monkey D. Luffy (Super Leader Parallèle)",
                        "https://boutique.test/OP17-079_2.webp"),
            candidature("OP17-022", "Shanks",
                        "https://boutique.test/OP17-022_0.webp"),
            candidature("OP17-022", "Shanks (Parallèle)",
                        "https://boutique.test/OP17-022_1.webp"),
        ]

    def lancer(self, **parametres):
        client = mock.Mock()
        client.prix_de_serie.return_value = self.releve
        with mock.patch.object(admin, "SessionLocal", self.Session), \
             mock.patch.object(admin, "ClientOPECards", return_value=client), \
             mock.patch.object(admin, "_telecharger",
                               side_effect=lambda session, url, **k: self.images.get(url)):
            return admin.diagnostic_variantes(series="819", limite=10,
                                              toutes=parametres.get("toutes", False))

    def test_la_mention_inconnue_est_bien_mesuree(self):
        """LE test : avant correction, ce code rendait « effectifs
        differents » et la mention restait a jamais sans rang."""
        rapport = self.lancer()
        luffy = next(r for r in rapport["rapports"] if r["code"] == "OP17-079")
        self.assertTrue(luffy["fiable"], luffy)
        couples = {c["mention"]: c["rang_officiel"] for c in luffy["couples"]}
        self.assertEqual(couples["Super Leader Parallèle"], 2)

    def test_les_mentions_deja_rangees_restent_dans_la_comparaison(self):
        """Ecarter « Parallele » sous pretexte qu'il a deja un rang
        desequilibrait les effectifs : trois fiches contre deux mentions."""
        rapport = self.lancer()
        luffy = next(r for r in rapport["rapports"] if r["code"] == "OP17-079")
        self.assertEqual(sorted(luffy["mentions"]),
                         ["", "Parallèle", "Super Leader Parallèle"])
        self.assertEqual(luffy["rangs_officiels"], [0, 1, 2])

    def test_par_defaut_seuls_les_codes_a_apprendre_sont_examines(self):
        """Comparer des images coute des telechargements : on ne le fait que
        la ou il reste quelque chose a etablir."""
        codes = [r["code"] for r in self.lancer()["rapports"]]
        self.assertEqual(codes, ["OP17-079"])

    def test_toutes_reexamine_aussi_les_mentions_connues(self):
        """Pour verifier qu'un rang deja attribue tient toujours."""
        codes = sorted(r["code"] for r in self.lancer(toutes=True)["rapports"])
        self.assertEqual(codes, ["OP17-022", "OP17-079"])

    def test_la_route_n_ecrit_rien(self):
        avant = [(l.card_code, l.name_slug, l.price_eur, l.image_url)
                 for l in self.Session().query(MarketCardPrice).all()]
        self.lancer(toutes=True)
        apres = [(l.card_code, l.name_slug, l.price_eur, l.image_url)
                 for l in self.Session().query(MarketCardPrice).all()]
        self.assertEqual(avant, apres)


if __name__ == "__main__":
    unittest.main()
