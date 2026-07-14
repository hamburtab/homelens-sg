#!/usr/bin/env python3
"""Download/prepare HDB data and build the local candidate knowledge base."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.data.hdb import create_demo_snapshot, download_hdb_snapshot  # noqa: E402
from homelens.features import build_from_csv  # noqa: E402
from homelens.utils import json_default  # noqa: E402


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    source = result.add_mutually_exclusive_group()
    source.add_argument("--fixture", action="store_true", help="use deterministic offline data")
    source.add_argument("--raw", type=Path, help="build from an existing HDB-shaped CSV")
    result.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="download only the newest N records for a rapid prototype",
    )
    result.add_argument("--page-size", type=int, default=None)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.fixture:
        raw_path, source_manifest = create_demo_snapshot()
    elif args.raw:
        raw_path = args.raw.expanduser().resolve()
        if not raw_path.exists():
            raise SystemExit(f"Raw CSV not found: {raw_path}")
        source_manifest = {"source": "existing file", "snapshot_path": str(raw_path)}
    else:
        raw_path, source_manifest = download_hdb_snapshot(
            max_records=args.max_records, page_size=args.page_size
        )
    result = build_from_csv(raw_path)
    summary = {
        "source": source_manifest,
        "raw_path": str(raw_path),
        "clean_path": str(result["clean_path"]),
        "candidates_path": str(result["candidates_path"]),
        "quality": result["quality"],
        "candidate_manifest": result["candidate_manifest"],
    }
    print(json.dumps(summary, indent=2, default=json_default))


if __name__ == "__main__":
    main()
