import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.vision.quality_vision import analyze_card_photos, VisionQualityResult


FAKE_IMAGE_BYTES = b"\xff\xd8\xff\xe0fakejpegbytes"


def _make_anthropic_response(parsed_json: dict):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "content": [{"type": "text", "text": json.dumps(parsed_json)}]
    }
    return resp


def _make_image_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.content = FAKE_IMAGE_BYTES
    resp.headers = {"Content-Type": "image/jpeg"}
    return resp


class TestAnalyzeCardPhotos(unittest.TestCase):
    def test_no_photo_urls_returns_none(self):
        self.assertIsNone(analyze_card_photos(api_key="x", photo_urls=[], title="t", description="d"))

    @patch("app.vision.quality_vision.requests.post")
    @patch("app.vision.quality_vision.requests.get")
    def test_parses_score_and_ocr_fields(self, mock_get, mock_post):
        mock_get.return_value = _make_image_response()
        mock_post.return_value = _make_anthropic_response({
            "score": 72,
            "centering": "légèrement décentré",
            "corners": "coins nets",
            "surface": "quelques micro-rayures",
            "confidence": "medium",
            "caveats": "photo un peu floue",
            "printed_name": "Dracaufeu",
            "printed_set_number": "4/102",
            "ocr_confidence": "high",
        })

        result = analyze_card_photos(
            api_key="fake-key",
            photo_urls=["https://example.test/photo1.jpg"],
            title="Dracaufeu holo TBE",
            description="Belle carte",
        )

        self.assertIsInstance(result, VisionQualityResult)
        self.assertAlmostEqual(result.score, 72.0)
        self.assertEqual(result.printed_name, "Dracaufeu")
        self.assertEqual(result.printed_set_number, "4/102")
        self.assertEqual(result.ocr_confidence, "high")

    @patch("app.vision.quality_vision.requests.post")
    @patch("app.vision.quality_vision.requests.get")
    def test_missing_ocr_fields_default_gracefully(self, mock_get, mock_post):
        mock_get.return_value = _make_image_response()
        mock_post.return_value = _make_anthropic_response({
            "score": 50,
            "centering": "",
            "corners": "",
            "surface": "",
            "confidence": "low",
            "caveats": "une seule photo",
        })

        result = analyze_card_photos(
            api_key="fake-key",
            photo_urls=["https://example.test/photo1.jpg"],
            title="Lot cartes",
            description="",
        )

        self.assertEqual(result.printed_name, "")
        self.assertEqual(result.printed_set_number, "")
        self.assertEqual(result.ocr_confidence, "low")

    @patch("app.vision.quality_vision.requests.post")
    @patch("app.vision.quality_vision.requests.get")
    def test_all_images_failing_to_download_returns_none(self, mock_get, mock_post):
        import requests as real_requests
        mock_get.side_effect = real_requests.RequestException("boom")

        result = analyze_card_photos(
            api_key="fake-key",
            photo_urls=["https://example.test/broken.jpg"],
            title="t",
            description="d",
        )
        self.assertIsNone(result)
        mock_post.assert_not_called()

    @patch("app.vision.quality_vision.requests.post")
    @patch("app.vision.quality_vision.requests.get")
    def test_invalid_json_response_returns_none(self, mock_get, mock_post):
        mock_get.return_value = _make_image_response()
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"content": [{"type": "text", "text": "not json"}]}
        mock_post.return_value = resp

        result = analyze_card_photos(
            api_key="fake-key",
            photo_urls=["https://example.test/photo1.jpg"],
            title="t",
            description="d",
        )
        self.assertIsNone(result)

    def test_to_dict_includes_disclaimer_and_ocr_fields(self):
        result = VisionQualityResult(
            score=80, centering="ok", corners="ok", surface="ok",
            confidence="high", caveats="", printed_name="Mewtwo",
            printed_set_number="10/102", ocr_confidence="medium",
        )
        d = result.to_dict()
        self.assertIn("disclaimer", d)
        self.assertEqual(d["printed_name"], "Mewtwo")


if __name__ == "__main__":
    unittest.main()
