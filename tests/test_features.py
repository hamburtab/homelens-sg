from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import (  # noqa: E402
    build_candidate_knowledge_base,
    clean_hdb_transactions,
    parse_remaining_lease,
    parse_storey_midpoint,
)


class FeatureEngineeringTests(unittest.TestCase):
    def test_remaining_lease_parser(self) -> None:
        self.assertAlmostEqual(parse_remaining_lease("61 years 04 months"), 61 + 4 / 12)
        self.assertEqual(parse_remaining_lease("65 years"), 65)
        self.assertTrue(pd.isna(parse_remaining_lease("unknown")))

    def test_storey_midpoint_parser(self) -> None:
        self.assertEqual(parse_storey_midpoint("10 TO 12"), 11)
        self.assertTrue(pd.isna(parse_storey_midpoint("unknown")))

    def test_cleaning_reports_duplicates_and_invalid_values(self) -> None:
        frame = demo_hdb_frame().head(20)
        duplicate = frame.iloc[[0]].copy()
        invalid = frame.iloc[[1]].copy()
        invalid["_id"] = 99999
        invalid["resale_price"] = -1
        dirty = pd.concat([frame, duplicate, invalid], ignore_index=True)
        clean, report = clean_hdb_transactions(dirty)
        self.assertEqual(len(clean), 20)
        self.assertEqual(report["duplicate_rows_removed"], 1)
        self.assertEqual(report["implausible_rows_removed"], 1)
        self.assertTrue((clean["price_per_sqm"] > 0).all())

    def test_identical_rows_without_transaction_id_are_retained(self) -> None:
        frame = demo_hdb_frame().head(20).drop(columns=["_id"])
        dirty = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        clean, report = clean_hdb_transactions(dirty)
        self.assertEqual(len(clean), 21)
        self.assertEqual(report["duplicate_rows_removed"], 0)
        self.assertEqual(report["suspected_identical_rows_retained"], 2)

    def test_candidate_aggregation_and_trends(self) -> None:
        clean, _ = clean_hdb_transactions(demo_hdb_frame())
        candidates, manifest = build_candidate_knowledge_base(
            clean, lookback_months=24, minimum_transactions=3
        )
        self.assertEqual(len(candidates), 8)
        self.assertEqual(manifest["candidate_rows"], 8)
        self.assertTrue((candidates["recent_transaction_count"] == 24).all())
        self.assertTrue(candidates["candidate_id"].is_unique)
        self.assertTrue(candidates["price_trend_pct_annual"].between(0.1, 10).all())

    def test_partial_current_month_is_excluded_from_candidates(self) -> None:
        frame = demo_hdb_frame()
        partial = frame.iloc[:3].copy()
        partial["_id"] = [90001, 90002, 90003]
        partial["month"] = pd.Timestamp.now().strftime("%Y-%m")
        partial["town"] = "BEDOK"
        partial["block"] = "999A"
        partial["street_name"] = "TEST CURRENT MONTH"
        clean, _ = clean_hdb_transactions(pd.concat([frame, partial], ignore_index=True))
        candidates, manifest = build_candidate_knowledge_base(clean)
        self.assertFalse((candidates["block"] == "999A").any())
        self.assertTrue(manifest["source_latest_month_was_partial_and_excluded"])
        self.assertEqual(manifest["partial_month_rows_excluded"], 3)


if __name__ == "__main__":
    unittest.main()
