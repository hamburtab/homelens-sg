"""Small OneMap client used by the future geospatial enrichment step."""

from __future__ import annotations

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
