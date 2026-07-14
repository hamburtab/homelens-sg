#!/usr/bin/env python3
"""Run one recommendation request from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.service import HomeLensService  # noqa: E402
from homelens.utils import json_default  # noqa: E402


def _comma_list(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="")
    parser.add_argument("--budget", type=float, required=True)
    parser.add_argument("--flat-types", type=_comma_list, default=[])
    parser.add_argument("--towns", type=_comma_list, default=[])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--use-llm", action="store_true")
    args = parser.parse_args()
    payload = {
        "query": args.query,
        "budget": args.budget,
        "flat_types": args.flat_types,
        "preferred_towns": args.towns,
        "top_k": args.top_k,
        "use_llm": args.use_llm,
    }
    result = HomeLensService().get_recommendations(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
