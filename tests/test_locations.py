from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.config import Settings  # noqa: E402
from homelens.locations import OneMapLocationResolver  # noqa: E402


class RefreshingClient:
    def __init__(self) -> None:
        self.search_calls = 0
        self.authentication_calls = 0

    def search_candidates(self, query, *, limit=5):
        self.search_calls += 1
        if self.search_calls == 1:
            response = requests.Response()
            response.status_code = 401
            raise requests.HTTPError(response=response)
        return [
            {
                "id": "onemap:nus",
                "provider": "onemap",
                "name": "National University of Singapore",
                "address": "21 Lower Kent Ridge Road",
                "postal_code": "119077",
                "latitude": 1.2966,
                "longitude": 103.7764,
                "confidence": 0.9,
            },
            {
                "id": "onemap:outside",
                "provider": "onemap",
                "name": "Outside Singapore",
                "address": "Outside Singapore",
                "postal_code": None,
                "latitude": 40.0,
                "longitude": -74.0,
                "confidence": 0.5,
            },
        ][:limit]

    def authenticate(self, email, password):
        self.authentication_calls += 1
        return "refreshed"


class LocationResolverTests(unittest.TestCase):
    def test_expired_token_refreshes_and_only_singapore_candidates_are_cached(self) -> None:
        settings = replace(
            Settings.from_environment(),
            onemap_token="expired",
            onemap_email="team@example.com",
            onemap_password="secret",
        )
        resolver = OneMapLocationResolver(settings)
        client = RefreshingClient()
        resolver._client = client

        first = resolver.search("NUS")
        second = resolver.search("NUS")

        self.assertEqual(client.authentication_calls, 1)
        self.assertEqual(client.search_calls, 2)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["planning_area"], "QUEENSTOWN")


if __name__ == "__main__":
    unittest.main()
