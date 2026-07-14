# Data Sources and Knowledge Base

## 1. Source register

HomeLens SG gives priority to official Singapore government sources. The source
snapshot and each downloaded layer are recorded in a manifest with a download time,
source identifier, file path and SHA-256 hash.

### Sources used by the current pipeline

| Source | Dataset ID | Current role | Access |
| --- | --- | --- | --- |
| [HDB Resale Flat Prices, from Jan 2017](https://data.gov.sg/collections/189/view) | `d_8b84c4ee58e3cfc0ece0d773c8ca6abc` | Main transaction table and price-model data | Public data.gov.sg download; API key is optional |
| data.gov.sg bus stops GeoJSON | `d_3f172c6feb3f4f92a2f47d93eed2908a` | Bus-stop count within 500 m after geocoding | Public download; API key is optional |
| data.gov.sg MRT exits GeoJSON | `d_b39d3a0871985372d7e1637193335da5` | Nearest recorded MRT exit after geocoding | Public download; API key is optional |
| data.gov.sg hawker centres GeoJSON | `d_4a086da0a5553be1d89383cd90d07ecd` | Hawker-centre count within 1 km after geocoding | Public download; API key is optional |
| data.gov.sg parks GeoJSON | `d_0542d48f0991541706b58059381a6eca` | Park count within 1 km and nearest-park distance | Public download; API key is optional |
| [OneMap](https://www.onemap.gov.sg/apidocs/) | Search/geocoding API | Convert HDB block addresses to latitude and longitude | Optional token or account credentials; left blank |

The four GeoJSON layers have been downloaded in the current workspace. The recorded
snapshot contains 5,166 bus-stop points, 597 MRT-exit points, 129 hawker-centre
points and 461 park points. These counts are tied to the 14 July 2026 download and
may change after a refresh.

### Optional or future integrations

| Service | Intended role | Current status |
| --- | --- | --- |
| [LTA DataMall](https://datamall.lta.gov.sg/content/dam/datamall/datasets/LTA_DataMall_API_User_Guide.pdf?ref=public_apis) | Possible bus routes, services and passenger-volume features | Client is included, but the key is blank and these features are not used by the current core knowledge base |
| OpenAI Responses API | Convert complex user language into validated preference fields | Optional and disabled by default; the key is blank; it is not a source of housing facts |

Commercial property portals are not part of the current pipeline. Adding them later
would require a separate review of permission, terms of use, robots rules, update
frequency and field reliability. The current system therefore does not claim to
search live listings.

## 2. HDB transaction scope

The official HDB table provides registered resale transactions. The fields used are:

- month;
- town, block and street name;
- flat type and flat model;
- storey range and floor area;
- lease commencement date and remaining lease; and
- resale price.

The current raw snapshot contains 235,356 rows from January 2017 to July 2026. July
2026 is a partial month. After validation, 235,355 transactions remain. The complete
CSV has no unique transaction ID, so 631 rows that share all published fields with
another row are retained and flagged as suspected identical records rather than
being assumed to be duplicates. One implausible row is removed. The raw file is kept
as a timestamped snapshot, so later results can be traced to the exact input.

This table does **not** provide a live asking price, listing status, renovation
condition, unit orientation, buyer profile, financing terms or exact journey time.

## 3. Knowledge-base construction

The local knowledge base is stored in
`data/processed/hdb_candidates.csv`. Its candidate key is:

```text
town + block + street_name + flat_type
```

The current build excludes the unfinished July 2026 month, then uses the latest 24
complete months of observations and keeps groups with at least three transactions.
It contains 7,730 candidates across 26 towns and six flat types. For each candidate,
it stores:

- median, 25th-percentile, 75th-percentile, minimum and maximum observed price;
- median price per square metre;
- median floor area, remaining lease and storey midpoint;
- common flat model;
- recent transaction count and first/latest observation month;
- months since the latest observation; and
- annualised recent price trend for its town and flat type.

The 75th-percentile price is used for the budget hard constraint. This is more
conservative than filtering on the median, but it is still historical evidence rather
than a quoted price for a specific home. A returned candidate based on only three or
four transactions is labelled as low-sample evidence because its percentiles are
less stable.

## 4. Spatial combination

The transaction table has block addresses but no coordinates. Spatial combination is
therefore performed only when OneMap geocoding is configured:

1. Create a unique block address from block and street name.
2. Search OneMap and cache latitude/longitude by address.
3. Read the four official GeoJSON layers as point features.
4. Use Haversine distance to calculate nearest points and radius counts.
5. Join the derived fields back to every candidate at that block.

The resulting optional fields are latitude, longitude, nearest MRT name and distance,
bus stops within 500 metres, hawker centres and parks within one kilometre, and
nearest-park distance. Until geocoding is completed, these fields remain unknown.
The recommender excludes unavailable dimensions and warns the user; it does not turn
unknown values into zero.

## 5. Provenance and refresh rules

The following files support reproducibility:

- `artifacts/manifests/hdb_snapshot.json`: source URL, dataset ID, time, hash, schema
  and row coverage;
- `artifacts/manifests/official_layers.json`: dataset IDs, hashes and feature counts;
- `artifacts/manifests/candidate_knowledge_base.json`: candidate definition, time
  window and row counts;
- `artifacts/metrics/data_quality.json`: cleaning results; and
- `artifacts/metrics/price_model.json`: time split, features and holdout metrics.

Each refresh should create a new raw snapshot, rerun schema and quality checks,
rebuild the candidate table, rerun the chronological model experiment and update the
manifests. Reports must show the latest complete month separately from a partial
current month.

## 6. Data limitations and planned improvements

- Transaction registration can lag the market and cannot show current availability.
- Small candidate groups have more uncertain price summaries; the current minimum is
  three transactions.
- Address search can return no result or the wrong result and should be checked before
  spatial features are accepted.
- MRT exits are access points, not full stations, and radius counts do not measure
  service quality.
- Park and hawker layers cover selected official categories and do not represent every
  environmental or neighbourhood factor.
- Future work may add official travel-time, school, healthcare and planning data, but
  only after source definitions and join quality are verified.

All credential fields remain blank in `.env.example`. The core HDB pipeline, model,
knowledge base and non-geospatial recommendations work without them.
