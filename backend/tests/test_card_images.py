import sys, os, unittest
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from app.collectors import card_images
from app.collectors.card_images import (
    ClientImagesCartes, code_canonique, urls_candidates,
)

BASE_TEST = "https://exemple.test/cardlist/card"


def _reglages(base=BASE_TEST, verifier=True):
    """Pointe le collecteur sur une base de test, le temps d'un test.

    On ne tape jamais l'hote reel depuis la suite : un test qui depend du
    reseau echoue pour des raisons qui n'ont rien a voir avec le code.
    """
    return mock.patch.multiple(
        card_images.settings,
        card_image_base_url=base,
        card_image_verify=verifier,
    )


class ReponseFactice:
    def __init__(self, status_code=200, content_type="image/png"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type} if content_type else {}
        self.ferme = False

    def close(self):
        self.ferme = True


class SessionFactice:
    """Session qui rejoue des reponses par URL, et enregistre les appels.

    `reponses` associe une URL a une reponse (ou a une exception a lever).
    Toute URL absente rend un 404 : c'est le comportement d'un hote qui ne
    connait pas la carte, donc le cas le plus courant.
    """

    def __init__(self, reponses=None, refuse_head=False):
        self.reponses = reponses or {}
        self.refuse_head = refuse_head
        self.appels = []
        self.headers = {}

    def _repondre(self, url, methode):
        self.appels.append((methode, url))
        if methode == "head" and self.refuse_head:
            return ReponseFactice(405, "text/html")
        valeur = self.reponses.get(url)
        if isinstance(valeur, Exception):
            raise valeur
        if valeur is None:
            return ReponseFactice(404, "text/html")
        return valeur

    def head(self, url, **kwargs):
        return self._repondre(url, "head")

    def get(self, url, **kwargs):
        return self._repondre(url, "get")


def _client(session, **kw):
    # min_delay=0 : la politesse reseau n'a pas a ralentir la suite.
    return ClientImagesCartes(session=session, min_delay=0.0, **kw)


class TestCodeCanonique(unittest.TestCase):
    """Le code de carte est la CLE de l'illustration : s'il est mal
    normalise, on construit une adresse qui ne mene nulle part."""

    def test_formes_equivalentes(self):
        for brut in ("OP01-120", "OP01 120", "op01-120", "op01120",
                     " OP01_120 ", "OP01.120"):
            with self.subTest(brut=brut):
                self.assertEqual(code_canonique(brut), "OP01-120")

    def test_numero_complete_a_trois_chiffres(self):
        """La liste officielle ecrit OP01-001, une source peut ecrire
        OP01-1 : c'est la meme carte."""
        self.assertEqual(code_canonique("OP01-1"), "OP01-001")
        self.assertEqual(code_canonique("OP01-01"), "OP01-001")

    def test_autres_prefixes_du_jeu(self):
        self.assertEqual(code_canonique("ST01-001"), "ST01-001")
        self.assertEqual(code_canonique("EB01-012"), "EB01-012")
        self.assertEqual(code_canonique("PRB01-001"), "PRB01-001")

    def test_promo_sans_numero_de_serie(self):
        """« P-001 » : prefixe purement alphabetique."""
        self.assertEqual(code_canonique("P-001"), "P-001")

    def test_rien_a_exploiter_rend_none(self):
        """Mieux vaut aucune image qu'une adresse inventee."""
        for brut in (None, "", "   ", "Monkey D. Luffy", "???", "1234"):
            with self.subTest(brut=brut):
                self.assertIsNone(code_canonique(brut))


class TestUrlsCandidates(unittest.TestCase):
    def test_illustration_de_base_en_premier(self):
        with _reglages():
            urls = urls_candidates("OP01-120", "Monkey D. Luffy")
        self.assertEqual(urls[0], f"{BASE_TEST}/OP01-120.png")

    def test_alternative_annoncee_par_le_nom_passe_devant(self):
        """Si la carte en base est l'illustration alternative, c'est CELLE-LA
        qui est en vente au prix affiche. Montrer l'illustration de base
        sous ce prix tromperait l'acheteur."""
        with _reglages():
            urls = urls_candidates("OP01-120", "Monkey D. Luffy (Parallel)")
        self.assertTrue(urls[0].endswith("OP01-120_p1.png"))
        self.assertIn(f"{BASE_TEST}/OP01-120.png", urls)

    def test_base_url_configurable(self):
        with _reglages(base="https://autre.test/img/"):
            urls = urls_candidates("OP01-120")
        self.assertEqual(urls[0], "https://autre.test/img/OP01-120.png")

    def test_sans_code_aucune_candidate(self):
        with _reglages():
            self.assertEqual(urls_candidates(None, "Monkey D. Luffy"), [])


class TestChercherImage(unittest.TestCase):
    def test_retient_l_adresse_qui_sert_une_image(self):
        attendue = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({attendue: ReponseFactice(200, "image/png")})
        with _reglages():
            image = _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
        self.assertIsNotNone(image)
        self.assertEqual(image.image_url, attendue)
        self.assertEqual(image.source, "onepiece-cardgame")
        self.assertEqual(image.card_id, "OP01-120")

    def test_essaie_les_variantes_puis_abandonne(self):
        session = SessionFactice()
        with _reglages():
            image = _client(session).chercher_image("Roronoa Zoro", "OP01-025")
        self.assertIsNone(image)
        # Trois adresses essayees : la base et les deux variantes.
        self.assertEqual(len(session.appels), 3)

    def test_variante_servie_quand_la_base_manque(self):
        variante = f"{BASE_TEST}/OP01-120_p1.png"
        session = SessionFactice({variante: ReponseFactice(200, "image/jpeg")})
        with _reglages():
            image = _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
        self.assertEqual(image.image_url, variante)

    def test_page_html_en_200_n_est_pas_une_image(self):
        """Le piege le plus sournois : beaucoup de sites rendent 200 avec une
        page d'erreur. Sans controle du type de contenu, on enregistrerait
        cette page comme etant l'illustration."""
        url = f"{BASE_TEST}/OP01-999.png"
        session = SessionFactice({url: ReponseFactice(200, "text/html")})
        with _reglages():
            image = _client(session).chercher_image("Carte inconnue", "OP01-999")
        self.assertIsNone(image)

    def test_sans_type_de_contenu_on_n_enregistre_pas(self):
        url = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({url: ReponseFactice(200, None)})
        with _reglages():
            self.assertIsNone(
                _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
            )

    def test_head_refuse_bascule_sur_get(self):
        """Certains hebergeurs rendent 405 sur HEAD tout en servant le GET.
        Sans ce repli, aucune image ne remonterait de cet hote."""
        url = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({url: ReponseFactice(200, "image/png")},
                                 refuse_head=True)
        with _reglages():
            image = _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
        self.assertEqual(image.image_url, url)
        self.assertIn(("get", url), session.appels)

    def test_panne_reseau_rend_none_sans_lever(self):
        """Une source distante ne doit pas casser le cycle d'enrichissement."""
        url = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({url: requests.ConnectionError("hote refuse")})
        with _reglages():
            image = _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
        self.assertIsNone(image)

    def test_sans_code_aucun_appel_reseau(self):
        """On ne devine PAS l'adresse a partir du nom : c'est l'erreur que
        cette version repare. Une carte sans code ne doit donc generer aucune
        requete."""
        session = SessionFactice()
        with _reglages():
            image = _client(session).chercher_image("Monkey D. Luffy", None)
        self.assertIsNone(image)
        self.assertEqual(session.appels, [])

    def test_mode_sans_verification_fait_confiance_au_format(self):
        session = SessionFactice()
        with _reglages(verifier=False):
            image = _client(session).chercher_image("Monkey D. Luffy", "OP01-120")
        self.assertEqual(image.image_url, f"{BASE_TEST}/OP01-120.png")
        self.assertEqual(session.appels, [])


class TestDiagnostic(unittest.TestCase):
    """Le diagnostic est le seul moyen de corriger le format d'adresse sans
    deviner : il doit rendre le detail de CHAQUE tentative."""

    def test_detaille_chaque_tentative(self):
        url = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({url: ReponseFactice(200, "image/png")})
        with _reglages():
            rapport = _client(session).diagnostic("OP01 120")

        self.assertEqual(rapport["code_canonique"], "OP01-120")
        self.assertEqual(rapport["base_url"], BASE_TEST)
        self.assertEqual(rapport["url_retenue"], url)
        self.assertEqual(rapport["tentatives"][0]["status_code"], 200)
        self.assertEqual(rapport["tentatives"][0]["content_type"], "image/png")

    def test_dit_pourquoi_quand_le_code_est_inexploitable(self):
        session = SessionFactice()
        with _reglages():
            rapport = _client(session).diagnostic("Luffy")
        self.assertIn("erreur", rapport)
        self.assertNotIn("tentatives", rapport)

    def test_rapporte_la_panne_reseau(self):
        url = f"{BASE_TEST}/OP01-120.png"
        session = SessionFactice({url: requests.ConnectionError("403 CONNECT")})
        with _reglages():
            rapport = _client(session).diagnostic("OP01-120")
        self.assertIn("erreur_reseau", rapport["tentatives"][0])
        self.assertIsNone(rapport["url_retenue"])


if __name__ == "__main__":
    unittest.main()
