from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_data import SubzoneIndex, _match_street_area, normalise_address


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProductDataTests(unittest.TestCase):
    def test_address_normalisation_reconciles_common_hdb_abbreviations(self) -> None:
        self.assertEqual(
            normalise_address("552 Ang Mo Kio Avenue 10"),
            normalise_address("552 ANG MO KIO AVE 10"),
        )
        self.assertEqual(
            normalise_address("683B Choa Chu Kang Crescent"),
            normalise_address("683B CHOA CHU KANG CRES"),
        )

    def test_subzone_index_locates_points_without_external_geocoding(self) -> None:
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"PLN_AREA_N": "TEST AREA", "SUBZONE_N": "TEST ZONE"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[103.0, 1.0], [104.0, 1.0], [104.0, 2.0], [103.0, 2.0], [103.0, 1.0]]],
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "subzones.geojson"
            path.write_text(json.dumps(payload), encoding="utf-8")
            index = SubzoneIndex(path)
            self.assertEqual(index.locate(1.5, 103.5), ("TEST AREA", "TEST ZONE"))
            self.assertEqual(index.locate(0.5, 103.5), (None, None))

    def test_street_area_match_supports_project_names_without_inventing_coordinates(self) -> None:
        areas = {
            "YISHUN AVE 6": {
                "planning_area": "YISHUN",
                "subzone": None,
                "town": "YISHUN",
            }
        }
        match = _match_street_area(
            normalise_address("462C Blossom Spring @ Yishun 462C Yishun Avenue 6"),
            areas,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["planning_area"], "YISHUN")

    def test_public_listing_export_excludes_sensitive_and_raw_fields(self) -> None:
        path = PROJECT_ROOT / "map" / "public" / "live-listings.json"
        records = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 14_400)
        forbidden = {
            "raw_listing_text",
            "source_listing_reference",
            "author_name",
            "author_url",
            "review_text",
        }
        self.assertTrue(all(forbidden.isdisjoint(record) for record in records))
        self.assertEqual(len({record["id"] for record in records if record["mode"] == "sale"}), 6_359)
        area_only = [
            record
            for record in records
            if record.get("areaSource") == "historical_hdb_street_match"
        ]
        self.assertGreater(len(area_only), 0)
        self.assertTrue(
            all("latitude" not in record and "longitude" not in record for record in area_only)
        )

    def test_community_profiles_cover_every_boundary_region(self) -> None:
        region_payload = json.loads(
            (PROJECT_ROOT / "map" / "public" / "region-profiles.json").read_text(encoding="utf-8")
        )
        subzone_payload = json.loads(
            (PROJECT_ROOT / "map" / "public" / "subzone-profiles.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(region_payload["profiles"]), 55)
        self.assertEqual(len(subzone_payload["profiles"]), 332)
        for profile in region_payload["profiles"].values():
            self.assertEqual(
                set(profile["dimensions"]),
                {"education", "transport", "food", "shopping", "recreation", "nature"},
            )


if __name__ == "__main__":
    unittest.main()
