"""Application service that grounds every response in the local knowledge base."""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from homelens.config import PROJECT_ROOT, Settings
from homelens.errors import DataUnavailableError
from homelens.intent import parse_intent
from homelens.price_model import MODEL_FEATURES, load_price_model
from homelens.recommender import recommend
from homelens.schemas import UserPreferences


class HomeLensService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_environment()
        self._candidates: pd.DataFrame | None = None
        self._price_model_artifact: dict[str, Any] | None = None
        self._price_model_checked = False

    def _load_candidates(self) -> pd.DataFrame:
        if self._candidates is not None:
            return self._candidates
        path = self.settings.candidates_path
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

    def reload(self) -> None:
        self._candidates = None
        self._load_candidates()

    def health(self) -> dict[str, Any]:
        candidates_path = self.settings.candidates_path
        model_path = self.settings.model_path
        result: dict[str, Any] = {
            "status": "ready" if candidates_path.exists() else "setup_required",
            "candidate_knowledge_base": candidates_path.exists(),
            "price_model": model_path.exists(),
            "integrations": self.settings.integration_status(),
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
        metrics_path = PROJECT_ROOT / "artifacts" / "metrics" / "price_model.json"
        if metrics_path.exists():
            result["price_model_metrics"] = json.loads(metrics_path.read_text(encoding="utf-8"))
        return result

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
        except (OSError, ValueError, KeyError, TypeError) as error:
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
        preferences = UserPreferences.from_dict(merged)
        raw_top_k = payload.get("top_k", 8)
        if isinstance(raw_top_k, bool) or not isinstance(raw_top_k, (int, str)):
            raise ValueError("top_k must be an integer between 1 and 50")
        try:
            top_k = int(raw_top_k)
        except ValueError as error:
            raise ValueError("top_k must be an integer between 1 and 50") from error
        ranking = recommend(self._load_candidates(), preferences, top_k=top_k)
        self._add_model_reference_prices(ranking)
        return {
            "query": query,
            "intent": intent.to_dict(),
            "preferences": preferences.to_dict(),
            **ranking,
            "disclaimer": (
                "Historical transaction evidence and representative block/flat-type options; "
                "not live listings, valuations, or financial advice."
            ),
        }
