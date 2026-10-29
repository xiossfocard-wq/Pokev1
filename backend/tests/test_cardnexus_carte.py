"""
Rapprocher une fiche de son impression CardNexus, d'apres les reponses
reelles de l'API (Shanks OP01-120 : originale, promo, manga d'un coffret).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import MarketCardPrice
from app.services import cardnexus_carte
from app.services.cardnexus_carte import avis_cardnexus, choisir_produit

ORIGINALE = {"id": 12653, "name": "Shanks", "nameSlug": "shanks", "productType": "card",
             "expansion": {"name": "Romance Dawn", "code": "OP01"}, "printNumber": "OP01-120"}
PROMO = {"id": 12172, "name": "Shanks (Championship 2023) [Serial Number]", "productType": "card",
         "nameSlug": "shanks-championship-2023-serial-number", "expansion": {"name": "Promo", "code": "OP-PR"}}
MANGA = {"id": 12161, "name": "Shanks (Manga)", "nameSlug": "shanks-manga", "variant": "Manga", "productType": "card",
         "expansion": {"name": "Premium Booster -The Best-", "code": "PRB-01"}}
PARALLELE = {"id": 9, "name": "Shanks (Parallel)", "nameSlug": "shanks-parallel", "variant": "Parallel",
             "productType": "card", "expansion": {"name": "Romance Dawn", "code": "OP01"}}
TOUS = [PROMO, MANGA, PARALLELE, ORIGINALE]


def carte(slug="shanks", langue="fr"):
    return MarketCardPrice(id=1, card_code="OP01-120", name_slug=slug, display_name="Shanks", language=langue)


class FauxClient:
    configure = True

    def __init__(self):
        self.appels = 0

    def chercher(self, **filtres):
        self.appels += 1
        return 200, {"data": TOUS}

    def prix(self, pid):
        self.appels += 1
        return 200, {"productId": pid, "pricesByFinish": {"Foil": {"cardnexus": {"regions": {"eu": {
            "low": 4.33, "listingCount": 3, "byCondition": {
                "NM": {"low": 4.33, "byLanguage": {"ja": {"low": 4.33, "listingCount": 2},
                                                   "fr": {"low": 9.5, "listingCount": 1}}}}}}}}}}

    def ventes(self, pid):
        self.appels += 1
        return 200, {"data": [{"soldAt": "2026-10-20", "price": {"amount": 8.0}},
                              {"soldAt": "2026-10-21", "price": {"amount": 10.0}}],
                     "pagination": {"nextCursor": None}}


class TestChoix(unittest.TestCase):
    def test_chaque_version_trouve_son_impression(self):
        self.assertEqual(choisir_produit(TOUS, carte())["id"], 12653)
        self.assertEqual(choisir_produit(TOUS, carte("shanks-parallele-1"))["id"], 9)
        self.assertEqual(choisir_produit(TOUS, carte("shanks-parallele-2"))["id"], 12161)

    def test_jamais_une_promo_a_la_place(self):
        self.assertIsNone(choisir_produit([PROMO], carte()))


class TestAvis(unittest.TestCase):
    def setUp(self):
        cardnexus_carte._cache.clear()

    def test_prix_europe_dans_la_langue_et_ventes(self):
        avis = avis_cardnexus(carte(), FauxClient())
        self.assertEqual(avis["europe"]["plus_bas"], 4.33)
        self.assertEqual((avis["europe"]["plus_bas_langue"], avis["europe"]["annonces_langue"]), (9.5, 1))
        self.assertEqual((avis["ventes_30j"], avis["ventes_mediane"]), (2, 9.0))
        self.assertEqual(avis["url"], "https://cardnexus.com/fr/explore/onepiece/romance-dawn/card/shanks-12653")

    def test_une_heure_de_cache(self):
        client = FauxClient()
        avis_cardnexus(carte(), client)
        avis_cardnexus(carte(), client)
        self.assertEqual(client.appels, 3)

    def test_sans_cle(self):
        class SansCle:
            configure = False
        self.assertEqual(avis_cardnexus(carte(), SansCle()), {"configure": False})


if __name__ == "__main__":
    unittest.main()
