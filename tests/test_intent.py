from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.intent import OpenAIIntentParser, parse_intent, parse_with_rules  # noqa: E402


class IntentTests(unittest.TestCase):
    def test_english_intent(self) -> None:
        result = parse_with_rules(
            "A spacious 4-room under S$650k, preferably in Tampines, within 800m of MRT"
        )
        self.assertEqual(result.values["budget"], 650_000)
        self.assertEqual(result.values["flat_types"], ["4 ROOM"])
        self.assertEqual(result.values["preferred_towns"], ["TAMPINES"])
        self.assertEqual(result.values["max_mrt_distance_m"], 800)

    def test_chinese_intent(self) -> None:
        result = parse_with_rules("预算80万以内，想要四房，最好在Punggol，靠近地铁")
        self.assertEqual(result.values["budget"], 800_000)
        self.assertEqual(result.values["flat_types"], ["4 ROOM"])
        self.assertEqual(result.values["preferred_towns"], ["PUNGGOL"])

    def test_chinese_town_alias_and_numeric_flat_type(self) -> None:
        result = parse_with_rules("预算65万，在淡滨尼找4房，靠近地铁")
        self.assertEqual(result.values["budget"], 650_000)
        self.assertEqual(result.values["flat_types"], ["4 ROOM"])
        self.assertEqual(result.values["preferred_towns"], ["TAMPINES"])

    def test_arbitrary_place_and_radius_are_extracted_without_coordinates(self) -> None:
        english = parse_with_rules("A 4-room under 650k within 3km of NUS")
        chinese = parse_with_rules("预算65万，在NUS附近3公里找四房")
        for result in (english, chinese):
            self.assertEqual(result.values["location_query"], "NUS")
            self.assertEqual(result.values["max_anchor_distance_m"], 3_000)
            self.assertNotIn("anchor_latitude", result.values)

    def test_negated_town_is_not_treated_as_a_preference(self) -> None:
        result = parse_with_rules("I do not want Bedok; preferably in Tampines")
        self.assertEqual(result.values["preferred_towns"], ["TAMPINES"])
        self.assertTrue(any("BEDOK" in warning for warning in result.warnings))

    def test_only_applies_to_town_only_when_adjacent(self) -> None:
        soft = parse_with_rules("Only 4-room; preferably in Tampines")
        hard = parse_with_rules("4-room, only in Tampines")
        self.assertNotIn("require_preferred_town", soft.values)
        self.assertTrue(hard.values["require_preferred_town"])

    def test_llm_request_falls_back_when_key_is_blank(self) -> None:
        settings = replace(Settings.from_environment(), openai_api_key="")
        result = parse_intent("4-room under 600k", settings=settings, use_llm=True)
        self.assertEqual(result.method, "rules")
        self.assertTrue(any("not configured" in warning for warning in result.warnings))

    @patch("homelens.intent.requests.post")
    def test_openai_request_disables_storage(self, post: Mock) -> None:
        settings = replace(
            Settings.from_environment(),
            enable_llm=True,
            openai_api_key="test-key",
            openai_base_url="https://relay.example/v1",
            openai_model="test-model",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output_text": json.dumps(
                {
                    "budget": 650000,
                    "flat_types": ["4 ROOM"],
                    "preferred_towns": [],
                    "min_floor_area_sqm": None,
                    "min_remaining_lease_years": None,
                    "max_mrt_distance_m": None,
                    "require_preferred_town": False,
                    "priorities": ["space"],
                }
            )
        }
        post.return_value = response
        result = OpenAIIntentParser(settings).parse("spacious 4-room under 650k")
        self.assertEqual(result.method, "openai")
        self.assertFalse(post.call_args.kwargs["json"]["store"])
        self.assertEqual(post.call_args.args[0], "https://relay.example/v1/responses")


if __name__ == "__main__":
    unittest.main()
