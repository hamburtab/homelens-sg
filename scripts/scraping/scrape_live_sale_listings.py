from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_LISTINGS_DIR = PROJECT_ROOT / "data" / "raw" / "listings" / "propertyguru"
INTERIM_LISTINGS_DIR = PROJECT_ROOT / "data" / "interim" / "listings"

OUTPUT_FILE = RAW_LISTINGS_DIR / "live_sale_listings.csv"
GEOCODE_CACHE_FILE = INTERIM_LISTINGS_DIR / "live_sale_listing_geocode_cache.json"

DEFAULT_START_URL = "https://www.propertyguru.com.sg/hdb-for-sale"
ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"

OUTPUT_COLUMNS = [
    "listing_id",
    "source",
    "source_listing_reference",
    "title",
    "asking_price",
    "price_psf",
    "address",
    "property_type",
    "bedrooms",
    "bathrooms",
    "floor_area_sqft",
    "tenure",
    "built_year",
    "nearest_mrt_name",
    "nearest_mrt_distance_m",
    "listed_on_text",
    "scraped_at",
    "latitude",
    "longitude",
    "raw_listing_text",
]


class PropertyGuruAccessError(RuntimeError):
    """Raised when PropertyGuru's edge protection rejects the request."""


def load_cache() -> dict[str, dict]:
    if not GEOCODE_CACHE_FILE.exists():
        return {}

    with GEOCODE_CACHE_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_cache(cache: dict[str, dict]) -> None:
    GEOCODE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    with GEOCODE_CACHE_FILE.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def make_listing_id(source_url: str, address: str, asking_price: int | None) -> str:
    key = f"{source_url}|{address}|{asking_price}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def parse_price(text: str) -> int | None:
    match = re.search(r"S\$\s*([\d,]+)(?!\s*(?:/mo|psf))", text, flags=re.I)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_price_psf(text: str) -> float | None:
    match = re.search(r"S\$\s*([\d,]+(?:\.\d+)?)\s*psf", text, flags=re.I)

    if not match:
        return None

    return float(match.group(1).replace(",", ""))


def parse_area(text: str) -> int | None:
    match = re.search(r"([\d,]+)\s*sqft", text, flags=re.I)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_mrt(text: str) -> tuple[str | None, float | None]:
    match = re.search(
        r"(?P<minutes>\d+)\s*min\s*\((?P<distance>[\d.]+)\s*"
        r"(?P<unit>m|km)\)\s*from\s*(?P<station>.+?)"
        r"(?:\s+Listed on|\s+Contact Agent|$)",
        text,
        flags=re.I,
    )

    if not match:
        return None, None

    distance = float(match.group("distance"))

    if match.group("unit").lower() == "km":
        distance *= 1000

    return clean_text(match.group("station")), round(distance, 2)


def parse_listed_on(text: str) -> str | None:
    match = re.search(
        r"Listed on\s+(.+?)(?:\s+Contact Agent|\s+WhatsApp|$)",
        text,
        flags=re.I,
    )

    if not match:
        return None

    return clean_text(match.group(1))


def parse_address(text: str) -> str | None:
    price_prefix = (
        r"S\$\s*[\d,]+"
        r"(?:\s+S\$\s*[\d,]+(?:\.\d+)?\s*psf)?\s+"
    )
    duplicate_match = re.search(
        price_prefix + r"(?P<address>.+?)\s+(?P=address)\b",
        text,
        flags=re.I,
    )

    if duplicate_match:
        return clean_text(duplicate_match.group("address"))

    fallback_match = re.search(
        price_prefix
        + r"(?P<address>.+?)\s+"
        + r"(?:\d+\s+(?:Beds?\s+)?\d+\s+(?:Baths?\s+)?[\d,]+\s*sqft|"
        + r"[\d,]+\s*sqft|HDB Flat)",
        text,
        flags=re.I,
    )

    if fallback_match:
        return clean_text(fallback_match.group("address"))

    return None


def parse_title(text: str, asking_price: int | None, address: str | None) -> str | None:
    if asking_price is None:
        return None

    title = re.split(r"S\$\s*[\d,]+", text, maxsplit=1)[0]
    title = clean_text(title)

    if not title and address:
        return address

    return title or None


def parse_bedrooms_bathrooms(text: str, address: str | None) -> tuple[int | None, int | None]:
    labelled_match = re.search(
        r"(?P<bedrooms>\d+)\s*Beds?\b.*?(?P<bathrooms>\d+)\s*Baths?\b",
        text,
        flags=re.I,
    )

    if labelled_match:
        return int(labelled_match.group("bedrooms")), int(labelled_match.group("bathrooms"))

    search_text = text

    if address:
        duplicated_address = re.search(
            rf"{re.escape(address)}\s+{re.escape(address)}\s+(?P<details>.+)",
            text,
            flags=re.I,
        )
        if duplicated_address:
            search_text = duplicated_address.group("details")

    compact_match = re.search(
        r"(?P<bedrooms>\d+)\s+(?P<bathrooms>\d+)\s+[\d,]+\s*sqft",
        search_text,
        flags=re.I,
    )

    if not compact_match:
        return None, None

    return int(compact_match.group("bedrooms")), int(compact_match.group("bathrooms"))


def parse_property_type(text: str) -> str | None:
    for property_type in [
        "Executive Maisonette",
        "Executive Apartment",
        "Jumbo Flat",
        "DBSS",
        "HDB Flat",
    ]:
        if re.search(rf"\b{re.escape(property_type)}\b", text, flags=re.I):
            return property_type

    return None


def parse_tenure(text: str) -> str | None:
    match = re.search(
        r"\b((?:\d+-year\s+)?Leasehold|Freehold)\b",
        text,
        flags=re.I,
    )

    if not match:
        return None

    return clean_text(match.group(1))


def parse_built_year(text: str) -> int | None:
    match = re.search(r"Built:\s*(\d{4})", text, flags=re.I)

    if not match:
        return None

    return int(match.group(1))


def parse_listing_reference(source_url: str) -> str | None:
    match = re.search(r"-(\d+)(?:/)?(?:\?.*)?$", source_url)

    if not match:
        return None

    return match.group(1)


def listing_links_from_page(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html5lib")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" "))

        if not re.search(r"S\$\s*[\d,]+", text) or "/mo" in text.lower():
            continue

        href = urljoin(base_url, anchor["href"])
        path = urlparse(href).path.lower()

        if (
            not any(segment in path for segment in ("/listing/", "/property-listing/"))
            or parse_listing_reference(href) is None
            or href in seen
        ):
            continue

        seen.add(href)
        links.append((href, text))

    return links


def parse_propertyguru_listing(
    source_page_url: str,
    source_url: str,
    text: str,
) -> dict | None:
    asking_price = parse_price(text)
    address = parse_address(text)

    if asking_price is None or address is None:
        return None

    bedrooms, bathrooms = parse_bedrooms_bathrooms(text, address)
    nearest_mrt_name, nearest_mrt_distance_m = parse_mrt(text)

    return {
        "listing_id": make_listing_id(source_url, address, asking_price),
        "source": "PropertyGuru",
        "source_page_url": source_page_url,
        "source_url": source_url,
        "source_listing_reference": parse_listing_reference(source_url),
        "title": parse_title(text, asking_price, address),
        "asking_price": asking_price,
        "price_psf": parse_price_psf(text),
        "address": address,
        "property_type": parse_property_type(text),
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "floor_area_sqft": parse_area(text),
        "tenure": parse_tenure(text),
        "built_year": parse_built_year(text),
        "nearest_mrt_name": nearest_mrt_name,
        "nearest_mrt_distance_m": nearest_mrt_distance_m,
        "listed_on_text": parse_listed_on(text),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "latitude": pd.NA,
        "longitude": pd.NA,
        "raw_listing_text": text,
    }


def _feature_text(listing_data: dict, automation_id: str) -> str | None:
    features = listing_data.get("listingFeatures", [])

    for feature in features:
        items = feature if isinstance(feature, list) else [feature]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("dataAutomationId") == automation_id:
                value = item.get("text")
                return clean_text(str(value)) if value is not None else None

    return None


def parse_next_data_listing(
    source_page_url: str,
    item: dict,
    raw_text_by_url: dict[str, str],
) -> dict | None:
    listing_data = item.get("listingData", {})
    source_url = listing_data.get("url")
    address = listing_data.get("fullAddress") or listing_data.get("localizedTitle")
    price_data = listing_data.get("price", {})
    asking_price = price_data.get("value")

    if not source_url or not address or asking_price is None:
        return None

    try:
        asking_price = int(asking_price)
    except (TypeError, ValueError):
        return None

    raw_text = raw_text_by_url.get(source_url, "")
    mrt_text = listing_data.get("mrt", {}).get("nearbyText", "")
    nearest_mrt_name, nearest_mrt_distance_m = parse_mrt(mrt_text)
    price_psf_text = (
        listing_data.get("pricePerArea", {}).get("localeStringValue")
        or listing_data.get("psfText", "")
    )
    tenure = _feature_text(listing_data, "listing-card-v2-tenure")
    built_text = _feature_text(listing_data, "listing-card-v2-build-year")
    recency_text = listing_data.get("recency", {}).get("text", "")
    listed_on_text = re.sub(r"^Listed on\s+", "", recency_text, flags=re.I) or None
    agent_description = listing_data.get("agent", {}).get("description")

    if not tenure:
        tenure = parse_tenure(raw_text)

    return {
        "listing_id": make_listing_id(source_url, str(address), asking_price),
        "source": "PropertyGuru",
        "source_page_url": source_page_url,
        "source_url": source_url,
        "source_listing_reference": str(listing_data.get("id") or "") or None,
        "title": clean_text(str(agent_description)) if agent_description else str(address),
        "asking_price": asking_price,
        "price_psf": parse_price_psf(str(price_psf_text)),
        "address": clean_text(str(address)),
        "property_type": (
            listing_data.get("property", {}).get("subTypeText")
            or _feature_text(listing_data, "listing-card-v2-unit-type")
        ),
        "bedrooms": listing_data.get("bedrooms"),
        "bathrooms": listing_data.get("bathrooms"),
        "floor_area_sqft": listing_data.get("floorArea"),
        "tenure": tenure,
        "built_year": parse_built_year(built_text or raw_text),
        "nearest_mrt_name": nearest_mrt_name,
        "nearest_mrt_distance_m": nearest_mrt_distance_m,
        "listed_on_text": clean_text(listed_on_text) if listed_on_text else None,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "latitude": pd.NA,
        "longitude": pd.NA,
        "raw_listing_text": raw_text,
    }


def parse_saved_page(html: str, source_page_url: str) -> list[dict]:
    raw_text_by_url = dict(listing_links_from_page(html, source_page_url))
    soup = BeautifulSoup(html, "html5lib")
    next_data_node = soup.find("script", id="__NEXT_DATA__")

    if next_data_node is not None and next_data_node.string:
        try:
            next_data = json.loads(next_data_node.string)
            items = next_data["props"]["pageProps"]["pageData"]["data"]["listingsData"]
        except (KeyError, TypeError, json.JSONDecodeError):
            items = []

        parsed = [
            parse_next_data_listing(source_page_url, item, raw_text_by_url)
            for item in items
        ]
        listings = [listing for listing in parsed if listing is not None]

        if listings:
            return listings

    parsed = [
        parse_propertyguru_listing(source_page_url, source_url, text)
        for source_url, text in raw_text_by_url.items()
    ]
    return [listing for listing in parsed if listing is not None]


def parse_saved_markdown(markdown: str, source_page_url: str) -> list[dict]:
    listings_section = markdown.split("## Property Listings", 1)

    if len(listings_section) != 2:
        return []

    listings_text = listings_section[1].split("\n## ", 1)[0]
    blocks = re.split(r"(?m)^###\s+", listings_text)
    listings: list[dict] = []

    for block in blocks[1:]:
        heading, _, body = block.partition("\n")
        source_url_match = re.search(
            r"\*\*Detail Link\*\*:\s*\[(https://www\.propertyguru\.com\.sg/listing/[^\]]+)\]",
            body,
        )
        address_match = re.search(r"(?m)^- \*\*Address\*\*:\s*(.+)$", body)
        price_match = re.search(r"(?m)^- \*\*Price\*\*:\s*S\$\s*([\d,]+)", body)
        features_match = re.search(
            r"(?ms)^- \*\*Features\*\*:\s*\n(?P<items>.*?)(?=^- \*\*|\Z)",
            body,
        )

        if not source_url_match or not price_match:
            continue

        source_url = source_url_match.group(1)
        address = (
            clean_text(address_match.group(1))
            if address_match
            else clean_text(heading)
        )
        asking_price = int(price_match.group(1).replace(",", ""))
        features = []

        if features_match:
            features = [
                clean_text(value)
                for value in re.findall(r"(?m)^\s+-\s+(.+)$", features_match.group("items"))
            ]

        bedrooms = int(features[0]) if len(features) > 0 and features[0].isdigit() else None
        bathrooms = int(features[1]) if len(features) > 1 and features[1].isdigit() else None
        area_text = next((value for value in features if re.search(r"\bsqft\b", value, re.I)), "")
        floor_area_sqft = parse_area(area_text)
        property_type = next(
            (value for value in features if value in {"HDB Flat", "DBSS", "Jumbo Flat"}),
            "HDB Flat",
        )
        tenure = next(
            (value for value in features if re.search(r"Leasehold|Freehold", value, re.I)),
            None,
        )
        built_text = next((value for value in features if value.startswith("Built:")), "")
        nearest_match = re.search(
            r"(?m)^- \*\*Nearest Train Station\*\*:\s*(.+)$",
            body,
        )
        nearest_text = clean_text(nearest_match.group(1)) if nearest_match else ""
        nearest_mrt_name, nearest_mrt_distance_m = parse_mrt(nearest_text)
        listed_on_match = re.search(r"(?m)^- Listed on\s+(.+)$", body)
        description_match = re.search(
            r"(?m)^\s+- \*\*Description\*\*:\s*(.+)$",
            body,
        )
        title = (
            clean_text(description_match.group(1))
            if description_match
            else clean_text(heading)
        )
        price_psf = (
            round(asking_price / floor_area_sqft, 2)
            if floor_area_sqft
            else None
        )
        raw_listing_text = clean_text(
            " ".join(
                value
                for value in [
                    title,
                    f"S$ {asking_price:,}",
                    f"S$ {price_psf:,.2f} psf" if price_psf is not None else "",
                    address,
                    str(bedrooms) if bedrooms is not None else "",
                    str(bathrooms) if bathrooms is not None else "",
                    area_text,
                    property_type,
                    tenure or "",
                    built_text,
                    nearest_text,
                    (
                        f"Listed on {clean_text(listed_on_match.group(1))}"
                        if listed_on_match
                        else ""
                    ),
                ]
                if value
            )
        )

        listings.append(
            {
                "listing_id": make_listing_id(source_url, address, asking_price),
                "source": "PropertyGuru",
                "source_page_url": source_page_url,
                "source_url": source_url,
                "source_listing_reference": parse_listing_reference(source_url),
                "title": title,
                "asking_price": asking_price,
                "price_psf": price_psf,
                "address": address,
                "property_type": property_type,
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "floor_area_sqft": floor_area_sqft,
                "tenure": tenure,
                "built_year": parse_built_year(built_text),
                "nearest_mrt_name": nearest_mrt_name,
                "nearest_mrt_distance_m": nearest_mrt_distance_m,
                "listed_on_text": (
                    clean_text(listed_on_match.group(1)) if listed_on_match else None
                ),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "latitude": pd.NA,
                "longitude": pd.NA,
                "raw_listing_text": raw_listing_text,
            }
        )

    return listings


def source_page_url_from_saved_path(path: Path) -> str:
    match = re.search(r"(?:page|markdown)_(\d+)\.(?:html|md)$", path.name, flags=re.I)

    if not match or match.group(1) == "1":
        return DEFAULT_START_URL

    return f"{DEFAULT_START_URL}/{match.group(1)}"


def fetch_page(
    session: requests.Session,
    url: str,
    max_retries: int,
    rate_limit_wait_seconds: float,
    jitter_seconds: float,
) -> str | None:
    for attempt in range(1, max_retries + 1):
        response = session.get(url, timeout=30)

        if response.status_code == 403:
            mitigated = response.headers.get("cf-mitigated", "").lower() == "challenge"
            reason = "Cloudflare challenge" if mitigated else "HTTP 403"
            raise PropertyGuruAccessError(
                f"PropertyGuru rejected {url} ({reason}). "
                "The approved access method or IP allowlist is not active for this request."
            )

        if response.status_code != 429:
            response.raise_for_status()
            return response.text

        retry_after = response.headers.get("Retry-After")
        wait_seconds = (
            float(retry_after)
            if retry_after and retry_after.isdigit()
            else rate_limit_wait_seconds * attempt
        )
        wait_seconds += random.uniform(0, jitter_seconds)
        print(
            f"Got 429 Too Many Requests. Waiting {wait_seconds:.1f}s "
            f"before retry {attempt}/{max_retries}."
        )
        time.sleep(wait_seconds)

    print(f"Skipped after repeated 429 responses: {url}")
    return None


def geocode_address(
    session: requests.Session,
    address: str,
    token: str,
) -> dict[str, float | None]:
    response = session.get(
        ONEMAP_SEARCH_URL,
        params={
            "searchVal": f"{address} SINGAPORE",
            "returnGeom": "Y",
            "getAddrDetails": "Y",
            "pageNum": 1,
        },
        headers={"Authorization": token},
        timeout=30,
    )
    response.raise_for_status()

    results = response.json().get("results", [])

    if not results:
        return {"latitude": None, "longitude": None}

    first = results[0]
    latitude = first.get("LATITUDE")
    longitude = first.get("LONGITUDE")

    if latitude is None or longitude is None:
        return {"latitude": None, "longitude": None}

    return {"latitude": float(latitude), "longitude": float(longitude)}


def add_coordinates(
    listings: list[dict],
    token: str | None,
    delay_seconds: float,
) -> list[dict]:
    if not token:
        print("ONEMAP_TOKEN not found; latitude and longitude will stay blank.")
        return listings

    cache = load_cache()
    session = requests.Session()

    for listing in listings:
        address = listing.get("address")

        if not address:
            continue

        cached = cache.get(address)

        if cached is None:
            try:
                cached = geocode_address(session=session, address=address, token=token)
                cache[address] = cached
                time.sleep(delay_seconds)
            except requests.RequestException as error:
                print(f"Failed to geocode {address}: {error}")
                continue

        listing["latitude"] = cached.get("latitude")
        listing["longitude"] = cached.get("longitude")

    save_cache(cache)
    return listings


def scrape_propertyguru_page(
    start_url: str,
    page_number: int,
    max_retries: int,
    rate_limit_wait_seconds: float,
    jitter_seconds: float,
) -> list[dict]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 compatible; NUSWebMiningProject/0.1; "
                "educational data collection"
            )
        }
    )
    page_url = start_url if page_number == 1 else f"{start_url}/{page_number}"
    print(f"Fetching: {page_url}")
    html = fetch_page(
        session=session,
        url=page_url,
        max_retries=max_retries,
        rate_limit_wait_seconds=rate_limit_wait_seconds,
        jitter_seconds=jitter_seconds,
    )

    if html is None:
        return []

    listings: list[dict] = []
    seen_ids: set[str] = set()

    for source_url, text in listing_links_from_page(html, page_url):
        listing = parse_propertyguru_listing(page_url, source_url, text)

        if listing is None or listing["listing_id"] in seen_ids:
            continue

        seen_ids.add(listing["listing_id"])
        listings.append(listing)

    return listings


def save_listings(listings: list[dict], output_file: Path, append: bool) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if not listings and output_file.exists():
        print(f"No new listings were scraped; keeping existing file: {output_file}")
        return

    df = pd.DataFrame(listings)

    if append and output_file.exists():
        try:
            existing = pd.read_csv(output_file)
        except pd.errors.EmptyDataError:
            existing = pd.DataFrame(columns=OUTPUT_COLUMNS)

        if existing.empty and not set(OUTPUT_COLUMNS).issubset(existing.columns):
            existing = pd.DataFrame(columns=OUTPUT_COLUMNS)

        df = pd.concat([existing, df], ignore_index=True)

    if "listing_id" in df.columns:
        df = df.drop_duplicates("listing_id", keep="last")

    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA

    df[OUTPUT_COLUMNS].to_csv(output_file, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a one-time scrape of public live HDB sale listings.",
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="PropertyGuru HDB sale search URL.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of result pages to fetch from --start-page.",
    )
    parser.add_argument("--start-page", type=int, default=1, help="First result page.")
    parser.add_argument(
        "--html-file",
        action="append",
        type=Path,
        default=[],
        help="Import a Safari-saved PropertyGuru HTML or Markdown page instead of requesting it.",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=2.0,
        help="Delay in seconds between PropertyGuru page requests.",
    )
    parser.add_argument(
        "--geocode-delay",
        type=float,
        default=2.0,
        help="Delay in seconds between OneMap requests.",
    )
    parser.add_argument("--output-file", type=Path, default=OUTPUT_FILE, help="CSV path.")
    parser.add_argument("--skip-geocode", action="store_true", help="Skip OneMap geocoding.")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append and deduplicate instead of replacing the CSV.",
    )
    parser.add_argument("--max-retries", type=int, default=5, help="Retries after HTTP 429.")
    parser.add_argument(
        "--rate-limit-wait",
        type=float,
        default=120.0,
        help="Base wait seconds after HTTP 429.",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=3.0,
        help="Random extra delay between requests.",
    )
    return parser.parse_args()


def load_env() -> None:
    env_file = PROJECT_ROOT / ".env"

    if load_dotenv is not None:
        load_dotenv(env_file, encoding="utf-8-sig")
        return

    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> int:
    args = parse_args()
    load_env()

    if args.html_file:
        imported_listings: list[dict] = []

        for html_file in args.html_file:
            html = html_file.read_text(encoding="utf-8", errors="replace")
            source_page_url = source_page_url_from_saved_path(html_file)
            listings = (
                parse_saved_markdown(html, source_page_url)
                if html_file.suffix.lower() == ".md"
                else parse_saved_page(html, source_page_url)
            )

            if not listings:
                print(f"No listings parsed from saved page: {html_file}")
                continue

            imported_listings.extend(listings)
            print(f"Imported {len(listings):,} listings from {html_file}")

        if imported_listings and not args.skip_geocode:
            imported_listings = add_coordinates(
                listings=imported_listings,
                token=os.getenv("ONEMAP_TOKEN"),
                delay_seconds=args.geocode_delay,
            )

        if imported_listings:
            save_listings(
                imported_listings,
                args.output_file,
                append=args.append,
            )

        print(f"Listings imported this run: {len(imported_listings):,}")
        print(f"Output file: {args.output_file}")
        return 0

    end_page = args.start_page + args.pages - 1
    total_scraped = 0

    for page_number in range(args.start_page, end_page + 1):
        try:
            listings = scrape_propertyguru_page(
                start_url=args.start_url.rstrip("/"),
                page_number=page_number,
                max_retries=args.max_retries,
                rate_limit_wait_seconds=args.rate_limit_wait,
                jitter_seconds=args.jitter,
            )
        except PropertyGuruAccessError as error:
            print(f"Access blocked: {error}")
            return 2

        if not listings:
            print(f"No listings were parsed; stopping at page {page_number}.")
            break

        if not args.skip_geocode:
            listings = add_coordinates(
                listings=listings,
                token=os.getenv("ONEMAP_TOKEN"),
                delay_seconds=args.geocode_delay,
            )

        save_listings(
            listings,
            args.output_file,
            append=args.append or page_number > args.start_page,
        )
        total_scraped += len(listings)
        print(
            f"Saved page {page_number}; new listings this page: {len(listings):,}; "
            f"new listings this run: {total_scraped:,}"
        )

        if page_number < end_page:
            time.sleep(args.page_delay + random.uniform(0, args.jitter))

    print(f"Listings scraped this run: {total_scraped:,}")
    print(f"Output file: {args.output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
