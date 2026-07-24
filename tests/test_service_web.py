from __future__ import annotations

import json
import math
import numpy as np
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import build_candidate_knowledge_base, clean_hdb_transactions  # noqa: E402
from homelens.service import HomeLensService  # noqa: E402
from homelens.web import handler_factory, serve  # noqa: E402


class ConstantPriceModel:
    def predict(self, frame):
        return np.full(len(frame), 612_345.0)


class BrokenPriceModel:
    def predict(self, frame):
        raise AttributeError("'SimpleImputer' object has no attribute '_fill_dtype'")


class FakeLocationIndex:
    def locate(self, latitude, longitude):
        return {"planning_area": "QUEENSTOWN", "subzone": "NATIONAL UNIVERSITY OF S'PORE"}


class FakeLocationResolver:
    index = FakeLocationIndex()

    def search(self, query, *, limit=5):
        return [
            {
                "id": "onemap:nus",
                "provider": "onemap",
                "name": "National University of Singapore",
                "address": "21 Lower Kent Ridge Road",
                "postal_code": "119077",
                "latitude": 1.2966,
                "longitude": 103.7764,
                "confidence": 0.9,
                "planning_area": "QUEENSTOWN",
                "subzone": "NATIONAL UNIVERSITY OF S'PORE",
            }
        ][:limit]


class ServiceAndWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clean, _ = clean_hdb_transactions(demo_hdb_frame())
        cls.candidates, _ = build_candidate_knowledge_base(clean)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.candidates_path = Path(self.temporary.name) / "candidates.csv"
        self.candidates.to_csv(self.candidates_path, index=False)
        self.settings = replace(
            Settings.from_environment(),
            candidates_path=self.candidates_path,
            model_path=Path(self.temporary.name) / "missing-model.joblib",
            openai_api_key="",
            onemap_token="",
            onemap_email="",
            onemap_password="",
            lta_account_key="",
        )
        self.service = HomeLensService(self.settings)

    def test_natural_language_place_requires_onemap_confirmation(self) -> None:
        self.service._location_resolver = FakeLocationResolver()
        result = self.service.get_recommendations(
            {"query": "4-room under 650k within 3km of NUS", "use_llm": False}
        )
        self.assertEqual(result["status"], "location_confirmation_required")
        self.assertEqual(result["location_query"], "NUS")
        self.assertEqual(result["location_candidates"][0]["provider"], "onemap")

    def test_confirmed_place_is_validated_and_exposed(self) -> None:
        self.service._location_resolver = FakeLocationResolver()
        self.service._candidates = self.candidates.copy()
        self.service._candidates["latitude"] = 1.2966
        self.service._candidates["longitude"] = 103.7764
        result = self.service.get_recommendations(
            {
                "budget": 1_000_000,
                "anchor_name": "NUS",
                "anchor_latitude": 1.2966,
                "anchor_longitude": 103.7764,
                "top_k": 2,
            }
        )
        self.assertEqual(result["anchor_context"]["planning_area"], "QUEENSTOWN")
        self.assertEqual(result["anchor_context"]["subzone"], "NATIONAL UNIVERSITY OF S'PORE")
        self.assertTrue(
            all(item["anchor_distance_m"] is not None for item in result["recommendations"])
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_service_health_and_recommendation(self) -> None:
        health = self.service.health()
        self.assertEqual(health["status"], "ready")
        self.assertEqual(health["candidate_rows"], 8)
        result = self.service.get_recommendations(
            {"query": "4-room below 650k", "budget": 650_000, "top_k": 3}
        )
        self.assertLessEqual(len(result["recommendations"]), 3)
        self.assertEqual(result["intent"]["method"], "rules")

    def test_natural_language_is_not_overridden_by_empty_form_fields(self) -> None:
        result = self.service.get_recommendations(
            {"query": "5-room under 800k", "flat_types": [], "preferred_towns": []}
        )
        self.assertEqual(result["preferences"]["budget"], 800_000)
        self.assertEqual(result["preferences"]["flat_types"], ["5 ROOM"])

    def test_invalid_non_json_numbers_and_types_are_rejected(self) -> None:
        invalid_payloads = (
            {"budget": math.nan},
            {"budget": math.inf},
            {"budget": True},
            {"budget": 650_000, "use_llm": "false"},
            {"budget": 650_000, "weights": []},
            {"budget": 650_000, "require_preferred_town": "false"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.service.get_recommendations(payload)

    def test_model_is_exposed_as_reference_context_only(self) -> None:
        self.service._price_model_checked = True
        self.service._price_model_artifact = {
            "model": ConstantPriceModel(),
            "metadata": {
                "training_end_month": "2025-12-01",
                "test_end_month": "2026-06-01",
                "random_forest": {"mape_percent": 6.1, "mae": 40_000},
            },
        }
        result = self.service.get_recommendations({"budget": 800_000, "top_k": 1})
        self.assertEqual(result["recommendations"][0]["ml_reference_price"], 612_345.0)
        self.assertEqual(result["model_context"]["training_end_month"], "2025-12")
        self.assertIn("reference estimate only", result["model_context"]["role"])

    def test_incompatible_price_model_does_not_block_recommendations(self) -> None:
        self.service._price_model_checked = True
        self.service._price_model_artifact = {"model": BrokenPriceModel(), "metadata": {}}
        result = self.service.get_recommendations({"budget": 800_000, "top_k": 1})
        self.assertEqual(len(result["recommendations"]), 1)
        self.assertTrue(
            any("price-model reference" in warning for warning in result["warnings"])
        )

    def test_public_bind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            serve("0.0.0.0", 8000)

    def test_http_health_and_recommendation(self) -> None:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory(self.service))
        except PermissionError:
            self.skipTest("the current execution sandbox does not permit loopback sockets")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
                health = json.loads(response.read())
            self.assertEqual(health["status"], "ready")

            request = urllib.request.Request(
                base + "/api/recommend",
                data=json.dumps({"budget": 650_000, "flat_types": ["4 ROOM"]}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                result = json.loads(response.read())
            self.assertGreater(len(result["recommendations"]), 0)

            wrong_type = urllib.request.Request(
                base + "/api/recommend",
                data=b'{"budget":650000}',
                headers={"Content-Type": "text/plain"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as media_error:
                urllib.request.urlopen(wrong_type, timeout=5)
            self.assertEqual(media_error.exception.code, 415)

            cross_origin = urllib.request.Request(
                base + "/api/recommend",
                data=b'{"budget":650000}',
                headers={"Content-Type": "application/json", "Origin": "https://example.com"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as origin_error:
                urllib.request.urlopen(cross_origin, timeout=5)
            self.assertEqual(origin_error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
