"""
Le diagnostic de la page d'une annonce Vinted.

Il sert a decouvrir OU la page donne les avis du vendeur et la description,
avant d'ecrire le moindre code qui les lirait : la page de recherche ne les
contient pas, et le format de la page d'annonce n'a jamais ete verifie.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException

from app.collectors.vinted_scraper import VintedScraper
from app.routers.admin import debug_vinted_annonce

PAGE = """<html><head>
<meta property="og:description" content="Shanks OP01-120 sortie de booster">
<script type="application/ld+json">{"@type": "Product", "name": "Shanks OP01-120",
 "description": "Carte sortie de booster, jamais jouée", "offers": {"price": "9.00"}}</script>
</head><body><script>self.__next_f.push([1, "{\\"user\\":{\\"feedback_count\\":42,\\"feedback_reputation\\":0.98}}"])</script>
</body></html>"""


class TestDiagnosticAnnonce(unittest.TestCase):
    def diagnostic(self, page=PAGE, reponse=True):
        scraper = VintedScraper(request_delay_seconds=0)
        faux = mock.Mock(text=page, status_code=200) if reponse else None
        with mock.patch.object(scraper, "_get", return_value=faux):
            return scraper.diagnostic_annonce("https://www.vinted.fr/items/123-shanks")

    def test_les_reperes_et_le_ld_json_sont_releves(self):
        d = self.diagnostic()
        self.assertTrue(d["ok"])
        self.assertEqual(d["reperes"]["feedback_count"]["occurrences"], 1)
        self.assertIn("feedback_count", d["reperes"]["feedback_count"]["extraits"][0])
        self.assertEqual(d["ld_json"][0]["description"], "Carte sortie de booster, jamais jouée")

    def test_seuls_de_courts_extraits_sont_rendus(self):
        d = self.diagnostic(page="x" * 100_000 + '"feedback_count":3' + "y" * 100_000)
        extrait = d["reperes"]["feedback_count"]["extraits"][0]
        self.assertLess(len(extrait), 500)

    def test_une_page_injoignable_dit_pourquoi(self):
        d = self.diagnostic(reponse=False)
        self.assertFalse(d["ok"])
        self.assertIn("raison", d)

    def test_la_route_ne_lit_que_des_annonces_vinted(self):
        for url in ("https://exemple.com/items/1", "http://www.vinted.fr/items/1",
                    "https://www.vinted.fr/catalog?search_text=x"):
            with self.subTest(url=url):
                with self.assertRaises(HTTPException) as e:
                    debug_vinted_annonce(url)
                self.assertEqual(e.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
