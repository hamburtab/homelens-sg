"""OneMap-backed Singapore place resolution and boundary validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import threading
import time
from typing import Any

import requests

from homelens.config import PROJECT_ROOT, Settings
from homelens.data.onemap import OneMapClient
from homelens.errors import DataUnavailableError


def _ring_contains(longitude: float, latitude: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous[:2]
        x2, y2 = current[:2]
        if (y1 > latitude) != (y2 > latitude):
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


def _bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    points: list[list[float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(geometry.get("coordinates") or [])
    return (
        min(float(point[0]) for point in points),
        min(float(point[1]) for point in points),
        max(float(point[0]) for point in points),
        max(float(point[1]) for point in points),
    )


class SingaporeLocationIndex:
    """Resolve a coordinate to the project's authoritative planning boundaries."""

    def __init__(self, path: Path | None = None) -> None:
        source = path or PROJECT_ROOT / "map" / "public" / "subzones.geojson"
        payload = json.loads(source.read_text(encoding="utf-8"))
        self.entries: list[
            tuple[tuple[float, float, float, float], dict[str, Any], dict[str, Any]]
        ] = []
        for feature in payload.get("features", []):
            geometry = feature.get("geometry") or {}
            if geometry.get("type") in {"Polygon", "MultiPolygon"}:
                self.entries.append(
                    (_bounds(geometry), geometry, feature.get("properties") or {})
                )

    def locate(self, latitude: float, longitude: float) -> dict[str, str] | None:
        if not (1.13 <= latitude <= 1.50 and 103.55 <= longitude <= 104.15):
            return None
        for bounds, geometry, properties in self.entries:
            min_lng, min_lat, max_lng, max_lat = bounds
            if not (min_lng <= longitude <= max_lng and min_lat <= latitude <= max_lat):
                continue
            if _geometry_contains(geometry, longitude, latitude):
                return {
                    "planning_area": str(properties.get("PLN_AREA_N") or ""),
                    "subzone": str(properties.get("SUBZONE_N") or ""),
                }
        return None


@dataclass
class _CacheEntry:
    created_at: float
    candidates: list[dict[str, Any]]


class OneMapLocationResolver:
    """Search arbitrary Singapore addresses and POIs with a bounded memory cache."""

    def __init__(self, settings: Settings, *, cache_ttl_seconds: int = 86_400) -> None:
        self.settings = settings
        self.cache_ttl_seconds = cache_ttl_seconds
        self.index = SingaporeLocationIndex()
        self._client: OneMapClient | None = None
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def _get_client(self) -> OneMapClient:
        if self._client is not None:
            return self._client
        client = OneMapClient(token=self.settings.onemap_token)
        if not client.available and self.settings.onemap_email and self.settings.onemap_password:
            client.authenticate(self.settings.onemap_email, self.settings.onemap_password)
        if not client.available:
            raise DataUnavailableError(
                "OneMap location search is not configured. Add ONEMAP_TOKEN or OneMap account credentials."
            )
        self._client = client
        return client

    @staticmethod
    def _search_variants(query: str) -> list[str]:
        clean = " ".join(query.split()).strip()
        variants = [clean]
        simplified = clean
        simplified = re.sub(
            r"\b(?:near|around|nearby|close to|within|in)\b",
            " ",
            simplified,
            flags=re.I,
        )
        simplified = re.sub(r"(附近|周边|靠近|在|位于)", " ", simplified)
        simplified = re.sub(r"\b(?:singapore|sg)\b", " ", simplified, flags=re.I)
        simplified = " ".join(simplified.split()).strip(" ,.;:-")
        if simplified and simplified.casefold() != clean.casefold():
            variants.append(simplified)

        lower = clean.casefold()
        alias_variants: list[str] = []
        if "utown" in lower or "u town" in lower or (
            "university town" in lower and "nus" in lower
        ):
            alias_variants.extend(["University Town", "UTown"])
        if re.search(r"\bnus\b", lower):
            alias_variants.append("National University of Singapore")
        if re.search(r"\bntu\b", lower):
            alias_variants.append("Nanyang Technological University")
        if re.search(r"\bsmu\b", lower):
            alias_variants.append("Singapore Management University")
        if re.search(r"\bsutd\b", lower):
            alias_variants.append("Singapore University of Technology and Design")
        if re.search(r"\bsit\b", lower):
            alias_variants.append("Singapore Institute of Technology")
        if re.search(r"\bsuss\b", lower):
            alias_variants.append("Singapore University of Social Sciences")
        variants.extend(alias_variants)

        result: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            value = " ".join(variant.split()).strip()
            key = value.casefold()
            if 2 <= len(value) <= 200 and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _search_once(self, client: OneMapClient, query: str, *, limit: int) -> list[dict[str, Any]]:
        try:
            return client.search_candidates(query, limit=limit)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            can_refresh = bool(self.settings.onemap_email and self.settings.onemap_password)
            if status not in {401, 403} or not can_refresh:
                raise DataUnavailableError(
                    "OneMap location search is temporarily unavailable."
                ) from error
            try:
                client.authenticate(
                    self.settings.onemap_email,
                    self.settings.onemap_password,
                )
                return client.search_candidates(query, limit=limit)
            except (requests.RequestException, RuntimeError) as retry_error:
                raise DataUnavailableError(
                    "OneMap authentication expired and could not be refreshed."
                ) from retry_error
        except requests.RequestException as error:
            raise DataUnavailableError(
                "OneMap location search is temporarily unavailable."
            ) from error

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        key = " ".join(query.casefold().split())
        if len(key) < 2 or len(key) > 200:
            raise ValueError("location query must contain between 2 and 200 characters")
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached.created_at >= now - self.cache_ttl_seconds:
                return cached.candidates[:limit]
        client = self._get_client()
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for variant in self._search_variants(query):
            raw = self._search_once(client, variant, limit=limit)
            for item in raw:
                region = self.index.locate(float(item["latitude"]), float(item["longitude"]))
                if region is None:
                    continue
                candidate = {**item, **region}
                dedupe_key = str(candidate.get("id") or "").casefold()
                if not dedupe_key:
                    dedupe_key = (
                        f"{float(candidate['latitude']):.6f}|"
                        f"{float(candidate['longitude']):.6f}|"
                        f"{str(candidate.get('address') or '').casefold()}"
                    )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                candidates.append(candidate)
            if len(candidates) >= limit:
                break
        with self._lock:
            if len(self._cache) >= 128:
                oldest = min(self._cache, key=lambda item: self._cache[item].created_at)
                self._cache.pop(oldest, None)
            self._cache[key] = _CacheEntry(now, candidates)
        return candidates[:limit]
