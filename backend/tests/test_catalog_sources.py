"""
Tests de la sonde de sources de catalogue (collectors/catalog_sources.py).

La sonde existe parce que ZebraDex ne couvre pas One Piece et qu'il faut
une autre source. Ce qu'on verifie ici, c'est qu'elle RAPPORTE fidelement
ce qu'elle a vu, sans conclure a la place de celui qui lira : une sonde qui
se trompe de verdict ferait exactement le degat qu'elle est censee eviter.

Aucun acces reseau : les reponses sont jouees par un double.
"""
import sys, os, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests

from app.collectors import catalog_sources
from app.collectors.catalog_sources import (
    SondeurDeSources, SourceCandidate, candidates,
)


class ReponseFactice:
    def __init__(self, status_code=200, texte="", content_type="text/html",
                 url="https://exemple.test/"):
        self.status_code = status_code
        self.text = texte
        self.headers = {"Content-Type": content_type}
        self.url = url


class SessionFactice:
    def __init__(self, reponse=None):
        self.reponse = reponse
        self.appels = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.appels.append(url)
        if isinstance(self.reponse, Exception):
            raise self.reponse
        return self.reponse or ReponseFactice()


def _sondeur(session):
    return SondeurDeSources(session=session, min_delay=0.0)


def _candidat(url="https://exemple.test/cardlist/"):
    return SourceCandidate(cle="test", url=url, apporte="code, nom")


class TestVerdicts(unittest.TestCase):
    """Le verdict doit suivre ce qui a ete recu, rien d'autre."""

    def setUp(self):
        self.autorise = mock.patch.object(
            catalog_sources.robots_compliance, "etat_pour_diagnostic",
            return_value="autorise")
        self.autorise.start()
        self.addCleanup(self.autorise.stop)

    def test_un_code_carte_rend_la_source_utilisable(self):
        page = "<html><td>OP01-120</td><td>Monkey D. Luffy</td></html>"
        rapport = _sondeur(SessionFactice(ReponseFactice(200, page))).sonder(_candidat())
        self.assertIn("UTILISABLE", rapport["conclusion"])
        self.assertEqual(rapport["indices"]["contient_un_code_carte"], "OP01-120")

    def test_404_dit_que_la_source_ne_couvre_pas_le_jeu(self):
        """Le cas ZebraDex. Le verdict doit etre explicite, pas un code nu."""
        rapport = _sondeur(SessionFactice(ReponseFactice(404, "Not Found"))).sonder(_candidat())
        self.assertIn("ne couvre pas", rapport["conclusion"])

    def test_200_sans_code_carte_ne_conclut_pas_a_l_utilisable(self):
        """Le piege exact qui nous a couté la premiere tentative : une page
        qui repond 200 n'est pas une page qui porte des cartes."""
        page = "<html><h1>Bienvenue</h1><p>Rien ici.</p></html>"
        rapport = _sondeur(SessionFactice(ReponseFactice(200, page))).sonder(_candidat())
        self.assertNotIn("UTILISABLE", rapport["conclusion"])
        self.assertIsNone(rapport["indices"]["contient_un_code_carte"])

    def test_mur_anti_bot_signale(self):
        page = "<html>Please complete the CAPTCHA to continue</html>"
        rapport = _sondeur(SessionFactice(ReponseFactice(200, page))).sonder(_candidat())
        self.assertIn("anti-bot", rapport["conclusion"])
        self.assertIn("captcha", rapport["indices"]["mentions_anti_bot"])

    def test_refus_403(self):
        rapport = _sondeur(SessionFactice(ReponseFactice(403, ""))).sonder(_candidat())
        self.assertIn("refus", rapport["conclusion"])

    def test_panne_reseau_rapportee_sans_lever(self):
        session = SessionFactice(requests.ConnectionError("hote injoignable"))
        rapport = _sondeur(session).sonder(_candidat())
        self.assertEqual(rapport["conclusion"], "injoignable")
        self.assertIn("erreur_reseau", rapport)


class TestCodesCartes(unittest.TestCase):
    """Le repere central de la sonde : un code prouve que la page porte des
    cartes du jeu, quelle que soit sa mise en forme."""

    def setUp(self):
        p = mock.patch.object(catalog_sources.robots_compliance,
                              "etat_pour_diagnostic", return_value="autorise")
        p.start()
        self.addCleanup(p.stop)

    def test_tous_les_prefixes_du_jeu(self):
        for texte, attendu in [
            ("code OP01-120 ici", "OP01-120"),
            ("deck ST01-001", "ST01-001"),
            ("booster EB01-012", "EB01-012"),
            ("promo P-001", "P-001"),
            ("premium PRB01-004", "PRB01-004"),
        ]:
            with self.subTest(texte=texte):
                rapport = _sondeur(SessionFactice(ReponseFactice(200, texte))).sonder(_candidat())
                self.assertEqual(rapport["indices"]["contient_un_code_carte"], attendu)

    def test_un_mot_qui_ressemble_n_est_pas_un_code(self):
        for texte in ("version 2026-001", "reference AB-12", "ISO 9001-004x"):
            with self.subTest(texte=texte):
                rapport = _sondeur(SessionFactice(ReponseFactice(200, texte))).sonder(_candidat())
                self.assertIsNone(rapport["indices"]["contient_un_code_carte"], texte)


class TestRobots(unittest.TestCase):
    def test_robots_interdit_la_source_n_est_pas_sondee(self):
        """Meme pour un diagnostic, on ne va pas ou le site demande qu'on
        n'aille pas."""
        session = SessionFactice(ReponseFactice(200, "OP01-120"))
        with mock.patch.object(catalog_sources.robots_compliance,
                               "etat_pour_diagnostic", return_value="interdit"):
            rapport = _sondeur(session).sonder(_candidat())
        self.assertEqual(rapport["robots_txt"], "interdit")
        self.assertIn("INTERDIT", rapport["conclusion"])
        self.assertEqual(session.appels, [], "aucune requete ne doit partir")

    def test_robots_illisible_n_est_pas_presente_comme_un_refus(self):
        """Le point le plus important de cette sonde. « Le site refuse » et
        « je n'ai pas pu demander » menent a des suites opposees : fermer la
        source, ou regarder le reseau. Les confondre ferait dire au
        diagnostic le contraire de la realite — l'erreur qui nous a menes
        ici."""
        session = SessionFactice(ReponseFactice(200, "OP01-120"))
        with mock.patch.object(catalog_sources.robots_compliance,
                               "etat_pour_diagnostic", return_value="illisible"):
            rapport = _sondeur(session).sonder(_candidat())

        self.assertEqual(rapport["robots_txt"], "illisible")
        self.assertIn("illisible", rapport["conclusion"])
        self.assertIn("PAS un refus", rapport["conclusion"])
        self.assertEqual(session.appels, [],
                         "sans autorisation lisible, on s'abstient")

    def test_robots_qui_leve_est_traite_comme_illisible(self):
        session = SessionFactice(ReponseFactice(200, "OP01-120"))
        with mock.patch.object(catalog_sources.robots_compliance,
                               "etat_pour_diagnostic",
                               side_effect=RuntimeError("robots casse")):
            rapport = _sondeur(session).sonder(_candidat())
        self.assertEqual(rapport["robots_txt"], "illisible")


class TestListeDesCandidates(unittest.TestCase):
    def test_les_sources_essentielles_sont_sondees(self):
        cles = [c.cle for c in candidates()]
        self.assertIn("liste_officielle", cles)
        self.assertIn("cardmarket_price_guide", cles)
        self.assertIn("zebradex_jeu_vise", cles,
                      "l'absence de ZebraDex doit etre reconstatee par la machine")

    def test_la_liste_officielle_derive_du_reglage_d_images(self):
        """Les illustrations et la liste viennent du meme site : un seul
        reglage, pas deux qui peuvent diverger."""
        with mock.patch.object(catalog_sources.settings, "card_image_base_url",
                               "https://exemple.test/images/cardlist/card"):
            url = next(c.url for c in candidates() if c.cle == "liste_officielle")
        self.assertEqual(url, "https://exemple.test/cardlist/")

    def test_le_fichier_de_prix_releve_a_la_main_est_sonde(self):
        with mock.patch.object(catalog_sources.settings,
                               "cardmarket_bulk_price_guide_url",
                               "https://exemple.test/prix.csv"):
            cles = [c.cle for c in candidates()]
        self.assertIn("cardmarket_fichier_direct", cles)

    def test_sans_fichier_releve_il_n_est_pas_sonde(self):
        with mock.patch.object(catalog_sources.settings,
                               "cardmarket_bulk_price_guide_url", None):
            cles = [c.cle for c in candidates()]
        self.assertNotIn("cardmarket_fichier_direct", cles)


class TestRapportComplet(unittest.TestCase):
    def test_le_rapport_liste_ce_qui_repond(self):
        page = "<html>" + "x" * 900 + " OP01-120 </html>"
        session = SessionFactice(ReponseFactice(200, page))
        with mock.patch.object(catalog_sources.robots_compliance,
                               "etat_pour_diagnostic", return_value="autorise"):
            rapport = _sondeur(session).sonder_tout()

        self.assertEqual(rapport["sources_sondees"], len(candidates()))
        self.assertTrue(rapport["repondent"])
        self.assertIn("quoi_faire", rapport)

    def test_une_source_vide_ne_compte_pas_comme_repondant(self):
        session = SessionFactice(ReponseFactice(200, "vide"))
        with mock.patch.object(catalog_sources.robots_compliance,
                               "etat_pour_diagnostic", return_value="autorise"):
            rapport = _sondeur(session).sonder_tout()
        self.assertEqual(rapport["repondent"], [])


if __name__ == "__main__":
    unittest.main()
