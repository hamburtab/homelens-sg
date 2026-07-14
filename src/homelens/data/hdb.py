"""Download and snapshot official HDB resale transaction records."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import time
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from homelens.config import PROJECT_ROOT, ensure_output_directories, load_project_config
from homelens.errors import DataSchemaError
from homelens.utils import sha256_file, write_json


DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"
INITIATE_DOWNLOAD_URL = (
    "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/initiate-download"
)
POLL_DOWNLOAD_URL = (
    "https://api-open.data.gov.sg/v1/public/api/datasets/{dataset_id}/poll-download"
)
REQUIRED_FIELDS = (
    "month",
    "town",
    "flat_type",
    "block",
    "street_name",
    "storey_range",
    "floor_area_sqm",
    "flat_model",
    "lease_commence_date",
    "remaining_lease",
    "resale_price",
)


def retrying_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "HomeLens-SG/0.1 educational-project"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def validate_source_fields(field_names: list[str] | tuple[str, ...] | set[str]) -> None:
    missing = sorted(set(REQUIRED_FIELDS) - set(field_names))
    if missing:
        raise DataSchemaError(
            "HDB source schema changed; missing required field(s): " + ", ".join(missing)
        )


def latest_hdb_snapshot(raw_dir: Path | None = None) -> Path | None:
    directory = raw_dir or PROJECT_ROOT / "data" / "raw"
    snapshots = sorted(directory.glob("hdb_resale_*.csv"), reverse=True)
    return snapshots[0] if snapshots else None


def _complete_download_url(
    resource_id: str, client: requests.Session, timeout_seconds: int
) -> str:
    api_key = os.getenv("DATA_GOV_SG_API_KEY", "").strip()
    headers = {"x-api-key": api_key} if api_key else {}
    response = client.get(
        INITIATE_DOWNLOAD_URL.format(dataset_id=resource_id),
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    last_payload: dict[str, Any] = response.json()
    url = last_payload.get("data", {}).get("url")
    if last_payload.get("code") == 0 and url:
        return str(url)

    # Dataset files may be prepared asynchronously. Poll slowly enough to stay
    # below the public dataset-download limit (two requests per ten seconds).
    for _ in range(12):
        time.sleep(5.1)
        response = client.get(
            POLL_DOWNLOAD_URL.format(dataset_id=resource_id),
            headers=headers,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        last_payload = response.json()
        url = last_payload.get("data", {}).get("url")
        if last_payload.get("code") == 0 and url:
            return str(url)
    raise RuntimeError(
        "data.gov.sg did not provide a complete-download URL: "
        + str(last_payload.get("errorMsg", "unknown error"))
    )


def download_hdb_snapshot(
    output_path: Path | None = None,
    *,
    dataset_id: str | None = None,
    page_size: int | None = None,
    max_records: int | None = None,
    timeout_seconds: int = 60,
    session: requests.Session | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Download records page by page and create a versioned raw snapshot.

    `max_records` is intended for rapid experiments. Limited snapshots are sorted
    by month descending so they contain recent rather than 2017-era records.
    """

    ensure_output_directories()
    config = load_project_config()
    resource_id = dataset_id or config["hdb_dataset_id"]
    size = int(page_size or config["download_page_size"])
    if size <= 0:
        raise ValueError("page_size must be positive")
    if max_records is not None and max_records <= 0:
        raise ValueError("max_records must be positive")

    now = datetime.now(timezone.utc)
    if output_path is None:
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        output_path = PROJECT_ROOT / "data" / "raw" / f"hdb_resale_{stamp}.csv"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    client = session or retrying_session()
    source_total: int | None = None
    if max_records is None:
        signed_url = _complete_download_url(resource_id, client, timeout_seconds)
        response = client.get(signed_url, timeout=max(timeout_seconds, 120), stream=True)
        response.raise_for_status()
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        temporary.replace(output_path)
        frame = pd.read_csv(output_path, low_memory=False)
        validate_source_fields(frame.columns.tolist())
        source_total = len(frame)
    else:
        records: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        offset = 0
        while True:
            requested = min(size, max_records - len(records))
            if requested <= 0:
                break
            params: dict[str, Any] = {
                "resource_id": resource_id,
                "limit": requested,
                "offset": offset,
                "sort": "month desc,_id desc",
            }
            response = client.get(DATASTORE_URL, params=params, timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success") or not isinstance(payload.get("result"), dict):
                raise RuntimeError("data.gov.sg returned an unsuccessful response")
            result = payload["result"]
            page = result.get("records", [])
            source_total = int(result.get("total", len(page)))
            source_fields = [field["id"] for field in result.get("fields", []) if "id" in field]
            validate_source_fields(source_fields)
            if not page:
                break
            for record in page:
                record_id = record.get("_id")
                if record_id is not None and record_id in seen_ids:
                    continue
                if record_id is not None:
                    seen_ids.add(record_id)
                records.append(record)
                if len(records) >= max_records:
                    break
            offset += len(page)
            if len(page) < requested or offset >= source_total:
                break
        if not records:
            raise RuntimeError("No HDB records were downloaded")
        frame = pd.DataFrame.from_records(records)
        validate_source_fields(frame.columns.tolist())
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        frame.to_csv(temporary, index=False)
        temporary.replace(output_path)

    manifest = {
        "source": "data.gov.sg — Resale Flat Prices (Based on Registration Date), From Jan 2017",
        "source_url": f"https://data.gov.sg/api/action/datastore_search?resource_id={resource_id}",
        "dataset_id": resource_id,
        "downloaded_at_utc": now.isoformat(),
        "snapshot_path": str(output_path.relative_to(PROJECT_ROOT)),
        "sha256": sha256_file(output_path),
        "rows_downloaded": int(len(frame)),
        "source_total_rows": source_total,
        "is_complete_snapshot": max_records is None and len(frame) == source_total,
        "requested_max_records": max_records,
        "fields": frame.columns.tolist(),
        "minimum_month": str(frame["month"].min()),
        "maximum_month": str(frame["month"].max()),
    }
    manifest_path = PROJECT_ROOT / "artifacts" / "manifests" / "hdb_snapshot.json"
    write_json(manifest_path, manifest)
    return output_path, manifest


def demo_hdb_frame() -> pd.DataFrame:
    """Return deterministic HDB-shaped data for offline demos and tests."""

    profiles = [
        ("ANG MO KIO", "406", "ANG MO KIO AVE 10", "4 ROOM", 92, "Model A", 1987, 550000),
        ("TAMPINES", "123", "TAMPINES ST 11", "4 ROOM", 104, "Model A", 1998, 590000),
        ("WOODLANDS", "888", "WOODLANDS DR 50", "5 ROOM", 120, "Improved", 2001, 610000),
        ("JURONG WEST", "510", "JURONG WEST ST 52", "4 ROOM", 95, "Model A", 1995, 480000),
        ("QUEENSTOWN", "22", "DOVER CRES", "3 ROOM", 67, "New Generation", 1980, 490000),
        ("PUNGGOL", "301A", "PUNGGOL CTRL", "4 ROOM", 93, "Premium Apartment", 2015, 620000),
        ("SENGKANG", "205", "SENGKANG EAST WAY", "5 ROOM", 112, "Improved", 2011, 670000),
        ("TOA PAYOH", "80", "LOR 4 TOA PAYOH", "4 ROOM", 90, "Improved", 1979, 600000),
    ]
    records: list[dict[str, Any]] = []
    record_id = 1
    for month_index, month in enumerate(pd.period_range("2024-01", "2025-12", freq="M")):
        for profile_index, profile in enumerate(profiles):
            town, block, street, flat_type, area, model, lease_start, base_price = profile
            price = base_price + month_index * 1650 + ((profile_index * 7 + month_index) % 5 - 2) * 3200
            remaining_months = max(1, 99 * 12 - ((month.year - lease_start) * 12 + month.month - 1))
            years, months = divmod(remaining_months, 12)
            lower_storey = 1 + 3 * ((profile_index + month_index) % 5)
            records.append(
                {
                    "month": str(month),
                    "town": town,
                    "flat_type": flat_type,
                    "block": block,
                    "street_name": street,
                    "storey_range": f"{lower_storey:02d} TO {lower_storey + 2:02d}",
                    "floor_area_sqm": area + ((month_index + profile_index) % 2),
                    "flat_model": model,
                    "lease_commence_date": lease_start,
                    "remaining_lease": f"{years} years {months:02d} months",
                    "resale_price": int(price),
                    "_id": record_id,
                }
            )
            record_id += 1

    return pd.DataFrame(records)


def create_demo_snapshot(output_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Create a deterministic offline dataset with the official source schema."""

    ensure_output_directories()
    output_path = output_path or PROJECT_ROOT / "data" / "raw" / "hdb_resale_fixture.csv"
    frame = demo_hdb_frame()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    manifest = {
        "source": "deterministic offline fixture shaped like the official HDB dataset",
        "dataset_id": "fixture",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_path": (
            str(output_path.relative_to(PROJECT_ROOT))
            if output_path.is_relative_to(PROJECT_ROOT)
            else str(output_path)
        ),
        "sha256": sha256_file(output_path),
        "rows_downloaded": len(frame),
        "source_total_rows": len(frame),
        "is_complete_snapshot": True,
        "fields": frame.columns.tolist(),
        "minimum_month": str(frame["month"].min()),
        "maximum_month": str(frame["month"].max()),
    }
    write_json(PROJECT_ROOT / "artifacts" / "manifests" / "hdb_snapshot.json", manifest)
    return output_path, manifest
