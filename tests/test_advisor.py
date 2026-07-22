from __future__ import annotations

from dataclasses import replace
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.advisor import HousingProfile, OpenAIAdvisorClient  # noqa: E402
from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import build_candidate_knowledge_base, clean_hdb_transactions  # noqa: E402
from homelens.service import HomeLensService  # noqa: E402


class FakeLocationIndex:
    def locate(self, latitude, longitude):
        if 1.13 <= latitude <= 1.50 and 103.55 <= longitude <= 104.15:
            return {"planning_area": "QUEENSTOWN", "subzone": "NATIONAL UNIVERSITY OF S'PORE"}
        return None


class FakeLocationResolver:
    index = FakeLocationIndex()

    def search(self, query, *, limit=5):
        return [
            {
                "id": "onemap:nus",
                "provider": "onemap",
                "name": "NUS",
                "address": "21 Lower Kent Ridge Road Singapore 119077",
                "postal_code": "119077",
                "latitude": 1.2966,
                "longitude": 103.7764,
                "confidence": 0.9,
                "planning_area": "QUEENSTOWN",
                "subzone": "NATIONAL UNIVERSITY OF S'PORE",
            }
        ][:limit]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError("mock API error")
            error.response = self
            raise error

    def json(self):
        return self.payload


class AdvisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        clean, _ = clean_hdb_transactions(demo_hdb_frame())
        candidates, _ = build_candidate_knowledge_base(clean)
        candidate_path = directory / "candidates.csv"
        candidates.to_csv(candidate_path, index=False)
        listings = pd.DataFrame(
            [
                {
                    "listing_id": f"rent-{index}",
                    "mode": "rent",
                    "address": f"{10 + index} College Avenue",
                    "scraped_at": "2026-07-20T00:00:00Z",
                    "price_monthly": 900 + index * 100,
                    "room_type": "Common Room",
                    "resolved_latitude": 1.2966 + index * 0.001,
                    "resolved_longitude": 103.7764,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "NATIONAL UNIVERSITY OF S'PORE",
                    "nearest_mrt_name": "Kent Ridge MRT Station",
                    "nearest_mrt_distance_m": 500 + index * 50,
                    "floor_area_sqft": 150,
                }
                for index in range(4)
            ]
        )
        listing_path = directory / "listings.csv"
        listings.to_csv(listing_path, index=False)
        settings = replace(
            Settings.from_environment(),
            candidates_path=candidate_path,
            live_listings_path=listing_path,
            model_path=directory / "missing.joblib",
            openai_api_key="",
            enable_llm=False,
            onemap_token="",
            onemap_email="",
            onemap_password="",
        )
        self.service = HomeLensService(settings)
        self.service._location_resolver = FakeLocationResolver()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_student_profile_location_confirmation_and_rental_recommendation(self) -> None:
        first = self.service.advisor_message(
            {"message": "我是一个在NUS读书的学生，想在新加坡租房"}
        )
        self.assertEqual(first["profile"]["housing_mode"], "rent")
        self.assertEqual(first["profile"]["institution"], "NUS")
        self.assertEqual(first["profile"]["location_reason"], "inferred_from_institution")
        self.assertEqual(first["location_candidates"][0]["id"], "onemap:nus")

        confirmed = self.service.advisor_message(
            {
                "session_id": first["session_id"],
                "confirmed_location_id": "onemap:nus",
            }
        )
        self.assertEqual(confirmed["profile"]["anchor_planning_area"], "QUEENSTOWN")

        final = self.service.advisor_message(
            {
                "session_id": first["session_id"],
                "message": "预算每月最多1500，想租一个普通房间。我没有车，很在意公共交通，没有其他要求，请直接推荐。",
            }
        )
        self.assertTrue(final["progress"]["ready"])
        self.assertEqual(final["recommendations"]["mode"], "rent")
        self.assertEqual(len(final["recommendations"]["listings"]), 3)
        self.assertLessEqual(
            max(item["price"] for item in final["recommendations"]["listings"]),
            1_500,
        )

    def test_reset_removes_in_memory_profile(self) -> None:
        first = self.service.advisor_message({"message": "我想租房"})
        self.service.reset_advisor({"session_id": first["session_id"]})
        with self.assertRaises(ValueError):
            self.service.advisor_message(
                {"session_id": first["session_id"], "message": "继续"}
            )

    def test_university_location_does_not_imply_school_need_for_children(self) -> None:
        result = self.service.advisor_message(
            {"message": "我是NUS学生，想租在学校附近"}
        )
        self.assertEqual(result["profile"]["institution"], "NUS")
        self.assertIsNone(result["profile"]["school_need"])

    def test_location_confirmation_finishes_the_previous_price_answer(self) -> None:
        first = self.service.advisor_message(
            {"message": "我是NUS学生，想租房，附近租金大概多少？"}
        )
        confirmed = self.service.advisor_message(
            {
                "session_id": first["session_id"],
                "confirmed_location_id": "onemap:nus",
            }
        )
        self.assertIn("月租中位数", confirmed["reply"])
        self.assertIn("S$1,050", confirmed["reply"])

    def test_openai_advisor_uses_strict_schema_and_disables_storage(self) -> None:
        settings = replace(
            self.service.settings,
            openai_api_key="test-key",
            openai_base_url="https://relay.example/v1",
            openai_model="test-model",
            enable_llm=True,
            enable_web_search=True,
        )
        output = {
            "answer": "The answer is current.",
            "profile_updates": {
                key: [] if key in {"preferred_towns", "additional_needs"} else None
                for key in OpenAIAdvisorClient._schema()["properties"]["profile_updates"]["required"]
            },
            "recommendation_requested": False,
            "sources": [],
        }
        response = FakeResponse({
            "output_text": json.dumps(output),
            "output": [{"type": "web_search_call"}],
        })
        with patch("homelens.advisor.requests.post", return_value=response) as mocked:
            result = OpenAIAdvisorClient(settings).respond(
                "What is the current policy?", HousingProfile(), [], {"sources": []}
            )
        request = mocked.call_args.kwargs["json"]
        self.assertIs(request["store"], False)
        self.assertEqual(request["tools"], [{"type": "web_search"}])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(result["method"], "openai_web")


if __name__ == "__main__":
    unittest.main()
