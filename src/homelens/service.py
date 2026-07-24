"""Application service that grounds every response in the local knowledge base."""

from __future__ import annotations

import json
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from homelens.config import PROJECT_ROOT, Settings
from homelens.errors import DataUnavailableError
from homelens.geospatial import haversine_matrix
from homelens.intent import parse_intent
from homelens.locations import OneMapLocationResolver
from homelens.price_model import MODEL_FEATURES, load_price_model
from homelens.recommender import recommend
from homelens.schemas import UserPreferences


class HomeLensService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self._candidates: pd.DataFrame | None = None
        self._live_listings: pd.DataFrame | None = None
        self._price_model_artifact: dict[str, Any] | None = None
        self._price_model_checked = False
        self._location_resolver: OneMapLocationResolver | None = None
        self._advisor = None

    def _active_candidates_path(self):
        """Prefer the repository's enriched counterpart for the standard candidate file."""

        configured = self.settings.candidates_path
        standard = PROJECT_ROOT / "data" / "processed" / "hdb_candidates.csv"
        product = PROJECT_ROOT / "data" / "processed" / "hdb_candidates_product.csv"
        enriched = PROJECT_ROOT / "data" / "processed" / "hdb_candidates_geocoded.csv"
        if configured.resolve() == standard.resolve():
            if product.exists():
                return product
            if enriched.exists():
                return enriched
        return configured

    def _load_candidates(self) -> pd.DataFrame:
        if self._candidates is not None:
            return self._candidates
        path = self._active_candidates_path()
        if not path.exists():
            raise DataUnavailableError(
                "Candidate knowledge base not found. Run scripts/build_dataset.py first."
            )
        frame = pd.read_csv(path, low_memory=False)
        required = {
            "candidate_id",
            "town",
            "block_address",
            "flat_type",
            "median_resale_price",
            "median_floor_area_sqm",
            "median_remaining_lease_years",
        }
        missing = required - set(frame.columns)
        if missing:
            raise DataUnavailableError(
                "Candidate knowledge base is missing: " + ", ".join(sorted(missing))
            )
        for column in ("first_transaction_month", "last_transaction_month"):
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], errors="coerce")
        self._candidates = frame
        return frame

    def _load_live_listings(self) -> pd.DataFrame:
        if self._live_listings is not None:
            return self._live_listings
        path = self.settings.live_listings_path
        if not path.exists():
            self._live_listings = pd.DataFrame()
            return self._live_listings
        frame = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        required = {"listing_id", "mode", "address", "scraped_at"}
        if missing := required - set(frame.columns):
            raise DataUnavailableError(
                "Live listing dataset is missing: " + ", ".join(sorted(missing))
            )
        frame["scraped_at"] = pd.to_datetime(frame["scraped_at"], errors="coerce", utc=True)
        self._live_listings = frame
        return frame

    def reload(self) -> None:
        self._candidates = None
        self._live_listings = None
        self._load_candidates()

    def _locations(self) -> OneMapLocationResolver:
        if self._location_resolver is None:
            self._location_resolver = OneMapLocationResolver(self.settings)
        return self._location_resolver

    def search_locations(self, query: str, *, limit: int = 5) -> dict[str, Any]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= 10:
            raise ValueError("location candidate limit must be between 1 and 10")
        return {
            "query": query.strip(),
            "provider": "onemap",
            "candidates": self._locations().search(query, limit=int(limit)),
            "requires_confirmation": True,
        }

    def _advisor_service(self):
        if self._advisor is None:
            from homelens.advisor import HousingAdvisor

            self._advisor = HousingAdvisor(self, self.settings)
        return self._advisor

    def advisor_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advisor_service().message(payload)

    def reset_advisor(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._advisor_service().reset(payload)

    def advisor_state(self, session_id: str) -> dict[str, Any]:
        return self._advisor_service().state(session_id)

    def health(self) -> dict[str, Any]:
        candidates_path = self._active_candidates_path()
        model_path = self.settings.model_path
        result: dict[str, Any] = {
            "status": "ready" if candidates_path.exists() else "setup_required",
            "candidate_knowledge_base": candidates_path.exists(),
            "price_model": model_path.exists(),
            "integrations": self.settings.integration_status(),
            "advisor": {
                "available": self.settings.integration_status()["openai"],
                "session_storage": "process memory only; four-hour TTL",
            },
            "candidate_source": str(candidates_path.relative_to(PROJECT_ROOT))
            if candidates_path.is_relative_to(PROJECT_ROOT)
            else str(candidates_path),
        }
        if candidates_path.exists():
            frame = self._load_candidates()
            result["candidate_rows"] = int(len(frame))
            result["towns"] = sorted(frame["town"].dropna().unique().tolist())
            if "last_transaction_month" in frame:
                latest = frame["last_transaction_month"].max()
                result["latest_observation_month"] = (
                    pd.Timestamp(latest).strftime("%Y-%m") if pd.notna(latest) else None
                )
            coordinates = frame[["latitude", "longitude"]].notna().all(axis=1)
            result["candidate_rows_with_coordinates"] = int(coordinates.sum())
        live = self._load_live_listings()
        result["live_listings"] = {
            "available": not live.empty,
            "sale": int((live.get("mode") == "sale").sum()) if not live.empty else 0,
            "rent": int((live.get("mode") == "rent").sum()) if not live.empty else 0,
        }
        metrics_path = PROJECT_ROOT / "artifacts" / "metrics" / "price_model.json"
        if metrics_path.exists():
            result["price_model_metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
        return result

    def overview(self) -> dict[str, Any]:
        status: dict[str, Any] = {}
        if self.settings.product_status_path.exists():
            status = json.loads(self.settings.product_status_path.read_text(encoding="utf-8"))
        return {"health": self.health(), "data": status}

    @staticmethod
    def _listing_payload(row: pd.Series) -> dict[str, Any]:
        def clean(value: Any) -> Any:
            if value is None or pd.isna(value):
                return None
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            if isinstance(value, np.generic):
                return value.item()
            return value

        return {
            "id": str(row["listing_id"]),
            "mode": clean(row.get("mode")),
            "title": clean(row.get("title")),
            "price": clean(
                row.get("asking_price")
                if row.get("mode") == "sale"
                else row.get("price_monthly")
            ),
            "address": clean(row.get("address")),
            "property_type": clean(row.get("property_type")),
            "room_type": clean(row.get("room_type")),
            "bedrooms": clean(row.get("bedrooms")),
            "bathrooms": clean(row.get("bathrooms")),
            "floor_area_sqft": clean(row.get("floor_area_sqft")),
            "nearest_mrt_name": clean(row.get("nearest_mrt_name")),
            "nearest_mrt_distance_m": clean(row.get("nearest_mrt_distance_m")),
            "listed_on_text": clean(row.get("listed_on_text")),
            "scraped_at": clean(row.get("scraped_at")),
            "town": clean(row.get("resolved_town")),
            "planning_area": clean(row.get("planning_area")),
            "subzone": clean(row.get("subzone")),
            "latitude": clean(row.get("resolved_latitude")),
            "longitude": clean(row.get("resolved_longitude")),
            "location_source": clean(row.get("location_source")),
            "anchor_distance_m": clean(row.get("_anchor_distance_m")),
        }

    def _matching_live_sales(
        self, preferences: UserPreferences, *, limit: int = 12
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        listings = self._load_live_listings()
        if listings.empty:
            return [], {"available": False, "reason": "product listing dataset has not been built"}
        sale = listings.loc[listings["mode"] == "sale"].copy()
        prices = pd.to_numeric(sale.get("asking_price"), errors="coerce")
        sale = sale.loc[prices.notna() & (prices <= preferences.budget)].copy()
        sale["_price"] = pd.to_numeric(sale["asking_price"], errors="coerce")
        applied_filters = [f"asking price <= S${preferences.budget:,.0f}"]

        target_bedrooms: set[int] = set()
        for flat_type in preferences.flat_types:
            match = re.match(r"(\d) ROOM", flat_type)
            if match:
                target_bedrooms.add(max(1, int(match.group(1)) - 1))
            elif flat_type in {"EXECUTIVE", "MULTI-GENERATION"}:
                target_bedrooms.update({3, 4, 5})
        if target_bedrooms:
            bedrooms = pd.to_numeric(sale.get("bedrooms"), errors="coerce")
            sale = sale.loc[bedrooms.isin(target_bedrooms)].copy()
            applied_filters.append(
                "bedrooms in " + ", ".join(str(value) for value in sorted(target_bedrooms))
            )

        if preferences.min_floor_area_sqm is not None:
            area_sqft = pd.to_numeric(sale.get("floor_area_sqft"), errors="coerce")
            minimum_sqft = preferences.min_floor_area_sqm * 10.7639
            sale = sale.loc[area_sqft.notna() & (area_sqft >= minimum_sqft)].copy()
            applied_filters.append(f"floor area >= {preferences.min_floor_area_sqm:g} sqm")

        if preferences.max_mrt_distance_m is not None:
            mrt_distance = pd.to_numeric(sale.get("nearest_mrt_distance_m"), errors="coerce")
            sale = sale.loc[
                mrt_distance.notna() & (mrt_distance <= preferences.max_mrt_distance_m)
            ].copy()
            applied_filters.append(
                f"recorded MRT distance <= {preferences.max_mrt_distance_m:g} m"
            )

        sale["_anchor_distance_m"] = np.nan
        if preferences.anchor_latitude is not None and preferences.anchor_longitude is not None:
            coordinates = sale[["resolved_latitude", "resolved_longitude"]].apply(
                pd.to_numeric, errors="coerce"
            )
            valid = coordinates.notna().all(axis=1)
            if valid.any():
                sale.loc[valid, "_anchor_distance_m"] = haversine_matrix(
                    coordinates.loc[valid].to_numpy(float),
                    np.asarray(
                        [[preferences.anchor_latitude, preferences.anchor_longitude]], dtype=float
                    ),
                )[:, 0]
            if preferences.max_anchor_distance_m is not None:
                distance = pd.to_numeric(sale["_anchor_distance_m"], errors="coerce")
                sale = sale.loc[
                    distance.notna() & (distance <= preferences.max_anchor_distance_m)
                ].copy()
                applied_filters.append(
                    f"straight-line distance to {preferences.anchor_name or 'selected place'} "
                    f"<= {preferences.max_anchor_distance_m:g} m"
                )

        if preferences.preferred_towns:
            sale["_preferred"] = sale["resolved_town"].isin(preferences.preferred_towns)
            if preferences.require_preferred_town:
                sale = sale.loc[sale["_preferred"]].copy()
                applied_filters.append(
                    "town in " + ", ".join(preferences.preferred_towns)
                )
        else:
            sale["_preferred"] = False
        matched_before_limit = len(sale)
        sort_columns = ["_preferred"]
        ascending = [False]
        if preferences.anchor_latitude is not None:
            sort_columns.append("_anchor_distance_m")
            ascending.append(True)
        sort_columns.extend(["scraped_at", "_price"])
        ascending.extend([False, True])
        sale = sale.sort_values(sort_columns, ascending=ascending, kind="mergesort").head(limit)
        return [self._listing_payload(row) for _, row in sale.iterrows()], {
            "available": True,
            "role": "partial PropertyGuru research snapshot; not complete inventory",
            "matched_before_limit": int(matched_before_limit),
            "location_is_optional": (
                preferences.max_anchor_distance_m is None
                and not preferences.require_preferred_town
            ),
            "applied_filters": applied_filters,
        }

    @staticmethod
    def _merge_preferences(
        parsed: dict[str, Any], payload: dict[str, Any]
    ) -> dict[str, Any]:
        result = dict(parsed)
        explicit_fields = (
            "budget",
            "flat_types",
            "preferred_towns",
            "min_floor_area_sqm",
            "min_remaining_lease_years",
            "max_mrt_distance_m",
            "anchor_name",
            "anchor_latitude",
            "anchor_longitude",
            "max_anchor_distance_m",
            "require_preferred_town",
            "weights",
        )
        for field in explicit_fields:
            if field not in payload or payload[field] in (None, ""):
                continue
            value = payload[field]
            if field in {"flat_types", "preferred_towns"} and value == []:
                continue
            if field == "weights" and not isinstance(value, dict):
                raise ValueError("weights must be a JSON object")
            result[field] = value
        return result

    @staticmethod
    def _storey_range(midpoint: float) -> str:
        lower = max(1, int(math.floor((midpoint - 2) / 3) * 3 + 1))
        return f"{lower:02d} TO {lower + 2:02d}"

    def _load_price_model_if_available(self) -> dict[str, Any] | None:
        if self._price_model_checked:
            return self._price_model_artifact
        self._price_model_checked = True
        if not self.settings.model_path.exists():
            return None
        self._price_model_artifact = load_price_model(self.settings.model_path)
        return self._price_model_artifact

    def _add_model_reference_prices(self, ranking: dict[str, Any]) -> None:
        recommendations = ranking.get("recommendations", [])
        if not recommendations:
            return
        try:
            artifact = self._load_price_model_if_available()
            if artifact is None:
                return
            rows: list[dict[str, Any]] = []
            for item in recommendations:
                month = pd.Period(item["last_transaction_month"], freq="M")
                storey_mid = float(item["median_storey"])
                rows.append(
                    {
                        "town": item["town"],
                        "flat_type": item["flat_type"],
                        "flat_model": item["flat_model"],
                        "storey_range": self._storey_range(storey_mid),
                        "floor_area_sqm": item["median_floor_area_sqm"],
                        "remaining_lease_years": item["median_remaining_lease_years"],
                        "storey_mid": storey_mid,
                        "month_index": month.year * 12 + month.month,
                    }
                )
            model_frame = pd.DataFrame(rows, columns=MODEL_FEATURES)
            predictions = artifact["model"].predict(model_frame)
            for item, prediction in zip(recommendations, predictions):
                reference = float(prediction)
                if not np.isfinite(reference):
                    continue
                item["ml_reference_price"] = round(reference, 2)
                item["ml_vs_observed_percent"] = round(
                    (reference / item["median_resale_price"] - 1) * 100, 2
                )
                item["reasons"].append(
                    f"The time-holdout ML model gives a reference price of S${reference:,.0f}; "
                    "the observed 75th percentile remains the budget filter."
                )
            metadata = artifact.get("metadata", {})
            ranking["model_context"] = {
                "available": True,
                "role": "reference estimate only; not used to relax hard constraints",
                "training_end_month": str(metadata.get("training_end_month", ""))[:7] or None,
                "test_end_month": str(metadata.get("test_end_month", ""))[:7] or None,
                "holdout_mape_percent": metadata.get("random_forest", {}).get("mape_percent"),
                "holdout_mae": metadata.get("random_forest", {}).get("mae"),
            }
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            ranking.setdefault("warnings", []).append(
                f"The price-model reference could not be loaded ({type(error).__name__})."
            )

    def get_recommendations(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("request payload must be an object")
        query = str(payload.get("query", "")).strip()
        if len(query) > 2_000:
            raise ValueError("query must be at most 2,000 characters")
        use_llm = payload.get("use_llm", False)
        if not isinstance(use_llm, bool):
            raise ValueError("use_llm must be true or false")
        intent = parse_intent(query, settings=self.settings, use_llm=use_llm)
        merged = self._merge_preferences(intent.values, payload)
        location_query = str(
            payload.get("location_query") or intent.values.get("location_query") or ""
        ).strip()
        has_anchor = (
            merged.get("anchor_latitude") is not None
            and merged.get("anchor_longitude") is not None
        )
        if location_query and not has_anchor:
            location_search = self.search_locations(location_query)
            return {
                "status": "location_confirmation_required",
                "query": query,
                "intent": intent.to_dict(),
                "location_query": location_query,
                "location_candidates": location_search["candidates"],
                "message": "Choose the intended OneMap result before recommendations are calculated.",
            }
        preferences = UserPreferences.from_dict(merged)
        anchor_context = None
        if preferences.anchor_latitude is not None and preferences.anchor_longitude is not None:
            region = self._locations().index.locate(
                preferences.anchor_latitude, preferences.anchor_longitude
            )
            if region is None:
                raise ValueError("confirmed anchor location must fall within Singapore boundaries")
            anchor_context = {
                "name": preferences.anchor_name,
                "latitude": preferences.anchor_latitude,
                "longitude": preferences.anchor_longitude,
                **region,
                "distance_type": "straight-line haversine",
            }
        raw_top_k = payload.get("top_k", 8)
        if isinstance(raw_top_k, bool) or not isinstance(raw_top_k, (int, str)):
            raise ValueError("top_k must be an integer between 1 and 50")
        try:
            top_k = int(raw_top_k)
        except ValueError as error:
            raise ValueError("top_k must be an integer between 1 and 50") from error
        ranking = recommend(self._load_candidates(), preferences, top_k=top_k)
        self._add_model_reference_prices(ranking)
        live_listings, listing_context = self._matching_live_sales(preferences)
        return {
            "query": query,
            "intent": intent.to_dict(),
            "preferences": preferences.to_dict(),
            **ranking,
            "live_listings": live_listings,
            "listing_context": listing_context,
            "anchor_context": anchor_context,
            "disclaimer": (
                "Historical recommendations plus a partial periodically collected listing snapshot; "
                "not a valuation, complete market inventory, or financial advice."
            ),
        }
