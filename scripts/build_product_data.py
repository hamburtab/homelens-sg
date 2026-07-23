#!/usr/bin/env python3
"""Build privacy-safe product datasets from HomeLens research inputs.

The script keeps contributed source files immutable. It creates a deduplicated
listing table, resolves locations from exact normalized addresses when
possible, and publishes aggregate community profiles without review text or
author information.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.utils import write_json  # noqa: E402


DIMENSIONS = ("education", "transport", "food", "shopping", "recreation", "nature")
FACILITY_SOURCES = {
    "railwayStations": "geojson_railway_station.json",
    "busStops": "BusStop.geojson",
    "malls": "geojson_mall.json",
    "supermarkets": "geojson_supermarket.json",
    "convenienceStores": "geojson_convenience.json",
    "foodCourts": "geojson_food_court.json",
    "restaurants": "geojson_restaurant.json",
    "cafes": "geojson_cafe.json",
    "parks": "geojson_park.json",
    "natureReserves": "geojson_nature_reserve.json",
    "sportsCentres": "geojson_sports_centre.json",
    "schools": "geojson_school.json",
    "kindergartens": "geojson_kindergarten.json",
}
ADDRESS_REPLACEMENTS = {
    "AVENUE": "AVE",
    "STREET": "ST",
    "ROAD": "RD",
    "DRIVE": "DR",
    "CRESCENT": "CRES",
    "CENTRAL": "CTRL",
    "JALAN": "JLN",
    "BUKIT": "BT",
    "UPPER": "UPP",
    "COMMONWEALTH": "CWEALTH",
    "NORTH": "NTH",
    "SOUTH": "STH",
}


def normalise_address(value: Any) -> str:
    """Return a conservative key that reconciles common HDB street abbreviations."""

    text = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    return " ".join(ADDRESS_REPLACEMENTS.get(token, token) for token in text.split())


def _valid_coordinates(latitude: Any, longitude: Any) -> bool:
    try:
        lat = float(latitude)
        lng = float(longitude)
    except (TypeError, ValueError):
        return False
    return np.isfinite(lat) and np.isfinite(lng) and 1.0 <= lat <= 2.0 and 103.0 <= lng <= 105.0


def _ring_contains(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        crosses = (y1 > latitude) != (y2 > latitude)
        if crosses:
            boundary_x = (x2 - x1) * (latitude - y1) / (y2 - y1) + x1
            if longitude < boundary_x:
                inside = not inside
        previous = current
    return inside


def _geometry_contains(geometry: dict[str, Any], longitude: float, latitude: float) -> bool:
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if geometry.get("type") == "Polygon" else coordinates
    if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    for polygon in polygons:
        if not polygon or not _ring_contains(longitude, latitude, polygon[0]):
            continue
        if any(_ring_contains(longitude, latitude, hole) for hole in polygon[1:]):
            continue
        return True
    return False


def _coordinate_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    coordinates = geometry.get("coordinates") or []
    points: list[list[float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append(value)
            return
        if isinstance(value, list):
            for child in value:
                collect(child)

    collect(coordinates)
    longitudes = [float(point[0]) for point in points]
    latitudes = [float(point[1]) for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


class SubzoneIndex:
    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.entries: list[tuple[tuple[float, float, float, float], dict[str, Any], dict[str, Any]]] = []
        for feature in payload.get("features", []):
            geometry = feature.get("geometry") or {}
            if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
                continue
            self.entries.append(
                (_coordinate_bounds(geometry), geometry, feature.get("properties") or {})
            )

    def locate(self, latitude: float, longitude: float) -> tuple[str | None, str | None]:
        for bounds, geometry, properties in self.entries:
            min_lng, min_lat, max_lng, max_lat = bounds
            if not (min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat):
                continue
            if _geometry_contains(geometry, longitude, latitude):
                return properties.get("PLN_AREA_N"), properties.get("SUBZONE_N")
        return None, None


def _geometry_point(geometry: dict[str, Any]) -> tuple[float, float] | None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
        return float(coordinates[1]), float(coordinates[0])

    points: list[tuple[float, float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append((float(value[1]), float(value[0])))
            return
        if isinstance(value, list):
            for child in value:
                collect(child)

    collect(coordinates)
    if not points:
        return None
    return (
        float(sum(latitude for latitude, _ in points) / len(points)),
        float(sum(longitude for _, longitude in points) / len(points)),
    )


def _empty_facility_counts() -> dict[str, int]:
    return {key: 0 for key in FACILITY_SOURCES}


def _facility_profiles(subzone_index: SubzoneIndex) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    region_counts: dict[str, dict[str, int]] = {}
    subzone_counts: dict[str, dict[str, int]] = {}
    geojson_root = PROJECT_ROOT / "map" / "public" / "geojson"

    for key, filename in FACILITY_SOURCES.items():
        payload = json.loads((geojson_root / filename).read_text(encoding="utf-8"))
        for feature in payload.get("features", []):
            point = _geometry_point(feature.get("geometry") or {})
            if point is None:
                continue
            latitude, longitude = point
            planning_area, subzone = subzone_index.locate(latitude, longitude)
            if not planning_area or not subzone:
                continue
            region_counts.setdefault(str(planning_area), _empty_facility_counts())[key] += 1
            subzone_counts.setdefault(str(subzone), _empty_facility_counts())[key] += 1

    return region_counts, subzone_counts


def _stable_location_crosswalk(frame: pd.DataFrame, *, town_column: str | None = None) -> pd.DataFrame:
    located = frame.loc[
        frame.apply(lambda row: _valid_coordinates(row.get("latitude"), row.get("longitude")), axis=1)
    ].copy()
    located["address_key"] = located["address_key"].astype(str)
    aggregates: dict[str, tuple[str, str]] = {
        "latitude": ("latitude", "median"),
        "longitude": ("longitude", "median"),
        "latitude_range": ("latitude", lambda values: float(values.max() - values.min())),
        "longitude_range": ("longitude", lambda values: float(values.max() - values.min())),
    }
    if town_column:
        aggregates["town"] = (town_column, lambda values: values.dropna().astype(str).mode().iloc[0])
    crosswalk = located.groupby("address_key", as_index=True).agg(**aggregates)
    # More than roughly 330 metres of disagreement is not a safe exact-address match.
    return crosswalk.loc[
        (crosswalk["latitude_range"] <= 0.003) & (crosswalk["longitude_range"] <= 0.003)
    ]


def _candidate_crosswalk(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.copy()
    frame["address_key"] = frame["block_address"].map(normalise_address)
    return _stable_location_crosswalk(frame, town_column="town")


def _street_key(value: Any) -> str:
    """Remove a leading HDB block number from a normalised address."""

    return re.sub(r"^\d+[A-Z]*\s+", "", normalise_address(value)).strip()


def _street_area_crosswalk(
    candidate_locations: pd.DataFrame,
    subzones: SubzoneIndex,
) -> dict[str, dict[str, str | None]]:
    """Map streets to areas only when every known HDB block agrees."""

    evidence: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for address_key, row in candidate_locations.iterrows():
        street = _street_key(address_key)
        if len(street) < 6 or " " not in street:
            continue
        planning_area, subzone = subzones.locate(float(row["latitude"]), float(row["longitude"]))
        if planning_area:
            evidence.setdefault(street, []).append(
                (str(planning_area), str(subzone) if subzone else None, str(row.get("town") or ""))
            )

    crosswalk: dict[str, dict[str, str | None]] = {}
    for street, observations in evidence.items():
        planning_areas = {item[0] for item in observations}
        if len(planning_areas) != 1:
            continue
        subzone_names = {item[1] for item in observations if item[1]}
        towns = {item[2] for item in observations if item[2]}
        crosswalk[street] = {
            "planning_area": next(iter(planning_areas)),
            "subzone": next(iter(subzone_names)) if len(subzone_names) == 1 else None,
            "town": next(iter(towns)) if len(towns) == 1 else None,
        }
    return crosswalk


def _match_street_area(
    address_key: str,
    street_areas: dict[str, dict[str, str | None]],
) -> dict[str, str | None] | None:
    tokens = address_key.split()
    candidates = [" ".join(tokens[index:]) for index in range(len(tokens))]
    matches = [candidate for candidate in candidates if candidate in street_areas]
    if not matches:
        return None
    return street_areas[max(matches, key=len)]


def _deduplicate_sale_fragments(paths: Iterable[Path]) -> tuple[pd.DataFrame, dict[str, int]]:
    frames = [pd.read_csv(path, encoding="utf-8-sig", low_memory=False) for path in paths]
    expected = list(frames[0].columns)
    if any(list(frame.columns) != expected for frame in frames[1:]):
        raise ValueError("sale listing fragments do not share the same schema")
    combined = pd.concat(frames, ignore_index=True)
    combined["_timestamp"] = pd.to_datetime(combined["scraped_at"], errors="coerce", utc=True)
    if combined["listing_id"].isna().any() or combined["_timestamp"].isna().any():
        raise ValueError("sale listing fragments contain missing IDs or invalid scraped_at values")
    overlap = int(combined.duplicated("listing_id", keep=False).sum())
    overlap_ids = int(combined.loc[combined.duplicated("listing_id", keep=False), "listing_id"].nunique())
    merged = (
        combined.sort_values("_timestamp", kind="mergesort")
        .drop_duplicates("listing_id", keep="last")
        .drop(columns="_timestamp")
        .reset_index(drop=True)
    )
    return merged, {
        "input_rows": int(len(combined)),
        "overlap_rows": overlap,
        "overlap_listing_ids": overlap_ids,
        "output_rows": int(len(merged)),
    }


def _scalar(value: Any) -> Any:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _write_compact_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _listing_record(row: pd.Series, mode: str) -> dict[str, Any]:
    is_sale = mode == "sale"
    price = row.get("asking_price") if is_sale else row.get("price_monthly")
    flags: list[str] = []
    if is_sale:
        area = pd.to_numeric(pd.Series([row.get("floor_area_sqft")]), errors="coerce").iloc[0]
        psf = pd.to_numeric(pd.Series([row.get("price_psf")]), errors="coerce").iloc[0]
        if pd.notna(area) and not 300 <= float(area) <= 3000:
            flags.append("area_outlier")
        if pd.notna(psf) and not 100 <= float(psf) <= 3000:
            flags.append("psf_outlier")
    record = {
        "id": str(row["listing_id"]),
        "mode": mode,
        "source": _scalar(row.get("source")),
        "title": _scalar(row.get("title")) or _scalar(row.get("address")),
        "price": _scalar(price),
        "pricePsf": _scalar(row.get("price_psf")),
        "address": _scalar(row.get("address")),
        "propertyType": _scalar(row.get("property_type")),
        "roomType": _scalar(row.get("room_type")),
        "bedrooms": _scalar(row.get("bedrooms")),
        "bathrooms": _scalar(row.get("bathrooms")),
        "areaSqft": _scalar(row.get("floor_area_sqft")),
        "tenure": _scalar(row.get("tenure")),
        "builtYear": _scalar(row.get("built_year")),
        "nearestMRT": _scalar(row.get("nearest_mrt_name")),
        "mrtDistanceM": _scalar(row.get("nearest_mrt_distance_m")),
        "listedOn": _scalar(row.get("listed_on_text")),
        "scrapedAt": _scalar(row.get("scraped_at")),
        "latitude": _scalar(row.get("resolved_latitude")),
        "longitude": _scalar(row.get("resolved_longitude")),
        "locationSource": _scalar(row.get("location_source")),
        "areaSource": _scalar(row.get("area_source")),
        "locationConfidence": "high" if row.get("location_source") else None,
        "town": _scalar(row.get("resolved_town")),
        "planningArea": _scalar(row.get("planning_area")),
        "subzone": _scalar(row.get("subzone")),
        "qualityFlags": flags,
    }
    return {
        key: value
        for key, value in record.items()
        if value is not None and value != []
    }


def _resolve_listings(
    sale: pd.DataFrame,
    rental: pd.DataFrame,
    candidate_locations: pd.DataFrame,
    subzones: SubzoneIndex,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    rental = rental.copy()
    rental["address_key"] = rental["address"].map(normalise_address)
    rental_locations = _stable_location_crosswalk(rental)
    street_areas = _street_area_crosswalk(candidate_locations, subzones)

    frames: list[pd.DataFrame] = []
    for mode, source in (("sale", sale), ("rent", rental)):
        frame = source.copy()
        frame["mode"] = mode
        if "address_key" not in frame:
            frame["address_key"] = frame["address"].map(normalise_address)
        resolved_latitudes: list[float | None] = []
        resolved_longitudes: list[float | None] = []
        location_sources: list[str | None] = []
        area_sources: list[str | None] = []
        towns: list[str | None] = []
        planning_areas: list[str | None] = []
        subzone_names: list[str | None] = []

        for row in frame.itertuples(index=False):
            payload = row._asdict()
            key = payload["address_key"]
            candidate = candidate_locations.loc[key] if key in candidate_locations.index else None
            rental_match = rental_locations.loc[key] if key in rental_locations.index else None
            street_match = _match_street_area(key, street_areas)
            latitude: float | None = None
            longitude: float | None = None
            source_name: str | None = None
            if _valid_coordinates(payload.get("latitude"), payload.get("longitude")):
                latitude = float(payload["latitude"])
                longitude = float(payload["longitude"])
                source_name = "listing_coordinate"
            elif candidate is not None:
                latitude = float(candidate["latitude"])
                longitude = float(candidate["longitude"])
                source_name = "historical_hdb_address_match"
            elif rental_match is not None:
                latitude = float(rental_match["latitude"])
                longitude = float(rental_match["longitude"])
                source_name = "rental_address_match"

            town = str(candidate["town"]) if candidate is not None else None
            planning_area = None
            subzone_name = None
            area_source: str | None = None
            if latitude is not None and longitude is not None:
                planning_area, subzone_name = subzones.locate(latitude, longitude)
                area_source = "coordinate_point_in_polygon" if planning_area else None
            elif street_match is not None:
                planning_area = street_match["planning_area"]
                subzone_name = street_match["subzone"]
                town = town or street_match["town"]
                area_source = "historical_hdb_street_match"
            resolved_latitudes.append(latitude)
            resolved_longitudes.append(longitude)
            location_sources.append(source_name)
            area_sources.append(area_source)
            towns.append(town or planning_area)
            planning_areas.append(planning_area)
            subzone_names.append(subzone_name)

        frame["resolved_latitude"] = resolved_latitudes
        frame["resolved_longitude"] = resolved_longitudes
        frame["location_source"] = location_sources
        frame["area_source"] = area_sources
        frame["resolved_town"] = towns
        frame["planning_area"] = planning_areas
        frame["subzone"] = subzone_names
        frames.append(frame)

    enriched = pd.concat(frames, ignore_index=True, sort=False)
    public_records = [
        _listing_record(row, str(row["mode"])) for _, row in enriched.iterrows()
    ]
    public_records.sort(key=lambda item: str(item.get("scrapedAt") or ""), reverse=True)

    quality: dict[str, Any] = {}
    for mode in ("sale", "rent"):
        subset = enriched.loc[enriched["mode"] == mode]
        located = subset[["resolved_latitude", "resolved_longitude"]].notna().all(axis=1)
        region = subset["planning_area"].notna()
        quality[mode] = {
            "rows": int(len(subset)),
            "rows_with_coordinates": int(located.sum()),
            "coordinate_coverage": round(float(located.mean()), 4),
            "rows_with_planning_area": int(region.sum()),
            "planning_area_coverage": round(float(region.mean()), 4),
            "location_sources": {
                str(key): int(value)
                for key, value in subset["location_source"].fillna("unresolved").value_counts().items()
            },
            "area_sources": {
                str(key): int(value)
                for key, value in subset["area_source"].fillna("unresolved").value_counts().items()
            },
        }
    return enriched, public_records, quality


def _weighted_average(values: pd.Series, weights: pd.Series) -> float | None:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0).clip(lower=0)
    valid = numeric_values.notna()
    if not valid.any():
        return None
    if numeric_weights.loc[valid].sum() <= 0:
        return float(numeric_values.loc[valid].mean())
    return float(np.average(numeric_values.loc[valid], weights=numeric_weights.loc[valid]))


def _dimension_payload(group: pd.DataFrame, dimension: str) -> dict[str, Any]:
    score = _weighted_average(group[f"{dimension}_rating_100"], group[f"{dimension}_count"])
    return {
        "score": round(score, 1) if score is not None else None,
        "places": int(pd.to_numeric(group[f"{dimension}_count"], errors="coerce").fillna(0).sum()),
        "reviews": int(
            pd.to_numeric(group[f"{dimension}_review_count"], errors="coerce").fillna(0).sum()
        ),
    }


def _market_profiles(candidates: pd.DataFrame) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for town, group in candidates.groupby("town"):
        profiles[str(town).upper()] = {
            "medianHdbPrice": round(float(group["median_resale_price"].median()), 0),
            "medianFloorAreaSqm": round(float(group["median_floor_area_sqm"].median()), 1),
            "candidateCount": int(len(group)),
            "recentTransactions": int(group["recent_transaction_count"].sum()),
            "latestTransactionMonth": str(pd.to_datetime(group["last_transaction_month"]).max())[:7],
        }
    return profiles


def _community_profiles(
    reviews: pd.DataFrame,
    candidates: pd.DataFrame,
    listings: pd.DataFrame,
    facility_counts: tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    reviews = reviews.copy()
    reviews["planning_key"] = reviews["planning_area"].astype(str).str.upper().str.strip()
    reviews["subzone_key"] = reviews["subzone"].astype(str).str.upper().str.strip()
    market = _market_profiles(candidates)
    region_facilities, subzone_facilities = facility_counts

    region_profiles: dict[str, Any] = {}
    for planning_area, group in reviews.groupby("planning_key"):
        dimensions = {dimension: _dimension_payload(group, dimension) for dimension in DIMENSIONS}
        scores = [item["score"] for item in dimensions.values() if item["score"] is not None]
        listing_group = listings.loc[listings["planning_area"] == planning_area]
        region_profiles[planning_area] = {
            "name": planning_area,
            "liveabilityScore": round(float(np.mean(scores)), 1) if scores else None,
            "dimensions": dimensions,
            "facilityCounts": region_facilities.get(planning_area, _empty_facility_counts()),
            "subzoneCount": int(group["subzone_key"].nunique()),
            "placeEvidence": int(sum(item["places"] for item in dimensions.values())),
            "reviewEvidence": int(sum(item["reviews"] for item in dimensions.values())),
            "liveSaleListings": int((listing_group["mode"] == "sale").sum()),
            "liveRentalListings": int((listing_group["mode"] == "rent").sum()),
            "market": market.get(planning_area),
        }

    # HDB reporting uses a combined Kallang/Whampoa town. Surface its market evidence
    # in both most relevant planning areas while keeping the provenance explicit.
    for planning_area in ("KALLANG", "NOVENA"):
        if planning_area in region_profiles and region_profiles[planning_area]["market"] is None:
            region_profiles[planning_area]["market"] = market.get("KALLANG/WHAMPOA")
    if "DOWNTOWN CORE" in region_profiles and region_profiles["DOWNTOWN CORE"]["market"] is None:
        region_profiles["DOWNTOWN CORE"]["market"] = market.get("CENTRAL AREA")

    subzone_profiles: dict[str, Any] = {}
    for _, row in reviews.iterrows():
        dimensions = {
            dimension: {
                "score": _scalar(round(float(row[f"{dimension}_rating_100"]), 1)),
                "places": int(row[f"{dimension}_count"]),
                "reviews": int(row[f"{dimension}_review_count"]),
            }
            for dimension in DIMENSIONS
        }
        scores = [item["score"] for item in dimensions.values() if item["score"] is not None]
        key = str(row["subzone_key"])
        subzone_profiles[key] = {
            "name": key,
            "planningArea": str(row["planning_key"]),
            "liveabilityScore": round(float(np.mean(scores)), 1) if scores else None,
            "dimensions": dimensions,
            "facilityCounts": subzone_facilities.get(key, _empty_facility_counts()),
        }
    return region_profiles, subzone_profiles


def build_product_data() -> dict[str, Any]:
    product_candidate_path = PROJECT_ROOT / "data" / "processed" / "hdb_candidates_product.csv"
    candidate_path = (
        product_candidate_path
        if product_candidate_path.exists()
        else PROJECT_ROOT / "data" / "processed" / "hdb_candidates_geocoded.csv"
    )
    sale_paths = [
        PROJECT_ROOT / "data" / "raw" / "listings" / "propertyguru" / "live_sale_listings.csv",
        PROJECT_ROOT
        / "data"
        / "interim"
        / "listings"
        / "propertyguru"
        / "live_sale_listings_pages_0301_0500.csv",
    ]
    rental_path = (
        PROJECT_ROOT / "data" / "raw" / "listings" / "propertyguru" / "live_rental_listings.csv"
    )
    reviews_path = (
        PROJECT_ROOT
        / "data"
        / "external"
        / "community_reviews"
        / "google_maps_subzone_reviews"
        / "all_singapore_subzone_objective_dimension_review_profile.csv"
    )
    subzones_path = PROJECT_ROOT / "map" / "public" / "subzones.geojson"

    candidates = pd.read_csv(candidate_path, low_memory=False)
    sale, sale_merge = _deduplicate_sale_fragments(sale_paths)
    rental = pd.read_csv(rental_path, encoding="utf-8-sig", low_memory=False)
    reviews = pd.read_csv(reviews_path, low_memory=False)
    subzone_index = SubzoneIndex(subzones_path)
    candidate_locations = _candidate_crosswalk(candidates)
    listings, public_listings, location_quality = _resolve_listings(
        sale, rental, candidate_locations, subzone_index
    )
    facility_counts = _facility_profiles(subzone_index)
    region_profiles, subzone_profiles = _community_profiles(
        reviews, candidates, listings, facility_counts
    )

    processed_path = PROJECT_ROOT / "data" / "processed" / "live_listings_enriched.csv"
    public_listing_path = PROJECT_ROOT / "map" / "public" / "live-listings.json"
    region_path = PROJECT_ROOT / "map" / "public" / "region-profiles.json"
    subzone_path = PROJECT_ROOT / "map" / "public" / "subzone-profiles.json"
    status_path = PROJECT_ROOT / "map" / "public" / "data-status.json"
    manifest_path = PROJECT_ROOT / "artifacts" / "manifests" / "product_data.json"

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    listings.to_csv(processed_path, index=False, encoding="utf-8-sig")
    generated_at = datetime.now(timezone.utc).isoformat()
    _write_compact_json(public_listing_path, public_listings)
    write_json(region_path, {"generatedAt": generated_at, "profiles": region_profiles})
    write_json(subzone_path, {"generatedAt": generated_at, "profiles": subzone_profiles})

    candidate_coordinates = candidates[["latitude", "longitude"]].notna().all(axis=1)
    status = {
        "generatedAt": generated_at,
        "historicalMarket": {
            "candidateRows": int(len(candidates)),
            "towns": int(candidates["town"].nunique()),
            "rowsWithCoordinates": int(candidate_coordinates.sum()),
            "latestObservationMonth": str(pd.to_datetime(candidates["last_transaction_month"]).max())[:7],
        },
        "liveListings": {
            "sale": location_quality["sale"],
            "rent": location_quality["rent"],
            "latestScrape": str(pd.to_datetime(listings["scraped_at"], utc=True).max()),
            "saleParsedPageRanges": ["1-145", "301-500"],
            "saleRawPagesAwaitingImport": "146-185",
            "knownSalePageGap": "186-300 and pages after 500",
            "coverageWarning": "PropertyGuru sale data is a partial research snapshot, not complete market inventory.",
        },
        "communityEvidence": {
            "planningAreas": int(reviews["planning_area"].nunique()),
            "subzones": int(reviews["subzone"].nunique()),
            "dimensions": list(DIMENSIONS),
            "facilitySources": list(FACILITY_SOURCES),
            "privacy": "Only aggregate counts and scores are published; review text and author data stay external.",
        },
        "model": {
            "role": "Reference price only; never used to relax budget constraints.",
            "holdoutMapePercent": 5.9,
            "holdoutR2": 0.928,
        },
        "unavailable": [
            "Walking-time and route-aware commute estimates",
            "Complete live-sale inventory and automated weekly refresh",
            "Exact coordinates for unresolved listing addresses",
            "Private-condominium historical recommendation model",
        ],
    }
    write_json(status_path, status)

    manifest = {
        "created_at": generated_at,
        "sources": [str(path.relative_to(PROJECT_ROOT)) for path in [candidate_path, *sale_paths, rental_path, reviews_path, subzones_path]],
        "outputs": [
            str(path.relative_to(PROJECT_ROOT))
            for path in [processed_path, public_listing_path, region_path, subzone_path, status_path]
        ],
        "sale_merge": sale_merge,
        "location_quality": location_quality,
        "region_profiles": len(region_profiles),
        "subzone_profiles": len(subzone_profiles),
        "privacy_guards": [
            "raw_listing_text excluded from public JSON",
            "source listing reference excluded from public JSON",
            "review text, author names, and author URLs excluded from public JSON",
        ],
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    manifest = build_product_data()
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
