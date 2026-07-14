"""LTA DataMall client with explicit optional-credential behaviour."""

from __future__ import annotations

from typing import Any

import requests

from homelens.errors import MissingCredentialError


class LTADataMallClient:
    BASE_URL = "https://datamall2.mytransport.sg/ltaodataservice"

    def __init__(self, account_key: str = "", timeout_seconds: int = 30) -> None:
        self.account_key = account_key.strip()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "HomeLens-SG/0.1 educational-project",
        })
        if self.account_key:
            self.session.headers.update({"AccountKey": self.account_key})

    @property
    def available(self) -> bool:
        return bool(self.account_key)

    def get_page(self, endpoint: str, skip: int = 0) -> list[dict[str, Any]]:
        if not self.account_key:
            raise MissingCredentialError(
                "LTA DataMall is not configured. Add LTA_ACCOUNT_KEY to .env first."
            )
        response = self.session.get(
            f"{self.BASE_URL}/{endpoint.lstrip('/')}",
            params={"$skip": skip},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("value", [])

    def get_all(self, endpoint: str, page_size: int = 500) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        skip = 0
        while True:
            page = self.get_page(endpoint, skip=skip)
            rows.extend(page)
            if len(page) < page_size:
                return rows
            skip += len(page)

    def bus_stops(self) -> list[dict[str, Any]]:
        return self.get_all("BusStops")
