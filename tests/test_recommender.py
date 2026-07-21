from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import build_candidate_knowledge_base, clean_hdb_transactions  # noqa: E402
from homelens.recommender import recommend  # noqa: E402
from homelens.schemas import DEFAULT_WEIGHTS, UserPreferences  # noqa: E402


class RecommenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        clean, _ = clean_hdb_transactions(demo_hdb_frame())
        cls.candidates, _ = build_candidate_knowledge_base(clean)

    def test_hard_constraints_are_never_relaxed(self) -> None:
        preferences = UserPreferences(budget=650_000, flat_types=("4 ROOM",))
        result = recommend(self.candidates, preferences, top_k=8)
        self.assertGreater(len(result["recommendations"]), 0)
        for item in result["recommendations"]:
            self.assertLessEqual(item["observed_price_high"], 650_000)
            self.assertEqual(item["flat_type"], "4 ROOM")

    def test_budget_uses_75th_percentile_not_median(self) -> None:
        candidate = self.candidates.iloc[[0]].copy()
        candidate["median_resale_price"] = 500_000
        candidate["observed_price_high"] = 700_000
        preferences = UserPreferences(budget=600_000)
        result = recommend(candidate, preferences, top_k=1)
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["near_misses"][0]["budget_reference_price"], 700_000)

    def test_missing_transport_is_unknown_not_zero(self) -> None:
        result = recommend(self.candidates, UserPreferences(budget=800_000), top_k=3)
        self.assertTrue(any("transit" in warning for warning in result["warnings"]))
        for item in result["recommendations"]:
            self.assertNotIn("transit", result["effective_weights"])
            self.assertIsNone(item["nearest_mrt_distance_m"])

    def test_preferred_town_can_drive_soft_ranking(self) -> None:
        weights = {key: 0.01 for key in DEFAULT_WEIGHTS}
        weights["location"] = 1.0
        preferences = UserPreferences(
            budget=800_000, preferred_towns=("TAMPINES",), weights=weights
        )
        result = recommend(self.candidates, preferences, top_k=3)
        self.assertEqual(result["recommendations"][0]["town"], "TAMPINES")
        self.assertTrue(result["recommendations"][0]["preferred_town_match"])

    def test_confirmed_anchor_is_a_distance_filter_and_explanation(self) -> None:
        candidates = self.candidates.copy()
        candidates["latitude"] = 1.35
        candidates["longitude"] = 103.94
        candidates.loc[candidates.index[0], "latitude"] = 1.2966
        candidates.loc[candidates.index[0], "longitude"] = 103.7764
        preferences = UserPreferences(
            budget=1_000_000,
            anchor_name="NUS",
            anchor_latitude=1.2966,
            anchor_longitude=103.7764,
            max_anchor_distance_m=500,
        )
        result = recommend(candidates, preferences, top_k=3)
        self.assertEqual(len(result["recommendations"]), 1)
        item = result["recommendations"][0]
        self.assertLessEqual(item["anchor_distance_m"], 500)
        self.assertTrue(any("NUS" in reason for reason in item["reasons"]))

    def test_empty_result_returns_near_misses_without_relaxing(self) -> None:
        preferences = UserPreferences(budget=100_000, flat_types=("4 ROOM",))
        result = recommend(self.candidates, preferences, top_k=5)
        self.assertEqual(result["recommendations"], [])
        self.assertGreater(len(result["near_misses"]), 0)
        self.assertIn("Nothing was silently relaxed", result["warnings"][0])

    def test_near_misses_keep_every_non_budget_hard_constraint(self) -> None:
        preferences = UserPreferences(
            budget=100_000,
            flat_types=("4 ROOM",),
            preferred_towns=("PUNGGOL",),
            require_preferred_town=True,
            min_floor_area_sqm=90,
        )
        result = recommend(self.candidates, preferences, top_k=3)
        self.assertGreater(len(result["near_misses"]), 0)
        self.assertTrue(all(item["town"] == "PUNGGOL" for item in result["near_misses"]))
        self.assertTrue(all(item["flat_type"] == "4 ROOM" for item in result["near_misses"]))

    def test_ranking_is_deterministic(self) -> None:
        preferences = UserPreferences(budget=800_000, flat_types=("4 ROOM",))
        first = recommend(self.candidates, preferences, top_k=5)
        second = recommend(self.candidates, preferences, top_k=5)
        self.assertEqual(
            [item["candidate_id"] for item in first["recommendations"]],
            [item["candidate_id"] for item in second["recommendations"]],
        )

    def test_mrt_constraint_blocks_when_coordinates_are_missing(self) -> None:
        preferences = UserPreferences(budget=800_000, max_mrt_distance_m=800)
        result = recommend(self.candidates, preferences, top_k=3)
        self.assertEqual(result["recommendations"], [])
        self.assertEqual(result["blocked_by_missing_evidence"], ["nearest_mrt_distance_m"])
        self.assertTrue(any("enrich_geospatial.py" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
