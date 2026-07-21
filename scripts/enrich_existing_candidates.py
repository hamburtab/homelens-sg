#!/usr/bin/env python3
"""Calculate accessibility features for candidates that already have coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.geospatial import enrich_accessibility  # noqa: E402
from homelens.utils import write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "hdb_candidates_geocoded.csv",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    input_path = args.input if args.input.is_absolute() else PROJECT_ROOT / args.input
    output_path = args.output or (
        PROJECT_ROOT / "data" / "processed" / "hdb_candidates_product.csv"
    )
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    candidates = pd.read_csv(input_path, low_memory=False)
    coordinate_rows = candidates[["latitude", "longitude"]].notna().all(axis=1).sum()
    if coordinate_rows == 0:
        raise SystemExit("The input contains no candidate coordinates to enrich.")
    layer_root = PROJECT_ROOT / "data" / "raw" / "official_layers"
    layers = {
        name: layer_root / f"{name}.geojson"
        for name in ("bus_stops", "mrt_exits", "hawker_centres", "parks")
    }
    missing = [str(path) for path in layers.values() if not path.exists()]
    if missing:
        raise SystemExit("Missing official layers: " + ", ".join(missing))

    enriched, report = enrich_accessibility(candidates, layers)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_path, index=False)
    manifest = {
        "input_path": str(input_path.relative_to(PROJECT_ROOT)),
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "method": "straight-line haversine distance from existing OneMap coordinates",
        **report,
    }
    write_json(
        PROJECT_ROOT / "artifacts" / "manifests" / "candidate_accessibility.json",
        manifest,
    )
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
