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
    def test_les_trois_sources_designees_sont_sondees(self):
        cles = [c.cle for c in candidates()]
        self.assertEqual(cles, ["liste_fr_index", "liste_fr_serie", "prix_boutique_fr"])

    def test_zebradex_ne_figure_plus(self):
        """Son absence de couverture a ete constatee : la question est
        tranchee, la resonder ne ferait qu'ajouter du bruit."""
        for c in candidates():
            self.assertNotIn("zebradex", c.cle)
            self.assertNotIn("zebradex", c.url)

    def test_la_liste_derive_du_reglage_d_images(self):
        """Les visuels et la liste viennent du meme site : un seul reglage,
        pas deux qui peuvent diverger."""
        with mock.patch.object(catalog_sources.settings, "card_image_base_url",
                               "https://exemple.test/images/cardlist/card"):
            urls = {c.cle: c.url for c in candidates()}
        self.assertEqual(urls["liste_fr_index"], "https://exemple.test/cardlist/")
        self.assertTrue(urls["liste_fr_serie"].startswith(
            "https://exemple.test/cardlist/?series="))

    def test_le_site_vise_est_le_francais(self):
        """Le projet suit les cartes FRANCAISES : viser l'edition anglaise
        donnerait les mauvais noms imprimes."""
        from app.config import Settings
        self.assertIn("fr.onepiece-cardgame.com", Settings().card_image_base_url)

    def test_la_source_de_prix_suit_son_reglage(self):
        with mock.patch.object(catalog_sources.settings, "prix_source_url",
                               "https://boutique.test"):
            url = next(c.url for c in candidates() if c.cle == "prix_boutique_fr")
        self.assertEqual(url, "https://boutique.test")


class TestReperesDePrixEtDeLangue(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(catalog_sources.robots_compliance,
                              "etat_pour_diagnostic", return_value="autorise")
        p.start()
        self.addCleanup(p.stop)

    def _sonde(self, page):
        return _sondeur(SessionFactice(ReponseFactice(200, page))).sonder(_candidat())

    def test_les_prix_en_euros_sont_comptes(self):
        """Une source de prix sans prix visible n'en est pas une."""
        rapport = self._sonde("Luffy 12,50 € — Zoro 7.00 € — Nami 120,00 €")
        self.assertEqual(rapport["indices"]["nombre_de_prix_en_euros"], 3)
        self.assertEqual(rapport["indices"]["premier_prix"], "12,50 €")

    def test_une_page_sans_prix_le_dit(self):
        rapport = self._sonde("<html>OP01-120 Monkey D. Luffy</html>")
        self.assertEqual(rapport["indices"]["nombre_de_prix_en_euros"], 0)
        self.assertIsNone(rapport["indices"]["premier_prix"])

    def test_les_indices_de_francais_sont_releves(self):
        rapport = self._sonde("<html>Rareté : SR — Série : Romance Dawn — Prix</html>")
        self.assertIn("rareté", rapport["indices"]["indices_de_francais"])
        self.assertIn("série", rapport["indices"]["indices_de_francais"])

    def test_une_page_anglaise_ne_passe_pas_pour_francaise(self):
        """L'edition anglaise porte d'autres noms imprimes : la confondre
        avec la francaise remplirait le catalogue des mauvaises cartes."""
        rapport = self._sonde("<html>Rarity: SR — Series: Romance Dawn — Add to cart</html>")
        self.assertEqual(rapport["indices"]["indices_de_francais"], [])

    def test_les_mots_anglais_qui_contiennent_un_mot_francais(self):
        """Le faux positif qui a ete trouve en ecrivant ces tests : « serie »
        cherche en sous-chaine matche l'anglais « Series », et « neuf »
        matche... rien, mais « occasion » matche l'anglais « occasion ».
        La comparaison se fait donc sur des MOTS ENTIERS."""
        from app.collectors.catalog_sources import _mots_francais
        for anglais in ("this series is available",
                        "on this occasional basis",
                        "priximity is not a word"):
            with self.subTest(anglais=anglais):
                self.assertEqual(_mots_francais(anglais), [], anglais)

    def test_le_francais_sans_accents_compte_quand_meme(self):
        """Tous les sites n'accentuent pas leurs libelles."""
        from app.collectors.catalog_sources import _mots_francais
        trouves = _mots_francais("serie romance dawn, prix 12,50 €, disponible")
        self.assertIn("serie", trouves)
        self.assertIn("prix", trouves)


class TestEchantillonDeLiens(unittest.TestCase):
    """Savoir comment un site adresse ses pages dit ou chercher les series
    et les fiches cartes. C'est le renseignement principal pour une source
    dont on ne connait pas l'organisation."""

    BASE = "https://fr.exemple.test/cardlist/"

    def _liens(self, html):
        return catalog_sources._echantillon_de_liens(html, self.BASE)

    def test_les_liens_relatifs_sont_absolus(self):
        self.assertEqual(
            self._liens('<a href="?series=622117">S</a>'),
            ["https://fr.exemple.test/cardlist/?series=622117"],
        )

    def test_les_fichiers_sont_ecartes(self):
        html = ('<a href="/page">p</a><a href="/i.png">x</a>'
                '<a href="/s.css">y</a><a href="/j.js">z</a>')
        self.assertEqual(self._liens(html), ["https://fr.exemple.test/page"])

    def test_les_autres_sites_sont_ecartes(self):
        html = '<a href="/interne">a</a><a href="https://ailleurs.test/z">b</a>'
        self.assertEqual(self._liens(html), ["https://fr.exemple.test/interne"])

    def test_les_ancres_et_protocoles_speciaux_sont_ecartes(self):
        html = '<a href="#haut">a</a><a href="mailto:x@y.z">b</a><a href="/ok">c</a>'
        self.assertEqual(self._liens(html), ["https://fr.exemple.test/ok"])

    def test_les_doublons_sont_retires(self):
        html = '<a href="/a">1</a><a href="/a">2</a><a href="/b">3</a>'
        self.assertEqual(len(self._liens(html)), 2)

    def test_le_nombre_est_plafonne(self):
        html = "".join(f'<a href="/p{i}">x</a>' for i in range(80))
        self.assertLessEqual(len(self._liens(html)), 25)


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
