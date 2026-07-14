from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.schemas import UserPreferences  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_non_finite_and_boolean_numbers_are_rejected(self) -> None:
        for budget in (math.nan, math.inf, -math.inf, True):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                UserPreferences(budget=budget)

    def test_boolean_and_weight_fields_are_strict(self) -> None:
        with self.assertRaises(ValueError):
            UserPreferences(budget=650_000, require_preferred_town="false")
        with self.assertRaises(ValueError):
            UserPreferences(budget=650_000, weights={"affordability": True})
        with self.assertRaises(ValueError):
            UserPreferences(budget=650_000, weights={"typo": 1})

    def test_text_selections_must_contain_strings(self) -> None:
        with self.assertRaises(ValueError):
            UserPreferences(budget=650_000, preferred_towns=[123])


if __name__ == "__main__":
    unittest.main()
