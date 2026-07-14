"""Download small, no-key official transport and amenity GeoJSON layers."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from homelens.config import PROJECT_ROOT, load_project_config
from homelens.data.hdb import retrying_session
from homelens.utils import sha256_file, write_json


POLL_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"


def _signed_download_url(
    dataset_id: str,
    session: requests.Session,
    api_key: str = "",
    attempts: int = 5,
) -> str:
    headers = {"x-api-key": api_key} if api_key else {}
    for attempt in range(attempts):
        response = session.get(
            POLL_URL.format(dataset_id=dataset_id), headers=headers, timeout=45
        )
        response.raise_for_status()
        payload = response.json()
        url = payload.get("data", {}).get("url")
        if payload.get("code") == 0 and url:
            return str(url)
        if attempt + 1 < attempts:
            time.sleep(min(2 ** attempt + 1, 12))
    raise RuntimeError(
        f"data.gov.sg did not provide a download URL for {dataset_id}: "
        f"{payload.get('errorMsg', 'unknown error')}"
    )


def download_official_layers(
    output_dir: Path | None = None,
    *,
    api_key: str = "",
    force: bool = False,
    minimum_poll_interval_seconds: float = 5.1,
    session: requests.Session | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    """Download sequentially to respect the public dataset-download rate limit."""

    output_dir = output_dir or PROJECT_ROOT / "data" / "raw" / "official_layers"
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = load_project_config()["official_geospatial_layers"]
    client = session or retrying_session()
    paths: dict[str, Path] = {}
    layers_manifest: dict[str, Any] = {}
    last_poll_time = 0.0

    for name, dataset_id in datasets.items():
        destination = output_dir / f"{name}.geojson"
        if destination.exists() and not force:
            payload = json.loads(destination.read_text(encoding="utf-8"))
            paths[name] = destination
            layers_manifest[name] = {
                "dataset_id": dataset_id,
                "path": str(destination.relative_to(PROJECT_ROOT)),
                "sha256": sha256_file(destination),
                "feature_count": len(payload.get("features", [])),
                "cached": True,
            }
            continue

        elapsed = time.monotonic() - last_poll_time
        if last_poll_time and elapsed < minimum_poll_interval_seconds:
            time.sleep(minimum_poll_interval_seconds - elapsed)
        signed_url = _signed_download_url(dataset_id, client, api_key=api_key)
        last_poll_time = time.monotonic()
        response = client.get(signed_url, timeout=90)
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection" or not isinstance(
            payload.get("features"), list
        ):
            raise RuntimeError(f"{name} did not return a GeoJSON FeatureCollection")
        temporary = destination.with_suffix(".geojson.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(destination)
        paths[name] = destination
        layers_manifest[name] = {
            "dataset_id": dataset_id,
            "path": str(destination.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(destination),
            "feature_count": len(payload["features"]),
            "cached": False,
        }

    manifest = {
        "source": "data.gov.sg public GeoJSON datasets",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "coordinate_order": "longitude, latitude",
        "layers": layers_manifest,
    }
    write_json(PROJECT_ROOT / "artifacts" / "manifests" / "official_layers.json", manifest)
    return paths, manifest
