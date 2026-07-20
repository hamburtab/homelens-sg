from __future__ import annotations

from scripts.scraping import scrape_live_sale_listings as scraper


SAMPLE_TEXT = (
    "Rare! High Floor Corner Unit S$ 777,000 S$ 591.77 psf "
    "629 Pasir Ris Drive 3 629 Pasir Ris Drive 3 "
    "3 2 1,313 sqft HDB Flat 99-year Leasehold Built: 1993 "
    "8 min (630 m) from EW1 Pasir Ris MRT Station "
    "Listed on Jul 20, 2026 (1h ago) Contact Agent"
)


def test_parse_propertyguru_sale_listing() -> None:
    listing = scraper.parse_propertyguru_listing(
        "https://www.propertyguru.com.sg/hdb-for-sale",
        "https://www.propertyguru.com.sg/listing/hdb-for-sale-example-500138650",
        SAMPLE_TEXT,
    )

    assert listing is not None
    assert listing["source_listing_reference"] == "500138650"
    assert listing["title"] == "Rare! High Floor Corner Unit"
    assert listing["asking_price"] == 777_000
    assert listing["price_psf"] == 591.77
    assert listing["address"] == "629 Pasir Ris Drive 3"
    assert listing["bedrooms"] == 3
    assert listing["bathrooms"] == 2
    assert listing["floor_area_sqft"] == 1_313
    assert listing["property_type"] == "HDB Flat"
    assert listing["tenure"] == "99-year Leasehold"
    assert listing["built_year"] == 1993
    assert listing["nearest_mrt_name"] == "EW1 Pasir Ris MRT Station"
    assert listing["nearest_mrt_distance_m"] == 630
    assert listing["listed_on_text"] == "Jul 20, 2026 (1h ago)"


def test_listing_links_filters_rental_and_deduplicates() -> None:
    html = f"""
    <html><body>
      <a href="/listing/hdb-for-sale-example-500138650">{SAMPLE_TEXT}</a>
      <a href="/listing/hdb-for-sale-example-500138650">{SAMPLE_TEXT}</a>
      <a href="/listing/hdb-for-rent-example-500000001">S$ 2,500 /mo Example</a>
      <a href="/news/story-123">S$ 777,000 market report</a>
    </body></html>
    """

    links = scraper.listing_links_from_page(
        html,
        "https://www.propertyguru.com.sg/hdb-for-sale",
    )

    assert links == [
        (
            "https://www.propertyguru.com.sg/listing/hdb-for-sale-example-500138650",
            SAMPLE_TEXT,
        )
    ]


def test_parse_labelled_bedrooms_and_kilometres() -> None:
    text = (
        "Family Home S$ 850,000 S$ 850.00 psf "
        "10 Test Street 10 Test Street 4 Beds 2 Baths 1,000 sqft "
        "Executive Maisonette 99-year Leasehold Built: 1988 "
        "12 min (1.2 km) from NS1 Sample MRT Station Listed on Jul 19, 2026"
    )

    listing = scraper.parse_propertyguru_listing(
        "https://www.propertyguru.com.sg/hdb-for-sale/2",
        "https://www.propertyguru.com.sg/listing/hdb-for-sale-family-home-500138651",
        text,
    )

    assert listing is not None
    assert listing["bedrooms"] == 4
    assert listing["bathrooms"] == 2
    assert listing["property_type"] == "Executive Maisonette"
    assert listing["nearest_mrt_distance_m"] == 1_200
