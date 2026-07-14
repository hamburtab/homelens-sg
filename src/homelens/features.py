"""Clean HDB transactions and build the recommendation knowledge base."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from homelens.config import PROJECT_ROOT, ensure_output_directories, load_project_config
from homelens.data.hdb import REQUIRED_FIELDS, validate_source_fields
from homelens.utils import write_json


OPTIONAL_ENRICHMENT_COLUMNS = (
    "latitude",
    "longitude",
    "nearest_mrt_name",
    "nearest_mrt_distance_m",
    "bus_stops_500m",
    "amenities_1km",
    "nearest_park_distance_m",
)


def parse_remaining_lease(value: Any) -> float:
    """Convert values such as `61 years 04 months` to decimal years."""

    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (int, float, np.number)):
        return float(value)
    text = str(value).strip().lower()
    if not text:
        return np.nan
    years_match = re.search(r"(\d+)\s*year", text)
    months_match = re.search(r"(\d+)\s*month", text)
    if years_match:
        years = int(years_match.group(1))
        months = int(months_match.group(1)) if months_match else 0
        return years + months / 12.0
    try:
        return float(text)
    except ValueError:
        return np.nan


def parse_storey_midpoint(value: Any) -> float:
    numbers = [int(number) for number in re.findall(r"\d+", str(value))]
    if len(numbers) >= 2:
        return float(numbers[0] + numbers[1]) / 2.0
    if len(numbers) == 1:
        return float(numbers[0])
    return np.nan


def clean_hdb_transactions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    validate_source_fields(frame.columns.tolist())
    clean = frame.copy()
    initial_rows = len(clean)

    text_columns = ("town", "flat_type", "block", "street_name", "flat_model", "storey_range")
    for column in text_columns:
        clean[column] = clean[column].astype("string").str.strip()
    clean["town"] = clean["town"].str.upper()
    clean["flat_type"] = clean["flat_type"].str.upper()
    clean["block"] = clean["block"].str.upper()
    clean["street_name"] = clean["street_name"].str.upper()

    clean["month"] = pd.to_datetime(clean["month"], format="%Y-%m", errors="coerce")
    numeric_columns = ("floor_area_sqm", "lease_commence_date", "resale_price")
    for column in numeric_columns:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean["remaining_lease_years"] = clean["remaining_lease"].map(parse_remaining_lease)
    clean["storey_mid"] = clean["storey_range"].map(parse_storey_midpoint)

    duplicate_subset = [column for column in REQUIRED_FIELDS if column in clean.columns]
    suspected_duplicate_rows = int(
        clean.duplicated(subset=duplicate_subset, keep=False).sum()
    )
    # The complete CSV currently has no transaction identifier. Identical rows
    # can therefore be distinct sales and are retained. When `_id` is present
    # (datastore pages and fixtures), only duplicate identifiers are removed.
    duplicate_mask = (
        clean.duplicated(subset=["_id"], keep="first")
        if "_id" in clean.columns
        else pd.Series(False, index=clean.index)
    )
    duplicate_rows = int(duplicate_mask.sum())
    clean = clean.loc[~duplicate_mask].copy()

    required_non_null = [
        "month",
        "town",
        "flat_type",
        "block",
        "street_name",
        "floor_area_sqm",
        "resale_price",
        "remaining_lease_years",
        "storey_mid",
    ]
    missing_required_mask = clean[required_non_null].isna().any(axis=1)
    missing_required_rows = int(missing_required_mask.sum())
    clean = clean.loc[~missing_required_mask].copy()

    plausible_mask = (
        clean["resale_price"].between(50_000, 3_000_000)
        & clean["floor_area_sqm"].between(20, 300)
        & clean["remaining_lease_years"].between(0, 99.5)
        & clean["storey_mid"].between(1, 60)
    )
    implausible_rows = int((~plausible_mask).sum())
    clean = clean.loc[plausible_mask].copy()

    clean["price_per_sqm"] = clean["resale_price"] / clean["floor_area_sqm"]
    clean["transaction_year"] = clean["month"].dt.year.astype(int)
    clean["month_index"] = clean["month"].dt.year * 12 + clean["month"].dt.month
    clean["block_address"] = clean["block"] + " " + clean["street_name"]
    clean = clean.sort_values(["month", "_id"] if "_id" in clean else ["month"]).reset_index(drop=True)

    report = {
        "initial_rows": int(initial_rows),
        "duplicate_rows_removed": duplicate_rows,
        "suspected_identical_rows_retained": suspected_duplicate_rows,
        "duplicate_policy": (
            "remove repeated _id values" if "_id" in frame.columns
            else "retain identical field rows because the complete CSV has no transaction ID"
        ),
        "missing_required_rows_removed": missing_required_rows,
        "implausible_rows_removed": implausible_rows,
        "clean_rows": int(len(clean)),
        "retained_fraction": float(len(clean) / initial_rows) if initial_rows else 0.0,
        "minimum_month": clean["month"].min(),
        "maximum_month": clean["month"].max(),
        "town_count": int(clean["town"].nunique()),
        "flat_type_count": int(clean["flat_type"].nunique()),
    }
    return clean, report


def _candidate_id(row: pd.Series) -> str:
    key = "|".join(
        str(row[column]) for column in ("town", "block", "street_name", "flat_type")
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _market_trends(recent: pd.DataFrame) -> pd.DataFrame:
    keys = ["town", "flat_type"]
    monthly = (
        recent.groupby(keys + ["month"], as_index=False)["resale_price"]
        .median()
        .rename(columns={"resale_price": "monthly_median_price"})
    )
    # Float avoids integer overflow when x^2 is summed over many months.
    monthly["x"] = (
        monthly["month"].dt.year * 12 + monthly["month"].dt.month
    ).astype(float)
    monthly["xy"] = monthly["x"] * monthly["monthly_median_price"]
    monthly["xx"] = monthly["x"] ** 2
    stats = monthly.groupby(keys, as_index=False).agg(
        trend_months=("month", "nunique"),
        sum_x=("x", "sum"),
        sum_y=("monthly_median_price", "sum"),
        sum_xy=("xy", "sum"),
        sum_xx=("xx", "sum"),
        mean_market_price=("monthly_median_price", "mean"),
    )
    numerator = stats["trend_months"] * stats["sum_xy"] - stats["sum_x"] * stats["sum_y"]
    denominator = stats["trend_months"] * stats["sum_xx"] - stats["sum_x"] ** 2
    monthly_slope = np.where(denominator != 0, numerator / denominator, 0.0)
    stats["price_trend_pct_annual"] = np.where(
        stats["mean_market_price"] > 0,
        monthly_slope * 12 / stats["mean_market_price"] * 100,
        0.0,
    )
    return stats[keys + ["trend_months", "price_trend_pct_annual"]]


def build_candidate_knowledge_base(
    clean: pd.DataFrame,
    *,
    lookback_months: int | None = None,
    minimum_transactions: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Aggregate recent observations into explainable recommendation candidates."""

    if clean.empty:
        raise ValueError("cannot build candidates from an empty transaction table")
    config = load_project_config()
    lookback = int(lookback_months or config["candidate_lookback_months"])
    minimum = int(minimum_transactions or config["minimum_transactions_per_candidate"])
    if lookback <= 0 or minimum <= 0:
        raise ValueError("lookback_months and minimum_transactions must be positive")

    source_maximum_month = pd.Timestamp(clean["month"].max())
    latest_month_is_partial = (
        source_maximum_month.to_period("M") == pd.Timestamp.now().to_period("M")
    )
    analysis = (
        clean.loc[clean["month"] < source_maximum_month].copy()
        if latest_month_is_partial
        else clean
    )
    if analysis.empty:
        raise ValueError("no complete observation month is available for candidate construction")
    maximum_month = pd.Timestamp(analysis["month"].max())
    cutoff = maximum_month - pd.DateOffset(months=lookback - 1)
    recent = analysis.loc[analysis["month"] >= cutoff].copy()
    keys = ["town", "block", "street_name", "flat_type"]

    candidates = recent.groupby(keys, as_index=False).agg(
        median_resale_price=("resale_price", "median"),
        observed_price_low=("resale_price", lambda values: values.quantile(0.25)),
        observed_price_high=("resale_price", lambda values: values.quantile(0.75)),
        minimum_observed_price=("resale_price", "min"),
        maximum_observed_price=("resale_price", "max"),
        median_price_per_sqm=("price_per_sqm", "median"),
        median_floor_area_sqm=("floor_area_sqm", "median"),
        median_remaining_lease_years=("remaining_lease_years", "median"),
        median_storey=("storey_mid", "median"),
        recent_transaction_count=("resale_price", "size"),
        first_transaction_month=("month", "min"),
        last_transaction_month=("month", "max"),
        common_flat_model=("flat_model", lambda values: values.mode().iloc[0]),
    )
    candidates = candidates.loc[candidates["recent_transaction_count"] >= minimum].copy()
    candidates = candidates.merge(_market_trends(recent), on=["town", "flat_type"], how="left")

    candidates["candidate_id"] = candidates.apply(_candidate_id, axis=1)
    candidates["block_address"] = candidates["block"] + " " + candidates["street_name"]
    candidates["months_since_last_transaction"] = (
        (maximum_month.year - candidates["last_transaction_month"].dt.year) * 12
        + maximum_month.month
        - candidates["last_transaction_month"].dt.month
    ).astype(int)
    for column in OPTIONAL_ENRICHMENT_COLUMNS:
        if column not in candidates:
            candidates[column] = np.nan

    ordered = [
        "candidate_id",
        "town",
        "block",
        "street_name",
        "block_address",
        "flat_type",
        "common_flat_model",
        "median_resale_price",
        "observed_price_low",
        "observed_price_high",
        "minimum_observed_price",
        "maximum_observed_price",
        "median_price_per_sqm",
        "median_floor_area_sqm",
        "median_remaining_lease_years",
        "median_storey",
        "recent_transaction_count",
        "first_transaction_month",
        "last_transaction_month",
        "months_since_last_transaction",
        "price_trend_pct_annual",
        *OPTIONAL_ENRICHMENT_COLUMNS,
    ]
    candidates = candidates[ordered].sort_values(
        ["town", "flat_type", "median_resale_price", "block_address"]
    ).reset_index(drop=True)

    manifest = {
        "candidate_unit": "town + block + street + flat_type",
        "lookback_months": lookback,
        "minimum_transactions": minimum,
        "observation_cutoff": cutoff,
        "latest_observation_month": maximum_month,
        "source_latest_month": source_maximum_month,
        "source_latest_month_was_partial_and_excluded": latest_month_is_partial,
        "partial_month_rows_excluded": int(len(clean) - len(analysis)),
        "input_transaction_rows": int(len(clean)),
        "recent_transaction_rows": int(len(recent)),
        "candidate_rows": int(len(candidates)),
        "town_count": int(candidates["town"].nunique()),
        "flat_type_count": int(candidates["flat_type"].nunique()),
        "optional_enrichment_columns": list(OPTIONAL_ENRICHMENT_COLUMNS),
    }
    return candidates, manifest


def write_knowledge_base(
    clean: pd.DataFrame,
    candidates: pd.DataFrame,
    quality_report: dict[str, Any],
    candidate_manifest: dict[str, Any],
) -> tuple[Path, Path]:
    ensure_output_directories()
    clean_path = PROJECT_ROOT / "data" / "processed" / "hdb_transactions_clean.csv"
    candidates_path = PROJECT_ROOT / "data" / "processed" / "hdb_candidates.csv"
    clean.to_csv(clean_path, index=False, date_format="%Y-%m-%d")
    candidates.to_csv(candidates_path, index=False, date_format="%Y-%m-%d")
    write_json(PROJECT_ROOT / "artifacts" / "metrics" / "data_quality.json", quality_report)
    write_json(
        PROJECT_ROOT / "artifacts" / "manifests" / "candidate_knowledge_base.json",
        candidate_manifest,
    )
    return clean_path, candidates_path


def build_from_csv(raw_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(raw_path, low_memory=False)
    clean, quality = clean_hdb_transactions(frame)
    candidates, candidate_manifest = build_candidate_knowledge_base(clean)
    clean_path, candidates_path = write_knowledge_base(
        clean, candidates, quality, candidate_manifest
    )
    return {
        "raw_path": raw_path,
        "clean_path": clean_path,
        "candidates_path": candidates_path,
        "quality": quality,
        "candidate_manifest": candidate_manifest,
    }
