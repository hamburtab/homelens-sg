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
from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import build_candidate_knowledge_base, clean_hdb_transactions  # noqa: E402
from homelens.general_agent import (  # noqa: E402
    AgentMemory,
    HousingDataTools,
    OpenAIGeneralAgentClient,
    _rule_plan,
)
from homelens.service import HomeLensService  # noqa: E402


class ConstantPriceModel:
    def predict(self, frame):
        return [612_345.0 for _ in range(len(frame))]


class FakeLocationIndex:
    def locate(self, latitude, longitude):
        if 1.13 <= latitude <= 1.50 and 103.55 <= longitude <= 104.15:
            return {
                "planning_area": "QUEENSTOWN",
                "subzone": "NATIONAL UNIVERSITY OF S'PORE",
            }
        return None


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
                "confidence": 0.95,
                "planning_area": "QUEENSTOWN",
                "subzone": "NATIONAL UNIVERSITY OF S'PORE",
            }
        ][:limit]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class GeneralAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        frame = demo_hdb_frame()
        older = frame.copy()
        older["month"] = (
            pd.to_datetime(older["month"]) - pd.DateOffset(years=2)
        ).dt.strftime("%Y-%m")
        older["_id"] = older["_id"] + 10_000
        clean, _ = clean_hdb_transactions(
            pd.concat([older, frame], ignore_index=True)
        )
        candidates, _ = build_candidate_knowledge_base(clean)
        candidates_4y, _ = build_candidate_knowledge_base(
            clean,
            lookback_months=48,
        )
        candidates["latitude"] = 1.2966
        candidates["longitude"] = 103.7764
        candidate_path = directory / "candidates.csv"
        candidates.to_csv(candidate_path, index=False)
        candidates_4y["latitude"] = 1.2966
        candidates_4y["longitude"] = 103.7764
        candidates_4y.to_csv(directory / "candidates_4y.csv", index=False)

        listings = pd.DataFrame(
            [
                {
                    "listing_id": "rent-room-1",
                    "mode": "rent",
                    "title": "Common room near NUS",
                    "address": "10 College Avenue",
                    "scraped_at": "2026-07-20T00:00:00Z",
                    "price_monthly": 1_200,
                    "asking_price": None,
                    "room_type": "Common Room",
                    "bedrooms": None,
                    "property_type": "HDB room",
                    "floor_area_sqft": 160,
                    "nearest_mrt_name": "Kent Ridge MRT Station",
                    "nearest_mrt_distance_m": 500,
                    "resolved_latitude": 1.2970,
                    "resolved_longitude": 103.7764,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "NATIONAL UNIVERSITY OF S'PORE",
                },
                {
                    "listing_id": "rent-unit-1",
                    "mode": "rent",
                    "title": "Whole unit",
                    "address": "20 Dover Road",
                    "scraped_at": "2026-07-19T00:00:00Z",
                    "price_monthly": 3_800,
                    "asking_price": None,
                    "room_type": None,
                    "bedrooms": None,
                    "property_type": "HDB Flat",
                    "floor_area_sqft": 900,
                    "nearest_mrt_name": "Dover MRT Station",
                    "nearest_mrt_distance_m": 600,
                    "resolved_latitude": 1.3000,
                    "resolved_longitude": 103.7800,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "DOVER",
                },
                {
                    "listing_id": "rent-unit-2",
                    "mode": "rent",
                    "title": "Large whole unit",
                    "address": "88 Big Road",
                    "scraped_at": "2026-07-18T00:00:00Z",
                    "price_monthly": 8_800,
                    "asking_price": None,
                    "room_type": None,
                    "bedrooms": None,
                    "property_type": "HDB Flat",
                    "floor_area_sqft": 1_300,
                    "nearest_mrt_name": "Dover MRT Station",
                    "nearest_mrt_distance_m": 650,
                    "resolved_latitude": 1.3010,
                    "resolved_longitude": 103.7810,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "DOVER",
                },
                {
                    "listing_id": "rent-unit-3",
                    "mode": "rent",
                    "title": "Alternative whole unit",
                    "address": "40 Dover Road",
                    "scraped_at": "2026-07-17T00:00:00Z",
                    "price_monthly": 3_500,
                    "asking_price": None,
                    "room_type": None,
                    "bedrooms": None,
                    "property_type": "HDB Flat",
                    "floor_area_sqft": 850,
                    "nearest_mrt_name": "Dover MRT Station",
                    "nearest_mrt_distance_m": 700,
                    "resolved_latitude": 1.3020,
                    "resolved_longitude": 103.7820,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "DOVER",
                },
                {
                    "listing_id": "sale-1",
                    "mode": "sale",
                    "title": "4-room HDB",
                    "address": "30 Test Street",
                    "scraped_at": "2026-07-20T00:00:00Z",
                    "price_monthly": None,
                    "asking_price": 620_000,
                    "room_type": None,
                    "bedrooms": 3,
                    "property_type": "HDB Flat",
                    "floor_area_sqft": 1_000,
                    "nearest_mrt_name": "Test MRT Station",
                    "nearest_mrt_distance_m": 450,
                    "resolved_latitude": 1.3100,
                    "resolved_longitude": 103.7900,
                    "resolved_town": "QUEENSTOWN",
                    "planning_area": "QUEENSTOWN",
                    "subzone": "DOVER",
                },
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

    def test_help_question_is_answered_without_profile_gate(self) -> None:
        result = self.service.agent_message({"message": "我怎么使用这个软件？"})

        self.assertIn("像使用 ChatGPT 一样", result["reply"])
        self.assertEqual(result["cards"], [])
        self.assertTrue(result["progress"]["ready"])
        self.assertNotIn("你目前更倾向租房还是买房", result["reply"])
        self.assertIsNone(self.service._advisor)

    def test_vague_recommendation_returns_mixed_exploratory_results(self) -> None:
        result = self.service.agent_message({"message": "现在有什么推荐的房子？"})

        self.assertGreaterEqual(len(result["cards"]), 2)
        self.assertIn("探索", result["reply"])
        kinds = {card["kind"] for card in result["cards"]}
        self.assertIn("listing", kinds)
        self.assertIn("historical", kinds)
        modes = {card.get("mode") for card in result["cards"]}
        self.assertIn("rent", modes)
        self.assertIn("sale", modes)

    def test_specific_rental_budget_queries_local_snapshot(self) -> None:
        result = self.service.agent_message(
            {"message": "我想租房，每月预算最多1500，想租一个普通房间，有什么房源？"}
        )

        listing_cards = [
            card for card in result["cards"] if card["kind"] == "listing"
        ]
        self.assertEqual(len(listing_cards), 1)
        self.assertEqual(listing_cards[0]["id"], "rent-room-1")
        self.assertLessEqual(listing_cards[0]["price"], 1_500)
        self.assertEqual(result["profile"]["max_budget"], 1_500)
        self.assertEqual(result["profile"]["housing_mode"], "rent")

    def test_chinese_large_no_budget_rule_plan_updates_preferences(self) -> None:
        plan = _rule_plan("我很有钱，不在意预算，但是我要房子特别大")

        self.assertTrue(plan["clear_budget"])
        self.assertIn("space", plan["priorities"])
        self.assertEqual(plan["rental_scope"], "whole_unit")

    def test_large_no_budget_rental_refinement_requeries_by_floor_area(self) -> None:
        first = self.service.agent_message(
            {"message": "Recommend some rental options under 4000."}
        )
        second = self.service.agent_message(
            {
                "session_id": first["session_id"],
                "message": "I have no budget limit and want a very large rental home.",
            }
        )

        listing_cards = [
            card for card in second["cards"] if card["kind"] == "listing"
        ]
        self.assertGreaterEqual(len(listing_cards), 2)
        self.assertEqual(listing_cards[0]["id"], "rent-unit-2")
        self.assertEqual(second["profile"]["max_budget"], None)
        self.assertIn("space", second["profile"]["additional_needs"])

    def test_more_options_excludes_previous_listing_cards(self) -> None:
        first = self.service.agent_message(
            {"message": "Recommend rental options under 4000."}
        )
        seen = {
            card["id"]
            for card in first["cards"]
            if card["kind"] == "listing"
        }

        second = self.service.agent_message(
            {
                "session_id": first["session_id"],
                "message": "Show me other rental options with no budget limit.",
            }
        )
        listing_cards = [
            card for card in second["cards"] if card["kind"] == "listing"
        ]

        self.assertTrue(listing_cards)
        self.assertTrue(all(card["id"] not in seen for card in listing_cards))

    def test_landmark_question_resumes_after_onemap_confirmation(self) -> None:
        first = self.service.agent_message(
            {"message": "NUS附近每月1500能租到什么房间？"}
        )

        self.assertEqual(first["cards"], [])
        self.assertEqual(first["location_candidates"][0]["id"], "onemap:nus")
        confirmed = self.service.agent_message(
            {
                "session_id": first["session_id"],
                "confirmed_location_id": "onemap:nus",
            }
        )
        self.assertEqual(confirmed["profile"]["anchor_name"], "National University of Singapore")
        self.assertEqual(confirmed["cards"][0]["id"], "rent-room-1")
        self.assertEqual(confirmed["location_candidates"], [])

    def test_session_state_restores_result_cards(self) -> None:
        first = self.service.agent_message({"message": "有什么推荐房源？"})
        state = self.service.agent_state(first["session_id"])

        assistant_turn = state["turns"][-1]
        self.assertEqual(assistant_turn["role"], "assistant")
        self.assertEqual(assistant_turn["cards"], first["cards"])

    def test_general_agent_historical_cards_include_model_reference(self) -> None:
        self.service._price_model_checked = True
        self.service._price_model_artifact = {
            "model": ConstantPriceModel(),
            "metadata": {
                "training_end_month": "2025-12-01",
                "test_end_month": "2026-06-01",
                "random_forest": {"mape_percent": 6.1, "mae": 40_000},
            },
        }

        result = self.service.agent_message(
            {"message": "Show historical HDB options with model reference."}
        )
        historical = next(
            card for card in result["cards"] if card["kind"] == "historical"
        )

        self.assertEqual(historical["model_reference"]["price"], 612_345.0)
        self.assertEqual(
            historical["model_reference"]["holdout_mape_percent"],
            6.1,
        )
        self.assertIn("RF reference", {metric["label"] for metric in historical["metrics"]})

    def test_historical_tools_return_separate_two_and_four_year_windows(self) -> None:
        overview = HousingDataTools(self.service).market_overview()
        windows = overview["historical_hdb_windows"]

        self.assertEqual(windows["past_2_years"]["lookback_months"], 24)
        self.assertEqual(windows["past_4_years"]["lookback_months"], 48)
        self.assertGreater(
            windows["past_4_years"]["represented_transactions"],
            windows["past_2_years"]["represented_transactions"],
        )

        result = self.service.agent_message(
            {"message": "我想买 HDB，有什么历史成交推荐？"}
        )
        historical = next(
            card for card in result["cards"] if card["kind"] == "historical"
        )
        self.assertEqual(
            [window["lookback_months"] for window in historical["historical_windows"]],
            [24, 48],
        )
        self.assertGreater(
            historical["historical_windows"][1]["transaction_count"],
            historical["historical_windows"][0]["transaction_count"],
        )

    def test_new_topic_discards_stale_location_candidates(self) -> None:
        first = self.service.agent_message({"message": "NUS附近有什么租房？"})
        self.assertTrue(first["location_candidates"])

        second = self.service.agent_message(
            {
                "session_id": first["session_id"],
                "message": "先不管地点，现在有什么房子推荐？",
            }
        )
        self.assertEqual(second["location_candidates"], [])
        self.assertGreater(len(second["cards"]), 0)

    def test_openai_planner_uses_strict_schema_and_disables_storage(self) -> None:
        settings = replace(
            self.service.settings,
            openai_api_key="test-key",
            enable_llm=True,
            openai_base_url="https://example.test/v1",
        )
        client = OpenAIGeneralAgentClient(settings)
        plan = {
            "intent": "help",
            "language": "zh",
            "housing_mode": "unknown",
            "budget": None,
            "flat_types": [],
            "bedrooms": [],
            "rental_scope": None,
            "preferred_towns": [],
            "location_query": None,
            "radius_m": None,
            "priorities": [],
            "wants_recommendations": False,
            "wants_listings": False,
            "needs_current_web": False,
            "clear_budget": False,
            "clear_location": False,
            "clear_rooms": False,
        }
        with patch(
            "homelens.general_agent.requests.post",
            return_value=FakeResponse({"output_text": json.dumps(plan)}),
        ) as mocked:
            result = client.plan("怎么用？", AgentMemory(), [])

        self.assertEqual(result["intent"], "help")
        request = mocked.call_args.kwargs["json"]
        self.assertFalse(request["store"])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(
            request["text"]["format"]["name"],
            "general_housing_agent_plan",
        )

    def test_openai_answer_preserves_markdown_line_breaks(self) -> None:
        settings = replace(
            self.service.settings,
            openai_api_key="test-key",
            enable_llm=True,
            openai_base_url="https://example.test/v1",
        )
        client = OpenAIGeneralAgentClient(settings)
        markdown_answer = (
            "目前可以先看两个指标：\n\n"
            "- **历史成交中位数**：约 62 万新币\n"
            "- **挂牌叫价中位数**：约 66 万新币\n\n"
            "两类数据不能混为一谈。"
        )
        with patch(
            "homelens.general_agent.requests.post",
            return_value=FakeResponse(
                {
                    "output_text": json.dumps(
                        {"answer": markdown_answer, "follow_up": None},
                        ensure_ascii=False,
                    )
                }
            ),
        ):
            result = client.answer(
                message="现在新加坡房价怎么样？",
                memory=AgentMemory(),
                turns=[],
                plan={"needs_current_web": False},
                evidence={},
                cards=[],
            )

        self.assertEqual(result["answer"], markdown_answer)
        self.assertIn("\n\n- **历史成交中位数**", result["answer"])


if __name__ == "__main__":
    unittest.main()
