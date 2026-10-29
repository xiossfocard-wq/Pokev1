"""
CardNexus : la cle est envoyee comme il faut, et ne ressort jamais — ni
dans le diagnostic, ni dans un message d'erreur.
"""
import os
import sys
import unittest

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.collectors.cardnexus import ClientCardNexus, ErreurCardNexus, abreger

CLE = "cnk_live_secret123"


class FausseReponse:
    def __init__(self, statut, contenu):
        self.status_code, self._contenu = statut, contenu
        self.text = str(contenu)

    def json(self):
        if isinstance(self._contenu, str):
            raise ValueError("pas du JSON")
        return self._contenu


class FausseSession:
    """Rejoue des reponses selon le chemin, et garde les requetes."""
    def __init__(self, reponses, erreur=None):
        self.reponses, self.erreur, self.requetes = reponses, erreur, []

    def request(self, methode, url, json=None, timeout=None, headers=None):
        self.requetes.append({"methode": methode, "url": url, "corps": json, "headers": headers})
        if self.erreur:
            raise self.erreur
        chemin = url.split("public-api.cardnexus.com", 1)[1]
        cle = (chemin, (json or {}).get("printNumber") or (json or {}).get("name"))
        return self.reponses.get(cle) or self.reponses.get((chemin, None)) or FausseReponse(404, {"error": "?"})


class TestClient(unittest.TestCase):
    def test_sans_cle_rien_n_est_appele(self):
        session = FausseSession({})
        client = ClientCardNexus(cle="  ", session=session)
        self.assertFalse(client.diagnostic("OP01-120", "Shanks")["cle_configuree"])
        with self.assertRaises(ErreurCardNexus):
            client.chercher(name="Shanks")
        self.assertEqual(session.requetes, [])

    def test_la_cle_part_en_bearer(self):
        session = FausseSession({("/v1/products/search", "Shanks"): FausseReponse(200, {"data": []})})
        ClientCardNexus(cle=f" {CLE}\n", session=session).chercher(name="Shanks", limit=5)
        r = session.requetes[0]
        self.assertEqual((r["methode"], r["url"]), ("POST", "https://public-api.cardnexus.com/v1/products/search"))
        self.assertEqual(r["headers"]["Authorization"], f"Bearer {CLE}")
        self.assertEqual(r["corps"], {"name": "Shanks", "limit": 5})

    def test_le_diagnostic_suit_le_premier_produit(self):
        session = FausseSession({
            ("/v1/products/search", "OP01-120"): FausseReponse(200, {"data": [{"id": "p42", "name": "Shanks"}]}),
            ("/v1/products/search", "Shanks"): FausseReponse(200, {"data": [{"id": "p7"}]}),
            ("/v1/products/p42/prices", None): FausseReponse(200, {"pricesByFinish": {"Standard": {}}}),
            ("/v1/products/p42/sales", None): FausseReponse(200, {"data": []}),
        })
        resultat = ClientCardNexus(cle=CLE, session=session).diagnostic("OP01-120", "Shanks")
        self.assertEqual(resultat["premier_produit"], "p42")
        self.assertEqual([(e["etape"], e["statut"]) for e in resultat["etapes"]], [
            ("recherche par code", 200), ("recherche par nom", 200),
            ("prix du premier produit", 200), ("ventes du premier produit", 200)])

    def test_la_cle_ne_ressort_jamais(self):
        # Une API qui renverrait la cle dans son message d'erreur.
        session = FausseSession({("/v1/products/search", None): FausseReponse(401, {"error": f"bad key {CLE}"})})
        resultat = ClientCardNexus(cle=CLE, session=session).diagnostic("OP01-120", "Shanks")
        self.assertNotIn(CLE, str(resultat))
        self.assertEqual(resultat["etapes"][0]["statut"], 401)
        self.assertIsNone(resultat["premier_produit"])

    def test_injoignable_sans_divulguer_la_requete(self):
        erreur = requests.ConnectionError(f"Authorization: Bearer {CLE}")
        client = ClientCardNexus(cle=CLE, session=FausseSession({}, erreur=erreur))
        with self.assertRaises(ErreurCardNexus) as e:
            client.prix("p1")
        self.assertNotIn(CLE, str(e.exception))
        self.assertNotIn(CLE, str(client.diagnostic("OP01-120", "Shanks")))


class TestAbreger(unittest.TestCase):
    def test_la_forme_sans_le_volume(self):
        self.assertEqual(abreger({"data": list(range(10)), "t": "x" * 400})["data"], [0, 1, 2, "… 7 de plus"])
        self.assertEqual(len(abreger("x" * 400)), 301)


if __name__ == "__main__":
    unittest.main()
