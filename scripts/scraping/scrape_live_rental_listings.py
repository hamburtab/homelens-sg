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
from urllib.parse import urljoin

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

OUTPUT_FILE = RAW_LISTINGS_DIR / "live_rental_listings.csv"
GEOCODE_CACHE_FILE = INTERIM_LISTINGS_DIR / "live_rental_listing_geocode_cache.json"

DEFAULT_START_URL = "https://www.propertyguru.com.sg/hdb-for-rent"
ONEMAP_SEARCH_URL = "https://www.onemap.gov.sg/api/common/elastic/search"

OUTPUT_COLUMNS = [
    "listing_id",
    "source",
    "source_listing_reference",
    "title",
    "price_monthly",
    "address",
    "property_type",
    "room_type",
    "floor_area_sqft",
    "nearest_mrt_name",
    "nearest_mrt_distance_m",
    "listed_on_text",
    "scraped_at",
    "latitude",
    "longitude",
    "raw_listing_text",
]


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


def make_listing_id(source_url: str, address: str, price_monthly: int | None) -> str:
    key = f"{source_url}|{address}|{price_monthly}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def parse_price(text: str) -> int | None:
    match = re.search(r"S\$\s*([\d,]+)\s*/mo", text, flags=re.I)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_area(text: str) -> int | None:
    match = re.search(r"([\d,]+)\s*sqft", text, flags=re.I)

    if not match:
        return None

    return int(match.group(1).replace(",", ""))


def parse_mrt(text: str) -> tuple[str | None, float | None]:
    match = re.search(
        r"(?P<minutes>\d+)\s*min\s*\((?P<distance>[\d.]+)\s*(?P<unit>m|km)\)\s*from\s*(?P<station>.+?)(?:\s+Listed on|\s+Contact Agent|$)",
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


def parse_room_type(text: str) -> str | None:
    for room_type in [
        "Master Room",
        "Common Room",
        "Room Rental",
        "Room",
    ]:
        if re.search(rf"\b{re.escape(room_type)}\b", text, flags=re.I):
            return room_type

    return None


def parse_address(text: str) -> str | None:
    match = re.search(
        r"/mo(?:\s+S\$\s*[\d,.]+\s*psf)?\s+(.+?)\s+\1\b",
        text,
        flags=re.I,
    )

    if match:
        return clean_text(match.group(1))

    match = re.search(
        r"/mo(?:\s+S\$\s*[\d,.]+\s*psf)?\s+(.+?)\s+(?:Common Room|Master Room|Room|[\d]+\s+[\d]+\s+[\d,]+\s*sqft|[\d,]+\s*sqft|HDB Flat)",
        text,
        flags=re.I,
    )

    if match:
        return clean_text(match.group(1))

    return None


def parse_title(text: str, price_monthly: int | None, address: str | None) -> str | None:
    if price_monthly is None:
        return None

    marker = f"S$ {price_monthly:,} /mo"
    title = text.split(marker, 1)[0]

    if title == text:
        title = re.split(r"S\$\s*[\d,]+\s*/mo", text, maxsplit=1)[0]

    title = clean_text(title)

    if not title and address:
        return address

    return title or None


def listing_links_from_page(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html5lib")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get_text(" "))

        if "S$" not in text or "/mo" not in text:
            continue

        href = urljoin(base_url, anchor["href"])

        if href in seen:
            continue

        seen.add(href)
        links.append((href, text))

    return links


def parse_listing_reference(source_url: str) -> str | None:
    match = re.search(r"-(\d+)(?:/)?$", source_url)

    if not match:
        return None

    return match.group(1)


def parse_propertyguru_listing(
    source_page_url: str,
    source_url: str,
    text: str,
) -> dict | None:
    price_monthly = parse_price(text)
    address = parse_address(text)

    if price_monthly is None or address is None:
        return None

    nearest_mrt_name, nearest_mrt_distance_m = parse_mrt(text)

    return {
        "listing_id": make_listing_id(source_url, address, price_monthly),
        "source": "PropertyGuru",
        "source_page_url": source_page_url,
        "source_url": source_url,
        "source_listing_reference": parse_listing_reference(source_url),
        "title": parse_title(text, price_monthly, address),
        "price_monthly": price_monthly,
        "address": address,
        "property_type": "HDB Flat" if "HDB Flat" in text else pd.NA,
        "room_type": parse_room_type(text),
        "floor_area_sqft": parse_area(text),
        "nearest_mrt_name": nearest_mrt_name,
        "nearest_mrt_distance_m": nearest_mrt_distance_m,
        "listed_on_text": parse_listed_on(text),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "latitude": pd.NA,
        "longitude": pd.NA,
        "raw_listing_text": text,
    }


def fetch_page(
    session: requests.Session,
    url: str,
    max_retries: int,
    rate_limit_wait_seconds: float,
    jitter_seconds: float,
) -> str | None:
    for attempt in range(1, max_retries + 1):
        response = session.get(url, timeout=30)

        if response.status_code != 429:
            response.raise_for_status()
            return response.text

        retry_after = response.headers.get("Retry-After")

        if retry_after and retry_after.isdigit():
            wait_seconds = float(retry_after)
        else:
            wait_seconds = rate_limit_wait_seconds * attempt

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
        headers={
            "Authorization": token,
        },
        timeout=30,
    )
    response.raise_for_status()

    results = response.json().get("results", [])

    if not results:
        return {
            "latitude": None,
            "longitude": None,
        }

    first = results[0]
    latitude = first.get("LATITUDE")
    longitude = first.get("LONGITUDE")

    if latitude is None or longitude is None:
        return {
            "latitude": None,
            "longitude": None,
        }

    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
    }


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
                cached = geocode_address(
                    session=session,
                    address=address,
                    token=token,
                )
                cache[address] = cached
                time.sleep(delay_seconds)
            except requests.RequestException as error:
                print(f"Failed to geocode {address}: {error}")
                continue

        listing["latitude"] = cached.get("latitude")
        listing["longitude"] = cached.get("longitude")

    save_cache(cache)
    return listings


def scrape_propertyguru(
    start_url: str,
    start_page: int,
    end_page: int,
    page_delay_seconds: float,
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

    listings: list[dict] = []
    seen_ids: set[str] = set()

    for page_number in range(start_page, end_page + 1):
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
            print(
                "Stopping this run so the rows already collected can be saved. "
                f"Resume later from page {page_number}."
            )
            break

        for source_url, text in listing_links_from_page(html, page_url):
            listing = parse_propertyguru_listing(page_url, source_url, text)

            if listing is None:
                continue

            if listing["listing_id"] in seen_ids:
                continue

            seen_ids.add(listing["listing_id"])
            listings.append(listing)

        if page_number < end_page:
            wait_seconds = page_delay_seconds + random.uniform(0, jitter_seconds)
            time.sleep(wait_seconds)

    return listings


def save_listings(listings: list[dict], output_file: Path, append: bool) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if not listings and output_file.exists():
        print(
            "No new listings were scraped; keeping the existing output file "
            f"unchanged: {output_file}"
        )
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

    df = df[OUTPUT_COLUMNS]
    df.to_csv(output_file, index=False, encoding="utf-8-sig")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape public live HDB rental listings and geocode them.",
    )
    parser.add_argument(
        "--start-url",
        default=DEFAULT_START_URL,
        help="PropertyGuru HDB rental search URL to start from.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Number of result pages to fetch from --start-page.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First result page to fetch.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Deprecated alias for both --page-delay and --geocode-delay.",
    )
    parser.add_argument(
        "--page-delay",
        type=float,
        default=None,
        help="Delay in seconds between listing page requests.",
    )
    parser.add_argument(
        "--geocode-delay",
        type=float,
        default=None,
        help="Delay in seconds between OneMap geocode requests.",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=OUTPUT_FILE,
        help="CSV output path.",
    )
    parser.add_argument(
        "--skip-geocode",
        action="store_true",
        help="Skip OneMap geocoding.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to an existing CSV and deduplicate by listing_id.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Maximum retries for a page when the site returns 429.",
    )
    parser.add_argument(
        "--rate-limit-wait",
        type=float,
        default=120.0,
        help="Base wait seconds after a 429 response.",
    )
    parser.add_argument(
        "--jitter",
        type=float,
        default=3.0,
        help="Random extra wait seconds added between requests.",
    )
    return parser.parse_args()


def load_env() -> None:
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env", encoding="utf-8-sig")
        return

    env_file = PROJECT_ROOT / ".env"

    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> None:
    args = parse_args()
    load_env()

    page_delay = args.page_delay if args.page_delay is not None else args.delay
    geocode_delay = (
        args.geocode_delay if args.geocode_delay is not None else args.delay
    )
    end_page = args.start_page + args.pages - 1
    total_scraped = 0

    for page_number in range(args.start_page, end_page + 1):
        listings = scrape_propertyguru(
            start_url=args.start_url.rstrip("/"),
            start_page=page_number,
            end_page=page_number,
            page_delay_seconds=page_delay,
            max_retries=args.max_retries,
            rate_limit_wait_seconds=args.rate_limit_wait,
            jitter_seconds=args.jitter,
        )

        if not listings:
            print(
                "No listings were parsed on this page. "
                f"Stopping at page {page_number}."
            )
            break

        if not args.skip_geocode:
            listings = add_coordinates(
                listings=listings,
                token=os.getenv("ONEMAP_TOKEN"),
                delay_seconds=geocode_delay,
            )

        save_listings(listings, args.output_file, append=True)
        total_scraped += len(listings)

        print(
            f"Saved page {page_number}; "
            f"new listings this page: {len(listings):,}; "
            f"new listings this run: {total_scraped:,}"
        )

        if page_number < end_page:
            wait_seconds = page_delay + random.uniform(0, args.jitter)
            time.sleep(wait_seconds)

    print(f"Listings scraped this run: {total_scraped:,}")
    print(f"Output file: {args.output_file}")


if __name__ == "__main__":
    main()
