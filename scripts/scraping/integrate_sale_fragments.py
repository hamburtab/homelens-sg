#!/usr/bin/env python3
"""Merge compatible PropertyGuru sale CSV fragments and keep the newest listing row."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {"listing_id", "scraped_at"}


def merge_sale_fragments(paths: list[Path]) -> tuple[pd.DataFrame, dict[str, object]]:
    """Return one schema-preserving frame deduplicated by the latest scrape timestamp."""
    if not paths:
        raise ValueError("at least one input CSV is required")

    frames: list[pd.DataFrame] = []
    expected_columns: list[str] | None = None
    source_rows: dict[str, int] = {}

    for fragment_order, path in enumerate(paths):
        frame = pd.read_csv(path, encoding="utf-8-sig")
        columns = list(frame.columns)

        if expected_columns is None:
            expected_columns = columns
            missing = REQUIRED_COLUMNS - set(columns)
            if missing:
                raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
        elif columns != expected_columns:
            raise ValueError(
                f"schema mismatch for {path}; expected {expected_columns}, got {columns}"
            )

        if frame["listing_id"].isna().any():
            raise ValueError(f"{path} contains missing listing_id values")

        parsed_scraped_at = pd.to_datetime(frame["scraped_at"], errors="coerce", utc=True)
        invalid_timestamps = int(parsed_scraped_at.isna().sum())
        if invalid_timestamps:
            raise ValueError(f"{path} contains {invalid_timestamps} invalid scraped_at values")

        source_rows[str(path)] = len(frame)
        prepared = frame.copy()
        prepared["_parsed_scraped_at"] = parsed_scraped_at
        prepared["_fragment_order"] = fragment_order
        prepared["_row_order"] = range(len(prepared))
        frames.append(prepared)

    assert expected_columns is not None
    combined = pd.concat(frames, ignore_index=True)
    input_rows = len(combined)
    duplicate_rows = int(combined.duplicated("listing_id", keep=False).sum())
    duplicate_ids = int(combined.loc[combined.duplicated("listing_id", keep=False), "listing_id"].nunique())

    merged = (
        combined.sort_values(
            ["_parsed_scraped_at", "_fragment_order", "_row_order"],
            kind="mergesort",
        )
        .drop_duplicates("listing_id", keep="last")
        .loc[:, expected_columns]
        .reset_index(drop=True)
    )

    stats: dict[str, object] = {
        "source_rows": source_rows,
        "input_rows": input_rows,
        "duplicate_rows": duplicate_rows,
        "duplicate_listing_ids": duplicate_ids,
        "output_rows": len(merged),
        "unique_listing_ids": int(merged["listing_id"].nunique()),
        "deduplication_rule": "keep row with latest parsed scraped_at; later input wins ties",
    }
    return merged, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Sale CSV fragments to merge.")
    parser.add_argument("--output", required=True, type=Path, help="Merged CSV output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    merged, stats = merge_sale_fragments(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output, index=False, encoding="utf-8-sig")

    print(f"Input rows: {stats['input_rows']:,}")
    print(f"Duplicate listing IDs: {stats['duplicate_listing_ids']:,}")
    print(f"Output rows: {stats['output_rows']:,}")
    print(f"Output file: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
