import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import robots_compliance as rc


FAKE_ROBOTS_TXT = """
User-agent: *
Disallow: /cgu.php
Disallow: /admin/
Allow: /search
"""


class TestRobotsCompliance(unittest.TestCase):
    def setUp(self):
        rc.reset_cache_for_tests()

    def test_allowed_path(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=FAKE_ROBOTS_TXT):
            self.assertTrue(rc.is_allowed("https://example.test/search?q=luffy"))

    def test_disallowed_path(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=FAKE_ROBOTS_TXT):
            self.assertFalse(rc.is_allowed("https://example.test/cgu.php"))

    def test_disallowed_prefix(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=FAKE_ROBOTS_TXT):
            self.assertFalse(rc.is_allowed("https://example.test/admin/anything"))

    def test_missing_robots_txt_means_no_restriction(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=""):
            self.assertTrue(rc.is_allowed("https://example.test/anything"))

    def test_network_failure_refuses_by_caution(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=None):
            self.assertFalse(rc.is_allowed("https://example.test/search"))

    def test_result_is_cached_per_host(self):
        with patch.object(rc, "_fetch_robots_txt", return_value=FAKE_ROBOTS_TXT) as mocked:
            rc.is_allowed("https://example.test/search")
            rc.is_allowed("https://example.test/search?other=1")
            self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class TestEtatPourDiagnostic(unittest.TestCase):
    """`is_allowed` rend False dans deux cas tres differents : le site
    refuse, ou robots.txt n'a pas pu etre lu. Pour decider d'y aller, les
    confondre est sans danger — on s'abstient dans les deux cas. Pour un
    DIAGNOSTIC, c'est l'inverse : les deux appellent des suites opposees."""

    def setUp(self):
        rc.reset_cache_for_tests()

    def tearDown(self):
        rc.reset_cache_for_tests()

    def _session(self, contenu=None, status=200, leve=False):
        import requests

        class Rep:
            def __init__(self):
                self.status_code = status
                self.text = contenu or ""

        class Sess:
            def get(self, url, **kwargs):
                if leve:
                    raise requests.ConnectionError("hote injoignable")
                return Rep()

        return Sess()

    def test_autorise(self):
        session = self._session("User-agent: *\nAllow: /\n")
        self.assertEqual(
            rc.etat_pour_diagnostic("https://exemple.test/cartes", session=session),
            "autorise",
        )

    def test_interdit(self):
        session = self._session("User-agent: *\nDisallow: /cartes\n")
        self.assertEqual(
            rc.etat_pour_diagnostic("https://exemple.test/cartes", session=session),
            "interdit",
        )

    def test_illisible_n_est_pas_interdit(self):
        """Le cas qui comptait : un hote injoignable ne doit pas etre
        rapporte comme un site qui refuse."""
        session = self._session(leve=True)
        self.assertEqual(
            rc.etat_pour_diagnostic("https://exemple.test/cartes", session=session),
            "illisible",
        )

    def test_reste_coherent_avec_is_allowed(self):
        """Les deux fonctions doivent s'accorder : tout ce qui n'est pas
        "autorise" doit faire rendre False a `is_allowed`, sinon la sonde
        irait quelque part ou le collecteur, lui, s'abstiendrait."""
        for contenu, leve in [
            ("User-agent: *\nAllow: /\n", False),
            ("User-agent: *\nDisallow: /cartes\n", False),
            (None, True),
        ]:
            with self.subTest(contenu=contenu, leve=leve):
                rc.reset_cache_for_tests()
                session = self._session(contenu, leve=leve)
                etat = rc.etat_pour_diagnostic("https://exemple.test/cartes",
                                               session=session)
                rc.reset_cache_for_tests()
                session = self._session(contenu, leve=leve)
                autorise = rc.is_allowed("https://exemple.test/cartes", session=session)
                self.assertEqual(autorise, etat == "autorise")
