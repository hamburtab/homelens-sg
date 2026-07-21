"""Small OneMap client used by the future geospatial enrichment step."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import requests

from homelens.errors import MissingCredentialError


class OneMapClient:
    SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"
    TOKEN_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"

    def __init__(self, token: str = "", timeout_seconds: int = 30) -> None:
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HomeLens-SG/0.1 educational-project"})
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    @property
    def available(self) -> bool:
        return bool(self.token)

    def authenticate(self, email: str, password: str) -> str:
        if not email.strip() or not password.strip():
            raise MissingCredentialError(
                "OneMap authentication needs ONEMAP_EMAIL and ONEMAP_PASSWORD."
            )
        response = self.session.post(
            self.TOKEN_URL,
            json={"email": email.strip(), "password": password},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token") or payload.get("token")
        if not token:
            raise RuntimeError("OneMap token response did not contain an access token")
        self.token = str(token)
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        return self.token

    def search(self, query: str, page: int = 1) -> dict[str, Any]:
        if not self.token:
            raise MissingCredentialError(
                "OneMap is not configured. Add ONEMAP_TOKEN to .env before geocoding."
            )
        response = self.session.get(
            self.SEARCH_URL,
            params={
                "searchVal": query,
                "returnGeom": "Y",
                "getAddrDetails": "Y",
                "pageNum": page,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def geocode_first(self, query: str) -> dict[str, Any] | None:
        payload = self.search(query)
        results = payload.get("results", [])
        if not results:
            return None
        query_tokens = set(re.findall(r"[A-Z0-9]+", query.upper()))
        query_block = next(iter(re.findall(r"[A-Z0-9]+", query.upper())), "")
        candidates: list[tuple[float, dict[str, Any], float, float]] = []
        for result in results:
            try:
                latitude = float(result["LATITUDE"])
                longitude = float(result["LONGITUDE"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (1.15 <= latitude <= 1.50 and 103.55 <= longitude <= 104.15):
                continue
            address = str(result.get("ADDRESS", ""))
            address_tokens = set(re.findall(r"[A-Z0-9]+", address.upper()))
            if query_block and query_block not in address_tokens:
                continue
            overlap = len(query_tokens & address_tokens) / max(len(query_tokens), 1)
            candidates.append((overlap, result, latitude, longitude))
        if not candidates:
            return None
        match_score, first, latitude, longitude = max(candidates, key=lambda item: item[0])
        if match_score < 0.5:
            return None
        return {
            "search_query": query,
            "address": first.get("ADDRESS"),
            "postal_code": first.get("POSTAL"),
            "latitude": latitude,
            "longitude": longitude,
            "token_match_score": round(match_score, 3),
        }

    def search_candidates(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Return ranked OneMap place candidates without assuming an HDB block address."""

        clean_query = query.strip()
        if len(clean_query) < 2 or len(clean_query) > 200:
            raise ValueError("location query must contain between 2 and 200 characters")
        if isinstance(limit, bool) or not 1 <= int(limit) <= 10:
            raise ValueError("location candidate limit must be between 1 and 10")

        query_tokens = set(re.findall(r"[A-Z0-9]+", clean_query.upper()))
        payload = self.search(clean_query)
        raw_results = payload.get("results", [])
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[float, float, str]] = set()
        for rank, result in enumerate(raw_results):
            try:
                latitude = float(result["LATITUDE"])
                longitude = float(result["LONGITUDE"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (1.13 <= latitude <= 1.50 and 103.55 <= longitude <= 104.15):
                continue

            def meaningful(value: Any) -> str:
                text = str(value or "").strip()
                return "" if text.upper() in {"NIL", "NA", "N/A"} else text

            building = meaningful(result.get("BUILDING"))
            search_value = meaningful(result.get("SEARCHVAL"))
            road = meaningful(result.get("ROAD_NAME"))
            address = meaningful(result.get("ADDRESS")) or search_value or building or road
            name = building or search_value or road or address
            if not name or not address:
                continue
            dedupe_key = (round(latitude, 6), round(longitude, 6), address.upper())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            searchable = " ".join((name, address, road)).upper()
            result_tokens = set(re.findall(r"[A-Z0-9]+", searchable))
            overlap = len(query_tokens & result_tokens) / max(len(query_tokens), 1)
            query_lower = clean_query.casefold()
            name_lower = name.casefold()
            exact_bonus = 0.25 if name_lower == query_lower else 0.0
            prefix_bonus = 0.1 if name_lower.startswith(query_lower) else 0.0
            provider_rank_bonus = max(0.0, 0.1 - rank * 0.01)
            confidence = min(1.0, overlap * 0.65 + exact_bonus + prefix_bonus + provider_rank_bonus)
            provider_id = hashlib.sha256(
                f"{latitude:.7f}|{longitude:.7f}|{address.upper()}".encode("utf-8")
            ).hexdigest()[:16]
            candidates.append(
                {
                    "id": f"onemap:{provider_id}",
                    "provider": "onemap",
                    "name": name,
                    "address": address,
                    "postal_code": meaningful(result.get("POSTAL")) or None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "confidence": round(confidence, 3),
                }
            )
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        return candidates[: int(limit)]
