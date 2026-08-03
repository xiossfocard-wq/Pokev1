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
            self.assertTrue(rc.is_allowed("https://example.test/search?q=pikachu"))

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
