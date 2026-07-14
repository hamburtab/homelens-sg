# HomeLens SG

HomeLens SG is an explainable web-mining project that recommends **HDB resale
areas and representative block/flat-type options** in Singapore. It combines
official transaction data, optional transport and location APIs, a price model,
and a transparent multi-objective ranking method.

It does not pretend that historical transactions are live listings. Every
recommendation shows the evidence used, the observed price range, data recency,
score components, and unavailable features.

## What already works without any API key

- Download a complete official HDB snapshot, or a recent paginated sample, from data.gov.sg.
- Validate and clean month, price, area, storey and remaining-lease fields.
- Build a local candidate knowledge base at block + flat-type level.
- Train and compare a time-aware median baseline and machine-learning model.
- Parse common English/Chinese housing preferences with deterministic rules.
- Apply hard constraints before ranking candidates.
- Rank with robust fixed-distribution scores and mark Pareto-efficient options.
- Serve a local JSON API and responsive browser interface using Python only.

OneMap and OpenAI are optional integrations. An LTA DataMall client is reserved for
future work. All credentials are blank in `.env.example`; missing keys never stop
the core application.

## Quick start

Python 3.10 or newer is recommended.

```bash
cd homelens-sg
python3 -m pip install -e .
python3 scripts/build_dataset.py --max-records 20000
python3 scripts/download_layers.py
python3 scripts/train_model.py
python3 scripts/explore_data.py
python3 scripts/run_demo.py --budget 650000 --flat-types "4 ROOM"
python3 scripts/serve.py --port 8000
```

Then open `http://127.0.0.1:8000`.

For a complete research run, omit `--max-records`:

```bash
python3 scripts/build_dataset.py
python3 scripts/train_model.py
```

The raw snapshot, manifest, cleaned table, candidate knowledge base, model and
metrics are saved under `data/` and `artifacts/`. Poster-ready EDA figures are
saved under `artifacts/figures/`. These generated files are
ignored by Git so the repository stays small.

## Run without installing the package

Every script adds `src/` to its import path, so the following also works:

```bash
python3 scripts/build_dataset.py --fixture
python3 scripts/train_model.py
python3 scripts/serve.py
```

The `--fixture` mode is fully offline and is useful for tests or demonstrations.

## API examples

Health and integration status:

```bash
curl http://127.0.0.1:8000/api/health
```

Recommendation request:

```bash
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "I need a 4-room flat under 650k, preferably in Tampines",
    "budget": 650000,
    "flat_types": ["4 ROOM"],
    "preferred_towns": ["TAMPINES"],
    "top_k": 5
  }'
```

## Data and model design

The recommendation unit is a representative `town + block + street + flat
type`, aggregated from recent transactions. The budget hard constraint uses the
75th percentile of recent observed prices rather than the median, providing a
more conservative buffer. Flat type, minimum floor area and minimum lease are
also applied first. Soft
preferences are then scored using percentile bounds learned from the full
candidate knowledge base, so scores do not change arbitrarily when filters
change.

Missing transport or amenity data remains unknown. Its weight is redistributed
over available evidence and the response contains an explicit warning. Once
OneMap geocoding is completed, the same recommender automatically uses the official
MRT, bus-stop, hawker-centre and park columns already downloaded from data.gov.sg.

If the newest source month is still in progress, its records are retained in the
clean audit table but excluded from candidate construction, EDA comparisons and the
chronological model experiment. Candidate groups with only three or four recent
transactions are labelled as low-sample evidence.

The price experiment uses a chronological holdout rather than a random split.
It reports MAE, RMSE, MAPE and R-squared for both a hierarchical historical
median baseline and a random-forest regression pipeline. The training cutoff is
stored beside the model for reproducibility.

## Optional credentials

Copy the template only when you are ready to add keys:

```bash
cp .env.example .env
```

- `ONEMAP_TOKEN`: search/geocoding and nearby public-transport enrichment.
- `LTA_ACCOUNT_KEY`: reserved for a future LTA routes/service-frequency extension;
  it is not used by the current enrichment pipeline.
- `OPENAI_API_KEY`: structured natural-language intent extraction.
- `OPENAI_MODEL`: model used only for intent extraction.
- `HOMELENS_ENABLE_LLM`: must also be set to `true` before any OpenAI request is allowed.

The four static official layers (MRT exits, bus stops, hawker centres and parks)
need no key. After adding OneMap credentials, run:

```bash
python3 scripts/enrich_geospatial.py
```

This geocodes block addresses with a persistent cache, then computes straight-line
MRT/park distances and nearby bus-stop/amenity counts from the downloaded layers.

The OpenAI integration uses structured output through the Responses API with API
response storage disabled. Provider safety and abuse-monitoring policies may still
apply. The
LLM is never asked to invent prices, distances or amenities; it only converts
user language into the same validated preference schema used by the rules.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use a fixed local fixture and require no network or API key.

## Project documents

- `docs/PROJECT_PROPOSAL.md`: short English proposal.
- `docs/METHODOLOGY.md`: CRISP-DM process, experiments and limitations.
- `docs/DATA_SOURCES.md`: source register, knowledge-base fields and provenance.
- `docs/ARCHITECTURE.md`: data flow, request flow and module map.

## Project boundaries

- Current MVP: HDB resale decision support, not private-property or live-listing search.
- Current evidence: official HDB transaction records plus optional official APIs.
- Commercial property-site scraping is intentionally excluded until terms and permission are checked.
- Human evaluation is intentionally left for the team to conduct later.
