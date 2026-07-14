from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.geospatial import enrich_accessibility, haversine_matrix  # noqa: E402


def write_points(path: Path, points: list[tuple[float, float, dict]]) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": properties,
            }
            for longitude, latitude, properties in points
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class GeospatialTests(unittest.TestCase):
    def test_haversine_known_scale(self) -> None:
        distance = haversine_matrix(
            np.array([[1.3, 103.8]]), np.array([[1.3, 103.801]])
        )[0, 0]
        self.assertGreater(distance, 100)
        self.assertLess(distance, 120)

    def test_official_layer_features(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: root / f"{name}.geojson" for name in (
                "mrt_exits", "bus_stops", "hawker_centres", "parks"
            )}
            write_points(paths["mrt_exits"], [(103.8005, 1.3, {"STATION_NA": "TEST MRT"})])
            write_points(
                paths["bus_stops"],
                [(103.8004, 1.3, {}), (103.802, 1.3, {}), (103.82, 1.3, {})],
            )
            write_points(paths["hawker_centres"], [(103.803, 1.3, {"NAME": "TEST HAWKER"})])
            write_points(paths["parks"], [(103.804, 1.3, {"NAME": "TEST PARK"})])
            candidates = pd.DataFrame(
                [{"candidate_id": "one", "latitude": 1.3, "longitude": 103.8}]
            )
            enriched, report = enrich_accessibility(candidates, paths)
            row = enriched.iloc[0]
            self.assertEqual(row["nearest_mrt_name"], "TEST MRT")
            self.assertEqual(row["bus_stops_500m"], 2)
            self.assertEqual(row["amenities_1km"], 2)
            self.assertEqual(report["rows_with_coordinates"], 1)

    def test_empty_official_layer_fails_with_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                name: root / f"{name}.geojson"
                for name in ("mrt_exits", "bus_stops", "hawker_centres", "parks")
            }
            for path in paths.values():
                write_points(path, [(103.8, 1.3, {})])
            write_points(paths["mrt_exits"], [])
            candidates = pd.DataFrame(
                [{"candidate_id": "one", "latitude": 1.3, "longitude": 103.8}]
            )
            with self.assertRaisesRegex(ValueError, "mrt_exits"):
                enrich_accessibility(candidates, paths)


if __name__ == "__main__":
    unittest.main()
