"""Transparent hard-filter + multi-objective ranking for HDB candidates."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from homelens.geospatial import haversine_matrix
from homelens.schemas import UserPreferences


DIMENSIONS = {
    "affordability": ("observed_price_high", False),
    "space": ("median_floor_area_sqm", True),
    "lease": ("median_remaining_lease_years", True),
    "transit": ("nearest_mrt_distance_m", False),
    "amenities": ("amenities_1km", True),
    "market_activity": ("recent_transaction_count", True),
}


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _score_bounds(candidates: pd.DataFrame, column: str) -> tuple[float, float] | None:
    values = pd.to_numeric(candidates[column], errors="coerce").dropna()
    if len(values) < 2:
        return None
    lower, upper = values.quantile([0.05, 0.95]).tolist()
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        return None
    return float(lower), float(upper)


def _normalised_score(
    values: pd.Series, bounds: tuple[float, float], higher_is_better: bool
) -> pd.Series:
    lower, upper = bounds
    score = ((pd.to_numeric(values, errors="coerce") - lower) / (upper - lower)).clip(0, 1)
    return score if higher_is_better else 1 - score


def _pareto_flags(frame: pd.DataFrame, shortlist_limit: int = 3000) -> tuple[pd.Series, bool]:
    """Mark non-dominated price/space/lease options in a bounded shortlist."""

    objectives = frame[[
        "median_resale_price",
        "median_floor_area_sqm",
        "median_remaining_lease_years",
    ]].copy()
    complete = objectives.notna().all(axis=1)
    flags = pd.Series(False, index=frame.index)
    valid = frame.loc[complete]
    truncated = len(valid) > shortlist_limit
    if truncated:
        valid = valid.nlargest(shortlist_limit, "ranking_score")
    matrix = np.column_stack(
        [
            -valid["median_resale_price"].to_numpy(float),
            valid["median_floor_area_sqm"].to_numpy(float),
            valid["median_remaining_lease_years"].to_numpy(float),
        ]
    )
    efficient = np.ones(len(valid), dtype=bool)
    for index in range(len(valid)):
        if not efficient[index]:
            continue
        dominates_index = np.all(matrix >= matrix[index], axis=1) & np.any(
            matrix > matrix[index], axis=1
        )
        if np.any(dominates_index):
            efficient[index] = False
    flags.loc[valid.index] = efficient
    return flags, truncated


def _hard_filter(
    candidates: pd.DataFrame, preferences: UserPreferences
) -> tuple[pd.DataFrame, list[str]]:
    eligible = candidates.copy()
    filters = [f"75th-percentile observed price <= S${preferences.budget:,.0f}"]
    eligible = eligible.loc[eligible["observed_price_high"] <= preferences.budget]
    if preferences.flat_types:
        eligible = eligible.loc[eligible["flat_type"].isin(preferences.flat_types)]
        filters.append("flat type in " + ", ".join(preferences.flat_types))
    if preferences.require_preferred_town and preferences.preferred_towns:
        eligible = eligible.loc[eligible["town"].isin(preferences.preferred_towns)]
        filters.append("town in " + ", ".join(preferences.preferred_towns))
    if preferences.min_floor_area_sqm is not None:
        eligible = eligible.loc[
            eligible["median_floor_area_sqm"] >= preferences.min_floor_area_sqm
        ]
        filters.append(f"median floor area >= {preferences.min_floor_area_sqm:g} sqm")
    if preferences.min_remaining_lease_years is not None:
        eligible = eligible.loc[
            eligible["median_remaining_lease_years"]
            >= preferences.min_remaining_lease_years
        ]
        filters.append(
            f"median remaining lease >= {preferences.min_remaining_lease_years:g} years"
        )
    if preferences.max_mrt_distance_m is not None:
        distance = pd.to_numeric(eligible["nearest_mrt_distance_m"], errors="coerce")
        eligible = eligible.loc[distance.notna() & (distance <= preferences.max_mrt_distance_m)]
        filters.append(f"nearest MRT distance <= {preferences.max_mrt_distance_m:g} m")
    if preferences.max_anchor_distance_m is not None:
        distance = pd.to_numeric(eligible["anchor_distance_m"], errors="coerce")
        eligible = eligible.loc[
            distance.notna() & (distance <= preferences.max_anchor_distance_m)
        ]
        filters.append(
            f"straight-line distance to {preferences.anchor_name or 'selected place'} "
            f"<= {preferences.max_anchor_distance_m:g} m"
        )
    return eligible.copy(), filters


def _near_misses(candidates: pd.DataFrame, preferences: UserPreferences) -> list[dict[str, Any]]:
    pool = candidates.copy()
    if preferences.flat_types:
        pool = pool.loc[pool["flat_type"].isin(preferences.flat_types)]
    if preferences.require_preferred_town and preferences.preferred_towns:
        pool = pool.loc[pool["town"].isin(preferences.preferred_towns)]
    if preferences.min_floor_area_sqm is not None:
        pool = pool.loc[pool["median_floor_area_sqm"] >= preferences.min_floor_area_sqm]
    if preferences.min_remaining_lease_years is not None:
        pool = pool.loc[
            pool["median_remaining_lease_years"] >= preferences.min_remaining_lease_years
        ]
    if preferences.max_mrt_distance_m is not None:
        distance = pd.to_numeric(pool.get("nearest_mrt_distance_m"), errors="coerce")
        pool = pool.loc[distance.notna() & (distance <= preferences.max_mrt_distance_m)]
    if preferences.max_anchor_distance_m is not None:
        distance = pd.to_numeric(pool.get("anchor_distance_m"), errors="coerce")
        pool = pool.loc[
            distance.notna() & (distance <= preferences.max_anchor_distance_m)
        ]
    over = pool.loc[pool["observed_price_high"] > preferences.budget].nsmallest(
        3, "observed_price_high"
    )
    return [
        {
            "candidate_id": row.candidate_id,
            "town": row.town,
            "block_address": row.block_address,
            "flat_type": row.flat_type,
            "median_resale_price": float(row.median_resale_price),
            "budget_reference_price": float(row.observed_price_high),
            "over_budget_by": float(row.observed_price_high - preferences.budget),
        }
        for row in over.itertuples(index=False)
    ]


def recommend(
    candidates: pd.DataFrame,
    preferences: UserPreferences,
    *,
    top_k: int = 8,
) -> dict[str, Any]:
    if candidates.empty:
        raise ValueError("candidate knowledge base is empty")
    if top_k <= 0 or top_k > 50:
        raise ValueError("top_k must be between 1 and 50")
    # Never add placeholder columns to the service's cached knowledge base.
    candidates = candidates.copy()

    if preferences.anchor_latitude is not None and preferences.anchor_longitude is not None:
        candidates["anchor_distance_m"] = np.nan
        if {"latitude", "longitude"}.issubset(candidates.columns):
            coordinates = candidates[["latitude", "longitude"]].apply(
                pd.to_numeric, errors="coerce"
            )
            valid = coordinates.notna().all(axis=1)
            if valid.any():
                distances = haversine_matrix(
                    coordinates.loc[valid].to_numpy(float),
                    np.asarray(
                        [[preferences.anchor_latitude, preferences.anchor_longitude]],
                        dtype=float,
                    ),
                )[:, 0]
                candidates.loc[valid, "anchor_distance_m"] = distances
    else:
        candidates["anchor_distance_m"] = np.nan

    if preferences.max_mrt_distance_m is not None:
        distance = (
            pd.to_numeric(candidates["nearest_mrt_distance_m"], errors="coerce")
            if "nearest_mrt_distance_m" in candidates
            else pd.Series(dtype=float)
        )
        if distance.notna().sum() == 0:
            return {
                "recommendations": [],
                "eligible_candidate_count": 0,
                "total_candidate_count": int(len(candidates)),
                "hard_filters": [
                    f"nearest MRT distance <= {preferences.max_mrt_distance_m:g} m"
                ],
                "effective_weights": {},
                "warnings": [
                    "The MRT-distance constraint cannot be evaluated because candidate "
                    "coordinates have not been enriched. Add OneMap credentials and run "
                    "scripts/enrich_geospatial.py; no constraint was silently relaxed."
                ],
                "near_misses": [],
                "blocked_by_missing_evidence": ["nearest_mrt_distance_m"],
            }

    eligible, applied_filters = _hard_filter(candidates, preferences)
    warnings: list[str] = []
    if preferences.max_mrt_distance_m is not None:
        missing_distance_count = int(
            pd.to_numeric(candidates["nearest_mrt_distance_m"], errors="coerce").isna().sum()
        )
        if missing_distance_count:
            warnings.append(
                f"{missing_distance_count:,} candidates without MRT-distance evidence were "
                "excluded from the hard constraint."
            )
    if eligible.empty:
        return {
            "recommendations": [],
            "eligible_candidate_count": 0,
            "total_candidate_count": int(len(candidates)),
            "hard_filters": applied_filters,
            "effective_weights": {},
            "warnings": [
                "No candidate satisfies every hard constraint. Nothing was silently relaxed."
            ],
            "near_misses": _near_misses(candidates, preferences),
        }

    available_dimensions: dict[str, tuple[str, bool, tuple[float, float]]] = {}
    unavailable_dimensions: list[str] = []
    for dimension, (column, higher_is_better) in DIMENSIONS.items():
        if column not in candidates:
            candidates[column] = np.nan
            eligible[column] = np.nan
        bounds = _score_bounds(candidates, column)
        if bounds is None:
            unavailable_dimensions.append(dimension)
            continue
        available_dimensions[dimension] = (column, higher_is_better, bounds)

    location_available = bool(preferences.preferred_towns) or preferences.anchor_latitude is not None
    active_weight_sum = sum(preferences.weights[name] for name in available_dimensions)
    if location_available:
        active_weight_sum += preferences.weights["location"]
    if active_weight_sum <= 0:
        raise ValueError("none of the positively weighted dimensions has usable data")
    effective_weights = {
        name: preferences.weights[name] / active_weight_sum for name in available_dimensions
    }
    if location_available:
        effective_weights["location"] = preferences.weights["location"] / active_weight_sum

    weighted_sum = pd.Series(0.0, index=eligible.index)
    observed_weight = pd.Series(0.0, index=eligible.index)
    component_columns: dict[str, str] = {}
    for dimension, (column, higher_is_better, bounds) in available_dimensions.items():
        component = _normalised_score(eligible[column], bounds, higher_is_better)
        component_column = f"score_{dimension}"
        eligible[component_column] = component
        component_columns[dimension] = component_column
        present = component.notna()
        weighted_sum.loc[present] += component.loc[present] * effective_weights[dimension]
        observed_weight.loc[present] += effective_weights[dimension]

    if location_available:
        location_components: list[pd.Series] = []
        if preferences.preferred_towns:
            location_components.append(
                eligible["town"].isin(preferences.preferred_towns).astype(float)
            )
        if preferences.anchor_latitude is not None:
            anchor_distance = pd.to_numeric(eligible["anchor_distance_m"], errors="coerce")
            if preferences.max_anchor_distance_m is not None:
                anchor_score = (
                    1 - anchor_distance / preferences.max_anchor_distance_m
                ).clip(0, 1)
            else:
                bounds = _score_bounds(candidates, "anchor_distance_m")
                anchor_score = (
                    _normalised_score(anchor_distance, bounds, False)
                    if bounds is not None
                    else pd.Series(np.nan, index=eligible.index)
                )
            location_components.append(anchor_score)
        location_score = pd.concat(location_components, axis=1).mean(axis=1, skipna=True)
        eligible["score_location"] = location_score
        component_columns["location"] = "score_location"
        present = location_score.notna()
        weighted_sum.loc[present] += location_score.loc[present] * effective_weights["location"]
        observed_weight.loc[present] += effective_weights["location"]

    eligible["evidence_coverage"] = observed_weight
    eligible["ranking_score"] = (weighted_sum / observed_weight.replace(0, np.nan)).fillna(0)
    # Missing evidence is uncertainty, not a zero-valued feature. Apply only a modest confidence factor.
    eligible["ranking_score"] *= 0.85 + 0.15 * eligible["evidence_coverage"]
    if preferences.preferred_towns:
        preferred = eligible["town"].isin(preferences.preferred_towns)
        eligible["preferred_town_match"] = preferred
    else:
        eligible["preferred_town_match"] = False
    eligible["ranking_score"] = eligible["ranking_score"].clip(0, 1)

    pareto, truncated = _pareto_flags(eligible)
    eligible["pareto_efficient"] = pareto
    if truncated:
        warnings.append("Pareto analysis was limited to the 3,000 highest-ranked eligible options.")
    if unavailable_dimensions:
        warnings.append(
            "Unavailable dimensions were excluded and their weights redistributed: "
            + ", ".join(unavailable_dimensions)
            + "."
        )

    ranked_all = eligible.sort_values(
        ["ranking_score", "pareto_efficient", "recent_transaction_count", "candidate_id"],
        ascending=[False, False, False, True],
    )
    selected_indices: list[Any] = []
    town_counts: dict[str, int] = {}
    for index, row in ranked_all.iterrows():
        town = str(row["town"])
        if town_counts.get(town, 0) >= 2:
            continue
        selected_indices.append(index)
        town_counts[town] = town_counts.get(town, 0) + 1
        if len(selected_indices) >= top_k:
            break
    if len(selected_indices) < top_k:
        for index in ranked_all.index:
            if index not in selected_indices:
                selected_indices.append(index)
            if len(selected_indices) >= top_k:
                break
    ranked = eligible.loc[selected_indices]
    if len(eligible["town"].unique()) > 1 and top_k > 2:
        warnings.append("The shortlist is diversified to at most two options per town when possible.")

    results: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked.itertuples(index=False), start=1):
        row_dict = row._asdict()
        reasons = [
            (
                f"Observed median S${row.median_resale_price:,.0f}; middle 50% of recent "
                f"transactions was S${row.observed_price_low:,.0f}–S${row.observed_price_high:,.0f}."
            ),
            (
                f"Typical floor area is {row.median_floor_area_sqm:.0f} sqm with about "
                f"{row.median_remaining_lease_years:.1f} years remaining."
            ),
            (
                f"Evidence comes from {int(row.recent_transaction_count)} recent transactions; "
                f"latest observed month is {pd.Timestamp(row.last_transaction_month).strftime('%Y-%m')}."
            ),
        ]
        if row.preferred_town_match:
            reasons.append(f"Matches the preferred town: {row.town.title()}.")
        anchor_distance = _safe_float(row_dict.get("anchor_distance_m"))
        if anchor_distance is not None:
            reasons.append(
                f"Straight-line distance to {preferences.anchor_name or 'the selected place'} "
                f"is {anchor_distance / 1_000:.2f} km."
            )
        mrt_distance = _safe_float(row_dict.get("nearest_mrt_distance_m"))
        mrt_name = row_dict.get("nearest_mrt_name")
        if mrt_distance is not None:
            label = f" to {mrt_name}" if isinstance(mrt_name, str) and mrt_name else ""
            reasons.append(f"Nearest recorded MRT access is {mrt_distance:,.0f} m{label}.")
        if bool(row.pareto_efficient):
            reasons.append("This is a non-dominated price/space/lease trade-off in the shortlist.")

        breakdown = {
            dimension: (
                round(float(row_dict[component]), 4)
                if component in row_dict and not pd.isna(row_dict[component])
                else None
            )
            for dimension, component in component_columns.items()
        }
        results.append(
            {
                "rank": rank,
                "candidate_id": row.candidate_id,
                "town": row.town,
                "block": row.block,
                "street_name": row.street_name,
                "block_address": row.block_address,
                "flat_type": row.flat_type,
                "flat_model": row.common_flat_model,
                "ranking_score": round(float(row.ranking_score), 4),
                "score_breakdown": breakdown,
                "evidence_coverage": round(float(row.evidence_coverage), 4),
                "pareto_efficient": bool(row.pareto_efficient),
                "preferred_town_match": bool(row.preferred_town_match),
                "median_resale_price": float(row.median_resale_price),
                "observed_price_low": float(row.observed_price_low),
                "observed_price_high": float(row.observed_price_high),
                "median_floor_area_sqm": float(row.median_floor_area_sqm),
                "median_remaining_lease_years": float(row.median_remaining_lease_years),
                "median_storey": float(row.median_storey),
                "median_price_per_sqm": float(row.median_price_per_sqm),
                "recent_transaction_count": int(row.recent_transaction_count),
                "evidence_strength": (
                    "low"
                    if int(row.recent_transaction_count) < 5
                    else "moderate"
                    if int(row.recent_transaction_count) < 10
                    else "strong"
                ),
                "last_transaction_month": pd.Timestamp(row.last_transaction_month).strftime("%Y-%m"),
                "price_trend_pct_annual": _safe_float(row.price_trend_pct_annual),
                "nearest_mrt_name": mrt_name if isinstance(mrt_name, str) else None,
                "nearest_mrt_distance_m": mrt_distance,
                "anchor_distance_m": anchor_distance,
                "latitude": _safe_float(row_dict.get("latitude")),
                "longitude": _safe_float(row_dict.get("longitude")),
                "bus_stops_500m": _safe_float(row_dict.get("bus_stops_500m")),
                "amenities_1km": _safe_float(row_dict.get("amenities_1km")),
                "reasons": reasons,
            }
        )

    low_evidence_count = sum(item["evidence_strength"] == "low" for item in results)
    if low_evidence_count:
        warnings.append(
            f"{low_evidence_count} returned option(s) have only 3–4 recent transactions; "
            "their percentile price ranges are less stable."
        )

    return {
        "recommendations": results,
        "eligible_candidate_count": int(len(eligible)),
        "total_candidate_count": int(len(candidates)),
        "hard_filters": applied_filters,
        "effective_weights": {key: round(value, 4) for key, value in effective_weights.items()},
        "warnings": warnings,
        "near_misses": [],
        "diversity_rule": "at most two returned options per town when enough towns are eligible",
    }
