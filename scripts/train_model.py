#!/usr/bin/env python3
"""Train and evaluate the chronological HDB resale-price experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.price_model import train_price_model  # noqa: E402
from homelens.utils import json_default  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "data" / "processed" / "hdb_transactions_clean.csv",
    )
    parser.add_argument("--test-months", type=int, default=None)
    parser.add_argument("--trees", type=int, default=120)
    args = parser.parse_args()
    if not args.input.exists():
        raise SystemExit("Clean transactions not found. Run scripts/build_dataset.py first.")
    frame = pd.read_csv(args.input, parse_dates=["month"], low_memory=False)
    result = train_price_model(
        frame, test_months=args.test_months, n_estimators=args.trees
    )
    print(json.dumps(result, indent=2, default=json_default))


if __name__ == "__main__":
    main()
