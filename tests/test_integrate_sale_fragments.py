from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.scraping.integrate_sale_fragments import merge_sale_fragments


class IntegrateSaleFragmentsTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, rows: list[dict]) -> Path:
        path = directory / name
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def test_latest_scrape_wins_for_overlapping_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            older = self._write(
                directory,
                "older.csv",
                [
                    {"listing_id": "a", "scraped_at": "2026-07-20T09:00:00Z", "price": 1},
                    {"listing_id": "b", "scraped_at": "2026-07-20T09:00:00Z", "price": 2},
                ],
            )
            newer = self._write(
                directory,
                "newer.csv",
                [
                    {"listing_id": "a", "scraped_at": "2026-07-20T10:00:00Z", "price": 3},
                    {"listing_id": "c", "scraped_at": "2026-07-20T10:00:00Z", "price": 4},
                ],
            )

            merged, stats = merge_sale_fragments([older, newer])

            self.assertEqual(len(merged), 3)
            self.assertEqual(merged.set_index("listing_id").loc["a", "price"], 3)
            self.assertEqual(stats["duplicate_listing_ids"], 1)
            self.assertEqual(stats["unique_listing_ids"], 3)

    def test_schema_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            first = self._write(
                directory,
                "first.csv",
                [{"listing_id": "a", "scraped_at": "2026-07-20T09:00:00Z"}],
            )
            second = self._write(
                directory,
                "second.csv",
                [{"listing_id": "b", "scraped_at": "2026-07-20T10:00:00Z", "extra": 1}],
            )

            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                merge_sale_fragments([first, second])

    def test_invalid_timestamp_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = self._write(
                Path(temporary_directory),
                "invalid.csv",
                [{"listing_id": "a", "scraped_at": "not-a-time"}],
            )

            with self.assertRaisesRegex(ValueError, "invalid scraped_at"):
                merge_sale_fragments([path])


if __name__ == "__main__":
    unittest.main()
