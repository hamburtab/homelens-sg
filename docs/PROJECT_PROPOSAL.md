# HomeLens SG: Explainable HDB Resale Decision Support

## Project idea

Buying an HDB resale flat is a major decision. A buyer must compare price, floor area,
remaining lease, location, public transport and nearby amenities. This information is
often spread across different websites and datasets, so it is difficult to compare
areas in one place. HomeLens SG will combine official web data into an explainable
decision-support system for Singapore HDB resale housing.

The system will recommend suitable **areas and representative block + flat-type
options** based on a user's budget and preferences. It will not present historical
transactions as current property listings, and it will not replace a professional
valuation or financial adviser.

## Data and web-mining scope

The main source is the official data.gov.sg HDB resale transaction dataset from
January 2017 onwards. It contains the transaction month, town, block, street, flat
type, floor area, storey range, remaining lease and resale price. We will combine it
with official public GeoJSON layers for MRT exits, bus stops, hawker centres and
parks. OneMap can optionally be used to geocode HDB block addresses. All API
credentials are optional and are left blank until they are available.

After cleaning the transaction records, we build a local knowledge base. One
candidate represents a town, block, street and flat type. It summarises recent
transactions using the median price, middle 50% price range, typical floor area,
remaining lease, transaction count, recency and local price trend. If coordinates
are available, the candidate can also include straight-line distance to MRT and
parks, nearby bus-stop counts and nearby amenity counts.

## Method

We will follow the first five phases of CRISP-DM:

1. **Business understanding:** define the buyer's decision, useful constraints and
   the meaning of a good recommendation.
2. **Data understanding:** inspect coverage, missing values, duplicates, price
   distributions, trends and differences across towns and flat types.
3. **Data preparation:** clean and validate fields, create price, lease, storey and
   time features, combine official datasets, and build the candidate knowledge base.
4. **Modeling:** compare a historical median price baseline with a random-forest
   regression model. The recommender will first apply hard constraints and then use
   a transparent weighted score for affordability, space, lease, location, transit,
   amenities and market activity.
5. **Evaluation:** use a chronological holdout for the price experiment and report
   MAE, RMSE, MAPE and R-squared. We will also test constraint handling, missing-data
   behaviour, ranking stability and explanation quality.

Users can enter preferences in simple English or Chinese. A deterministic parser
works without an API key. An optional large-language-model parser may convert more
complex text into the same validated preference fields, but it is not allowed to
create housing facts. Every result will show its evidence, score breakdown, data
date and limitations.

## Expected value, limitations and next steps

HomeLens SG aims to make HDB resale research faster, more transparent and easier to
personalise. Its main innovation is the combination of a reusable local knowledge
base, time-aware price modeling and explainable multi-objective recommendation.
Important limitations are that registered transactions are historical, the latest
month may be incomplete, straight-line distance is not travel time, and some
geospatial features require address geocoding. Next, we will complete geospatial
enrichment, add stronger model comparisons and sensitivity tests, and conduct user
evaluation before the final presentation.
