"""Geocode HDB blocks and compute straight-line access to official layers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from homelens.config import PROJECT_ROOT, Settings
from homelens.data.onemap import OneMapClient
from homelens.utils import write_json


EARTH_RADIUS_M = 6_371_008.8


def _geojson_points(path: Path) -> tuple[np.ndarray, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    coordinates: list[list[float]] = []
    properties: list[dict[str, Any]] = []
    for feature in payload.get("features", []):
        geometry = feature.get("geometry") or {}
        point = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(point, list) or len(point) < 2:
            continue
        longitude, latitude = float(point[0]), float(point[1])
        if not (103.0 <= longitude <= 105.0 and 1.0 <= latitude <= 2.0):
            continue
        coordinates.append([latitude, longitude])
        properties.append(feature.get("properties") or {})
    return np.asarray(coordinates, dtype=float), properties


def haversine_matrix(origins_lat_lon: np.ndarray, targets_lat_lon: np.ndarray) -> np.ndarray:
    origins = np.radians(np.asarray(origins_lat_lon, dtype=float))
    targets = np.radians(np.asarray(targets_lat_lon, dtype=float))
    lat1 = origins[:, 0][:, None]
    lon1 = origins[:, 1][:, None]
    lat2 = targets[:, 0][None, :]
    lon2 = targets[:, 1][None, :]
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = np.sin(delta_lat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(
        delta_lon / 2
    ) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(haversine, 0, 1)))


def geocode_candidates(
    candidates: pd.DataFrame,
    client: OneMapClient,
    *,
    cache_path: Path | None = None,
    delay_seconds: float = 0.2,
    limit: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not client.available:
        raise RuntimeError("OneMap token is required to geocode HDB block addresses")
    cache_path = cache_path or PROJECT_ROOT / "data" / "processed" / "geocode_cache.json"
    cache: dict[str, Any] = (
        json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    )
    enriched = candidates.copy()
    addresses = enriched["block_address"].dropna().astype(str).unique().tolist()
    if limit is not None:
        missing = [address for address in addresses if not cache.get(address)][:limit]
    else:
        missing = [address for address in addresses if not cache.get(address)]
    failures = 0
    for index, address in enumerate(missing):
        result = client.geocode_first(address)
        cache[address] = result
        failures += int(result is None)
        if index + 1 < len(missing):
            time.sleep(delay_seconds)
    write_json(cache_path, cache)

    enriched["latitude"] = enriched["block_address"].map(
        lambda address: (cache.get(str(address)) or {}).get("latitude")
    )
    enriched["longitude"] = enriched["block_address"].map(
        lambda address: (cache.get(str(address)) or {}).get("longitude")
    )
    report = {
        "unique_addresses": len(addresses),
        "new_geocode_requests": len(missing),
        "new_failures": failures,
        "coordinates_available": int(enriched[["latitude", "longitude"]].notna().all(axis=1).sum()),
        "cache_path": str(cache_path),
    }
    return enriched, report


def _property_value(properties: dict[str, Any], *keys: str) -> str | None:
    upper = {str(key).upper(): value for key, value in properties.items()}
    for key in keys:
        value = upper.get(key.upper())
        if value not in (None, ""):
            return str(value)
    return None


def enrich_accessibility(
    candidates: pd.DataFrame,
    layer_paths: dict[str, Path],
    *,
    chunk_size: int = 250,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    required = {"bus_stops", "mrt_exits", "hawker_centres", "parks"}
    missing_layers = required - set(layer_paths)
    if missing_layers:
        raise ValueError("missing official layer(s): " + ", ".join(sorted(missing_layers)))
    enriched = candidates.copy()
    coordinate_mask = enriched[["latitude", "longitude"]].notna().all(axis=1)
    valid_indices = enriched.index[coordinate_mask].tolist()

    mrt_points, mrt_properties = _geojson_points(layer_paths["mrt_exits"])
    bus_points, _ = _geojson_points(layer_paths["bus_stops"])
    hawker_points, _ = _geojson_points(layer_paths["hawker_centres"])
    park_points, _ = _geojson_points(layer_paths["parks"])
    point_counts = {
        "mrt_exits": len(mrt_points),
        "bus_stops": len(bus_points),
        "hawker_centres": len(hawker_points),
        "parks": len(park_points),
    }
    empty_layers = [name for name, count in point_counts.items() if count == 0]
    if empty_layers:
        raise ValueError(
            "official layer(s) contain no valid Singapore point features: "
            + ", ".join(empty_layers)
        )
    mrt_names = [
        _property_value(properties, "STATION_NA", "STATION_NAME", "NAME") or "Unknown MRT"
        for properties in mrt_properties
    ]

    for start in range(0, len(valid_indices), chunk_size):
        indices = valid_indices[start : start + chunk_size]
        origins = enriched.loc[indices, ["latitude", "longitude"]].to_numpy(float)

        mrt_distances = haversine_matrix(origins, mrt_points)
        nearest_mrt_index = np.argmin(mrt_distances, axis=1)
        enriched.loc[indices, "nearest_mrt_distance_m"] = mrt_distances[
            np.arange(len(indices)), nearest_mrt_index
        ]
        enriched.loc[indices, "nearest_mrt_name"] = [mrt_names[index] for index in nearest_mrt_index]

        bus_distances = haversine_matrix(origins, bus_points)
        enriched.loc[indices, "bus_stops_500m"] = (bus_distances <= 500).sum(axis=1)

        hawker_distances = haversine_matrix(origins, hawker_points)
        park_distances = haversine_matrix(origins, park_points)
        hawker_count = (hawker_distances <= 1_000).sum(axis=1)
        park_count = (park_distances <= 1_000).sum(axis=1)
        enriched.loc[indices, "hawker_centres_1km"] = hawker_count
        enriched.loc[indices, "parks_1km"] = park_count
        enriched.loc[indices, "amenities_1km"] = hawker_count + park_count
        enriched.loc[indices, "nearest_park_distance_m"] = park_distances.min(axis=1)

    report = {
        "distance_type": "straight-line haversine distance",
        "candidate_rows": int(len(enriched)),
        "rows_with_coordinates": int(len(valid_indices)),
        "mrt_exit_points": int(len(mrt_points)),
        "bus_stop_points": int(len(bus_points)),
        "hawker_centre_points": int(len(hawker_points)),
        "park_points": int(len(park_points)),
    }
    return enriched, report


def onemap_client_from_settings(settings: Settings) -> OneMapClient:
    client = OneMapClient(token=settings.onemap_token)
    if not client.available and settings.onemap_email and settings.onemap_password:
        client.authenticate(settings.onemap_email, settings.onemap_password)
    return client
