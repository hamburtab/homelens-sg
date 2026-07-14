#!/usr/bin/env python3
"""Geocode HDB candidates and calculate official transport/amenity features."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.data.official_layers import download_official_layers  # noqa: E402
from homelens.geospatial import (  # noqa: E402
    enrich_accessibility,
    geocode_candidates,
    onemap_client_from_settings,
)
from homelens.utils import write_json  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="geocode at most N new addresses")
    parser.add_argument("--force-layers", action="store_true")
    args = parser.parse_args()

    settings = Settings.from_environment()
    if not settings.candidates_path.exists():
        raise SystemExit("Candidate knowledge base not found. Run scripts/build_dataset.py first.")
    client = onemap_client_from_settings(settings)
    if not client.available:
        raise SystemExit(
            "OneMap is not configured. Fill ONEMAP_TOKEN or ONEMAP_EMAIL/ONEMAP_PASSWORD in .env."
        )

    candidates = pd.read_csv(settings.candidates_path, low_memory=False)
    geocoded, geocode_report = geocode_candidates(candidates, client, limit=args.limit)
    paths, layers_manifest = download_official_layers(
        api_key=settings.data_gov_sg_api_key, force=args.force_layers
    )
    enriched, access_report = enrich_accessibility(geocoded, paths)
    enriched.to_csv(settings.candidates_path, index=False)
    report = {
        "geocoding": geocode_report,
        "accessibility": access_report,
        "layers": layers_manifest,
        "output_path": str(settings.candidates_path),
    }
    write_json(PROJECT_ROOT / "artifacts" / "manifests" / "geospatial_enrichment.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
