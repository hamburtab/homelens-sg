#!/usr/bin/env python3
"""Download official MRT, bus-stop, hawker-centre and park GeoJSON layers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.data.official_layers import download_official_layers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_environment()
    _, manifest = download_official_layers(
        api_key=settings.data_gov_sg_api_key, force=args.force
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
