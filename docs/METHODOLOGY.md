# Methodology

## 1. Research question and system boundary

HomeLens SG asks:

> Given a buyer's budget and housing preferences, which HDB resale areas and
> representative block + flat-type options offer the best supported trade-offs?

The unit of recommendation is not an individual flat listing. It is an aggregate of
recent registered transactions for one `town + block + street + flat_type` group.
The system supports research and comparison; it is not a live-listing search,
valuation service or financial-advice system.

## 2. CRISP-DM process

### 2.1 Business Understanding

The target users are people exploring HDB resale options in Singapore. Their main
needs are:

- stay within a stated budget;
- choose a suitable flat type, size and remaining lease;
- express preferred towns and transport or amenity priorities;
- understand why an option was recommended; and
- see the age, coverage and uncertainty of the evidence.

The main output is a ranked, evidence-based shortlist. A useful result must obey all
hard constraints, show the data used and avoid presenting unknown values as facts.

### 2.2 Data Understanding

The pipeline validates the source schema before processing. Exploratory analysis
checks monthly price trends, town-level price per square metre, price distributions,
price-space-lease trade-offs and model performance. Data quality checks cover:

- date and numeric parsing;
- missing required values;
- duplicate records;
- plausible ranges for price, floor area, remaining lease and storey; and
- time coverage, town coverage and flat-type coverage.

In the current reproducible snapshot, 235,356 raw transactions cover January 2017
to July 2026. The latest month is partial. Validation keeps 235,355 rows after
removing one implausible row. Because the complete CSV has no transaction ID, 631
rows with identical published fields are retained and reported as suspected matches
instead of being deleted as definite duplicates. These numbers describe this
snapshot only and will change when the source is refreshed.

### 2.3 Data Preparation

The preparation pipeline performs the following steps:

1. Standardise town, block, street and flat-type text.
2. Parse month, price, floor area and lease fields.
3. Convert remaining lease to decimal years and storey ranges to midpoints.
4. Remove repeated transaction IDs when an ID exists, flag identical field rows when
   no ID exists, and remove missing or implausible values.
5. Create price per square metre, a numeric month index and a block address.
6. Exclude an unfinished source month, select a rolling 24-complete-month candidate
   window and require at least three recent transactions per candidate.
7. Aggregate median, 25th and 75th percentile prices, area, lease, storey,
   transaction count, observation dates, common flat model and town-flat-type trend.

The current candidate knowledge base contains 7,730 candidates across 26 towns and
six flat types. Its observation window is July 2024 to June 2026; 1,046 records from
the unfinished July 2026 month are retained in the audit table but excluded here.

Optional spatial preparation has two stages. First, OneMap geocodes each unique HDB
block address and stores the result in a persistent cache. Second, Haversine distance
joins the coordinates to official MRT, bus-stop, hawker-centre and park layers. This
produces nearest-MRT and nearest-park distances, bus stops within 500 metres, and
hawker-centre plus park counts within one kilometre. These are straight-line measures,
not route or travel-time measures.

### 2.4 Modeling

#### Price experiment

Two methods are compared:

1. **Hierarchical median baseline:** use the historical median for town + flat type,
   then fall back to flat type and the global median.
2. **Random-forest regression:** one-hot encode town, flat type, flat model and storey
   range, and combine them with floor area, remaining lease, storey midpoint and a
   numeric month feature.

The split is chronological, not random. In the current run, the model trains on
222,066 transactions from January 2017 to December 2025 and tests on 12,243
transactions from January to June 2026. The unfinished July records are excluded.
This prevents future transactions from entering the training set.

The trained model provides a **reference price** for returned candidates. The
observed transaction evidence still controls the budget filter and is not replaced by
the model estimate.

#### Recommendation model

The recommendation process is deliberately transparent:

1. Parse English or Chinese preferences with deterministic rules. An optional LLM
   parser can return the same validated schema when it is enabled and configured.
2. Apply hard constraints first: the candidate's observed 75th-percentile price must
   be within budget, followed by any flat-type, town, floor-area, lease and MRT limits.
3. Normalise usable criteria with the 5th and 95th percentile bounds learned from the
   full knowledge base.
4. Calculate a weighted score for affordability, space, lease, preferred location,
   transit, amenities and market activity.
5. Treat missing evidence as unknown. Redistribute unavailable weights, reduce
   confidence modestly and return a warning. A hard MRT constraint is never silently
   relaxed when MRT evidence is missing.
6. Mark non-dominated price-space-lease trade-offs and diversify the final shortlist
   to at most two options per town when possible.

Each result includes the observed price range, recent sample size, latest transaction
month, score components, evidence coverage and plain-language reasons.

### 2.5 Evaluation

The price experiment reports MAE, RMSE, MAPE and R-squared on the chronological
holdout. The current run gives:

| Model | MAE | RMSE | MAPE | R-squared |
| --- | ---: | ---: | ---: | ---: |
| Hierarchical median baseline | S$157,422 | S$197,775 | 21.92% | 0.144 |
| Random forest | S$39,686 | S$57,454 | 5.90% | 0.928 |

The random forest reduces MAE by 74.79% relative to the baseline in this holdout.
This is an experimental result, not a guarantee for a future sale or an individual
flat.

The recommender is evaluated separately because prediction accuracy alone does not
prove recommendation quality. Automated tests check data parsing, candidate
aggregation, chronological separation, hard constraints, score behaviour, missing
geospatial evidence, intent extraction and the local web API. Planned evaluation also
includes ranking sensitivity, comparison with simpler ranking methods, case studies
and a user study; no user-study result is claimed at this stage.

## 3. Limitations

- Registration data records completed resale transactions, not asking prices or
  currently available homes.
- A block + flat-type aggregate cannot represent the renovation, orientation,
  condition or exact floor of a specific unit.
- The latest source month can be incomplete; the current pipeline excludes it from
  candidates, research figures and the final holdout while retaining it for audit.
- Straight-line distance does not model walking routes, service frequency, crowding
  or actual journey time.
- Some location features remain unavailable until block addresses are geocoded.
- Weighted ranking reflects stated preferences and design choices; sensitivity tests
  are needed to show how rankings change under different weights.
- The price model may lose accuracy after market or policy changes and must be
  retrained on refreshed data.

## 4. Next steps

1. Complete and verify address geocoding, then rebuild transport and amenity features.
2. Add walk-time or public-transport travel-time features if a reliable official
   source is available.
3. Compare the random forest with additional time-aware regression methods.
4. Run ablation and sensitivity tests for ranking criteria and missing data.
5. Add source-refresh checks, model drift monitoring and clearer uncertainty ranges.
6. Conduct user evaluation and use the findings to refine explanations and controls.
