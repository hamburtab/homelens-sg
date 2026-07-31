# SG HomeRadar / HomeLens SG

SG HomeRadar is an explainable HDB home-search and neighbourhood-exploration system for Singapore. It implements the proposal's core interaction paths:

- **Macro Exploration**: explore transport, food, shopping, education, nature, and recreation amenities across 55 URA planning areas and 332 subzones.
- **Micro Retrieval**: describe budget, flat type, area, floor space, lease, and transport requirements in natural language, in either English or Chinese. The system applies hard constraints first, then performs multi-objective ranking over historical evidence and explains the results.
- **General Housing Agent**: ask open-ended questions in a ChatGPT-like interface. For every turn, the agent first plans the required data tools, queries the local database, and answers from evidence without requiring a fixed user profile.

The system combines official HDB resale transactions, authorised batched PropertyGuru sale and rental listings, official geospatial facilities, and aggregated community evidence in one product. It is a course research and decision-support tool, not a valuation service or a complete market inventory.

## Implemented Features

### Unified Web Product

- Polished, responsive React single-page interface;
- Interactive Singapore planning-area and subzone map;
- Evidence-based liveability heatmap and six-dimension evidence panel;
- Filterable sale and rental listing catalogues;
- Natural-language recommendation form with AI/rule parsing toggle;
- General AI housing agent that handles vague or specific questions such as "How do I use this?", "What homes do you recommend?", and "Compare two areas", without enforcing a questionnaire;
- Per-turn workflow of structured planning → backend data tools → evidence synthesis, querying local resale transactions, sale and rental listings, area profiles, and data status;
- Separate two-year and four-year candidate windows for historical transactions; the agent presents their median prices, ranges, sample sizes, and trends independently;
- Budget, location, rent/buy intent, flat type, and lifestyle preferences are optional conversational memory rather than prerequisites for an answer;
- Vague recommendation requests immediately return exploratory, real-data cards across sale and rental options, clearly labelled as non-personalised;
- Time-sensitive policy or news questions may use web search, while project listings, prices, distances, and coordinates must still come from backend tools;
- The legacy fixed-profile advisor remains separate in `advisor.py` and `/api/advisor/*`; the current web chat uses `general_agent.py` and `/api/agent/*`;
- OneMap search for any Singapore POI or address, candidate confirmation, and map positioning;
- Hard filtering and ranking by straight-line distance from a confirmed location, with map radius and property-distance display;
- Recommendation cards, evidence-strength indicators, and Pareto trade-off labels;
- Side-by-side comparison of up to three candidates;
- Integration of periodic listing snapshots with historical recommendations;
- Clear documentation of methods, models, data coverage, and unimplemented capabilities.

### Recommendation and Models

- Hard constraints for budget, flat type, specified town, minimum floor area, minimum remaining lease, and MRT distance;
- Users can enter "NUS", "VivoCity", or a complete address. AI is the primary parser for location semantics and outputs the original location, canonical OneMap query, spatial relationship, flexibility, and confidence; rules are used only as a fallback when AI is unavailable;
- Location states distinguish not provided, recognised, pending OneMap confirmation, unresolved, and confirmed. Recognised locations are not repeatedly treated as missing information;
- Multi-objective ranking across affordability, space, lease, location, transit, amenities, and market activity;
- Missing evidence is not treated as zero, and hard constraints are never silently relaxed;
- 7,730 primary HDB block-and-flat-type candidates from the latest 24 complete months, plus 12,256 comparison candidates from a 48-month window;
- Random Forest supplies reference prices only; the historical 75th-percentile price continues to control budget eligibility;
- Chronological holdout performance of approximately 5.9% MAPE and 0.928 R².

### Current Product Data

| Dataset | Current Size | Product Use |
| --- | ---: | --- |
| HDB resale transactions | 235,355 cleaned records | Prices, floor area, lease, trends, and modelling |
| HDB two-year candidate knowledge base | 7,730 records | Current recommendations and area market profiles |
| HDB four-year candidate knowledge base | 12,256 records | Medium-term historical comparison and sparse-block supplementation |
| Sale listings | 6,359 unique listings | Partial market snapshot and recommendation linkage |
| Rental listings | 8,041 records | Rental catalogue and map |
| Planning areas | 55 | Macro exploration |
| Subzones | 332 | Six-dimension liveability profiles |

Address resolution does not fabricate locations:

- 5,255 of 6,359 sale listings (82.6%) can be positioned using historical HDB addresses or matching rental addresses;
- 7,932 of 8,041 rental listings (98.6%) have valid coordinates;
- For addresses that still lack precise coordinates, an area-level assignment is added only when historical HDB blocks prove that the entire street belongs to one planning area. This raises planning-area filter coverage to 95.9% for sale listings and 99.3% for rental listings;
- Listings that cannot be reliably positioned remain in the catalogue but do not display a map marker;
- `locationSource` and `areaSource` identify the evidence used for the map point and area assignment respectively.

## Quick Start

Requires Python 3.10+ and Node.js.

```bash
python3 -m pip install -e .
cd map
npm install
npm run build
cd ..
python3 scripts/serve.py --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

The Python service serves both the production web application and the `/api/*` recommendation endpoints.

Arbitrary location search requires either a OneMap token or OneMap account credentials. Store them only in the local `.env`; they are never sent to the browser:

```text
ONEMAP_TOKEN=...
# Alternatively, configure both ONEMAP_EMAIL and ONEMAP_PASSWORD
```

## Regenerating Product Data

The repository already contains runnable product data. Run the following commands only when the raw or team-provided data changes:

```bash
python3 scripts/build_dataset.py --raw data/raw/hdb_resale_20260714T091349Z.csv
python3 scripts/enrich_existing_candidates.py
python3 scripts/build_product_data.py
cd map && npm run build
```

Details:

- `build_dataset.py` generates both two-year and four-year candidate knowledge bases from the same cleaned transaction-level dataset;
- `enrich_existing_candidates.py` uses existing block coordinates and official MRT, bus, hawker-centre, and park layers to calculate straight-line distances and facility counts without requesting a new geospatial API;
- `build_product_data.py` merges listings, deduplicates by the latest `scraped_at`, standardises addresses, resolves planning areas and subzones, and produces privacy-safe frontend JSON;
- Team-provided source files remain unchanged, and every product file can be regenerated from its source.

## API

### `GET /api/health`

Returns the status of the knowledge base, model, LLM, listings, and data dates.

### `GET /api/overview`

Returns the health status and a summary of product-data coverage.

### `POST /api/recommend`

Example:

```json
{
  "query": "A 4-room flat under S$650,000, preferably in Tampines and near an MRT station",
  "budget": 650000,
  "flat_types": ["4 ROOM"],
  "preferred_towns": ["TAMPINES"],
  "top_k": 8,
  "use_llm": false
}
```

Returns historical recommendations, score breakdowns, explanations, model reference prices, warnings, and up to 12 partially live sale-listing matches.

### `GET /api/locations/search?q=NUS&limit=5`

Returns OneMap candidates for a Singapore location together with their planning area and subzone. The user must confirm a candidate before the frontend sends `anchor_latitude`, `anchor_longitude`, and the optional `max_anchor_distance_m` to the recommendation endpoint. Coordinates are never generated by the LLM.

A natural-language request can also be written as `A 4-room under 650k within 3km of NUS`. The first request returns `location_confirmation_required` and a candidate list; recommendations are calculated only after a confirmed follow-up request. Distance currently uses the straight-line Haversine formula and does not represent walking, driving, or public-transport routes.

### `POST /api/agent/message`

Start or continue a general housing-agent session:

```json
{
  "message": "What homes do you currently recommend?"
}
```

The response contains the `session_id`, the current answer, optional conversational memory, the actual queried sources, and directly renderable `cards`. The agent does not require a fixed profile before answering; vague recommendation requests still query the database and return exploratory results. Include the `session_id` in later requests. Specific landmarks continue to require OneMap candidate confirmation:

```json
{
  "session_id": "...",
  "confirmed_location_id": "onemap:..."
}
```

`GET /api/agent/session?session_id=...` restores the conversation and result cards, while `POST /api/agent/reset` clears the session. The server retains only the latest 16 turns and optional memory in process, expiring them after four hours. The legacy `/api/advisor/*` endpoints remain available but are no longer used by the current web interface.

## LLM-Compatible Gateway

The project supports gateways compatible with the OpenAI Responses API. Store real credentials only in the local `.env`:

```text
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=...
HOMELENS_ENABLE_LLM=true
HOMELENS_ENABLE_WEB_SEARCH=true
```

If no LLM is available or a call fails, the system automatically falls back to deterministic bilingual planning and local-data answers. The new agent uses a two-stage model workflow: the first stage produces only a strict JSON query plan, the backend executes controlled data tools, and the second stage may compose an answer only from bounded evidence. OneMap coordinates, filtering, statistics, and listings remain backend-controlled; web search is allowed only for time-sensitive questions.

## Testing

```bash
python3 -m unittest discover -s tests -v
cd map && npm run build
```

The current `unittest` suite contains 75 tests. One is skipped in sandboxes that restrict local sockets and all others pass; three additional pytest-style listing-parser tests have been verified manually. Frontend linting, TypeScript checks, and the production build also pass. The new tests cover open-ended help, vague recommendations, budget queries, follow-up answers after OneMap confirmation, restoration of session cards, and the strict JSON planning protocol.

## Privacy and Data Boundaries

- The public frontend does not contain PropertyGuru `raw_listing_text` or internal source references;
- Raw Google review text, author names, and author URLs are not included in the public frontend;
- The interface displays only aggregated community scores, place counts, and review-evidence counts;
- The advisor does not store nationality, race, religion, gender, or health diagnoses in a profile or use them for ranking. A university student's request to live near campus is not misinterpreted as a need for children's schools;
- The current profile is a temporary anonymous session rather than a persistent cross-device user account. A multi-user deployment would still require authentication, a database, user consent, export/deletion controls, and server-side encryption;
- Sale data is a discontinuous course-research snapshot: pages 1–145 and 301–500 are currently parsed; raw pages 146–185 await import, while pages 186–300 and all pages after 500 remain missing;
- Automated weekly scheduling is not implemented and is explicitly outside the current project scope.

## Explicitly Reserved Future Capabilities

The interface displays `Planned` or disabled placeholders for the following capabilities without claiming that they are implemented:

- Road-network walking times and real commute routes;
- Exact coordinates for listings that cannot be resolved by address matching;
- Complete real-time sale inventory and automatic weekly updates;
- Historical recommendation models for private condominiums;
- Features that require live LTA route or congestion data.

For more detailed data sources, directory responsibilities, and handover status, see `docs/`, `artifacts/manifests/`, and `CODEX_PROJECT_HANDOFF.md`.
