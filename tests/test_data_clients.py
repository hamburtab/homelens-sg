from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.data.hdb import _complete_download_url  # noqa: E402
from homelens.data.onemap import OneMapClient  # noqa: E402


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads):
        self.payloads = iter(payloads)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return FakeResponse(next(self.payloads))


class DataClientTests(unittest.TestCase):
    @patch("homelens.data.hdb.time.sleep")
    def test_complete_download_polls_until_url_is_ready(self, sleep) -> None:
        session = FakeSession(
            [
                {"code": 0, "data": {}},
                {"code": 0, "data": {}},
                {"code": 0, "data": {"url": "https://download.example/data.csv"}},
            ]
        )
        url = _complete_download_url("dataset", session, 10)
        self.assertEqual(url, "https://download.example/data.csv")
        self.assertEqual(session.calls, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_onemap_selects_a_plausible_singapore_address_match(self) -> None:
        client = OneMapClient(token="test")
        client.search = lambda query: {
            "results": [
                {
                    "ADDRESS": "123 TAMPINES STREET 11",
                    "POSTAL": "000000",
                    "LATITUDE": "40.0",
                    "LONGITUDE": "-74.0",
                },
                {
                    "ADDRESS": "123 TAMPINES STREET 11 SINGAPORE 521123",
                    "POSTAL": "521123",
                    "LATITUDE": "1.345",
                    "LONGITUDE": "103.945",
                },
            ]
        }
        result = client.geocode_first("123 TAMPINES ST 11")
        self.assertEqual(result["postal_code"], "521123")
        self.assertGreaterEqual(result["token_match_score"], 0.5)

    def test_onemap_place_search_returns_ranked_deduplicated_candidates(self) -> None:
        client = OneMapClient(token="test")
        client.search = lambda query: {
            "results": [
                {
                    "SEARCHVAL": "NATIONAL UNIVERSITY OF SINGAPORE",
                    "BUILDING": "NATIONAL UNIVERSITY OF SINGAPORE",
                    "ADDRESS": "21 LOWER KENT RIDGE ROAD SINGAPORE 119077",
                    "POSTAL": "119077",
                    "LATITUDE": "1.2966",
                    "LONGITUDE": "103.7764",
                },
                {
                    "SEARCHVAL": "NATIONAL UNIVERSITY OF SINGAPORE",
                    "BUILDING": "NATIONAL UNIVERSITY OF SINGAPORE",
                    "ADDRESS": "21 LOWER KENT RIDGE ROAD SINGAPORE 119077",
                    "POSTAL": "119077",
                    "LATITUDE": "1.2966",
                    "LONGITUDE": "103.7764",
                },
                {
                    "SEARCHVAL": "OUTSIDE SINGAPORE",
                    "ADDRESS": "OUTSIDE SINGAPORE",
                    "LATITUDE": "40.0",
                    "LONGITUDE": "-74.0",
                },
            ]
        }
        candidates = client.search_candidates("NUS")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["provider"], "onemap")
        self.assertEqual(candidates[0]["postal_code"], "119077")
        self.assertTrue(candidates[0]["id"].startswith("onemap:"))


if __name__ == "__main__":
    unittest.main()
