"""Chronological price experiment with a strong, interpretable baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from homelens.config import PROJECT_ROOT, ensure_output_directories, load_project_config
from homelens.utils import write_json


CATEGORICAL_FEATURES = ["town", "flat_type", "flat_model", "storey_range"]
NUMERIC_FEATURES = [
    "floor_area_sqm",
    "remaining_lease_years",
    "storey_mid",
    "month_index",
]
MODEL_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET = "resale_price"


@dataclass
class HierarchicalMedianBaseline:
    group_medians: dict[tuple[str, str], float] | None = None
    flat_type_medians: dict[str, float] | None = None
    global_median: float = 0.0

    def fit(self, frame: pd.DataFrame) -> "HierarchicalMedianBaseline":
        self.group_medians = (
            frame.groupby(["town", "flat_type"])[TARGET].median().astype(float).to_dict()
        )
        self.flat_type_medians = frame.groupby("flat_type")[TARGET].median().astype(float).to_dict()
        self.global_median = float(frame[TARGET].median())
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.group_medians is None or self.flat_type_medians is None:
            raise RuntimeError("baseline must be fitted before prediction")
        predictions = []
        for row in frame[["town", "flat_type"]].itertuples(index=False):
            value = self.group_medians.get((row.town, row.flat_type))
            if value is None:
                value = self.flat_type_medians.get(row.flat_type, self.global_median)
            predictions.append(value)
        return np.asarray(predictions, dtype=float)


def chronological_split(
    frame: pd.DataFrame, test_months: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    if frame.empty:
        raise ValueError("cannot split an empty dataset")
    maximum_month = pd.Timestamp(frame["month"].max())
    cutoff = maximum_month - pd.DateOffset(months=test_months - 1)
    train = frame.loc[frame["month"] < cutoff].copy()
    test = frame.loc[frame["month"] >= cutoff].copy()
    if len(train) < 20 or len(test) < 5:
        raise ValueError(
            "not enough chronological coverage; need at least 20 train and 5 test rows"
        )
    if train["month"].max() >= test["month"].min():
        raise AssertionError("chronological split leaked future records into training")
    return train, test, cutoff


def _metrics(actual: pd.Series | np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    absolute_percentage = np.abs(actual_array - predicted_array) / np.maximum(actual_array, 1.0)
    return {
        "mae": float(mean_absolute_error(actual_array, predicted_array)),
        "rmse": float(np.sqrt(mean_squared_error(actual_array, predicted_array))),
        "mape_percent": float(np.mean(absolute_percentage) * 100),
        "r2": float(r2_score(actual_array, predicted_array)),
    }


def build_model(random_seed: int = 42, n_estimators: int = 120) -> Pipeline:
    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("one_hot", OneHotEncoder(handle_unknown="ignore", min_frequency=2)),
        ]
    )
    numeric = Pipeline(steps=[("imputer", SimpleImputer(strategy="median"))])
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", categorical, CATEGORICAL_FEATURES),
            ("numeric", numeric, NUMERIC_FEATURES),
        ]
    )
    regressor = RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=20,
        min_samples_leaf=3,
        max_features=0.8,
        n_jobs=-1,
        random_state=random_seed,
    )
    return Pipeline(steps=[("preprocess", preprocessor), ("regressor", regressor)])


def train_price_model(
    clean: pd.DataFrame,
    *,
    output_path: Path | None = None,
    metrics_path: Path | None = None,
    test_months: int | None = None,
    random_seed: int | None = None,
    n_estimators: int = 120,
) -> dict[str, Any]:
    config = load_project_config()
    seed = int(random_seed if random_seed is not None else config["random_seed"])
    holdout_months = int(test_months or config["test_months"])
    model_frame = clean.dropna(subset=MODEL_FEATURES + [TARGET, "month"]).copy()
    source_maximum_month = pd.Timestamp(model_frame["month"].max())
    latest_month_is_partial = (
        source_maximum_month.to_period("M") == pd.Timestamp.now().to_period("M")
    )
    partial_month_rows_excluded = 0
    if latest_month_is_partial:
        partial_month_rows_excluded = int(
            (model_frame["month"] == source_maximum_month).sum()
        )
        model_frame = model_frame.loc[model_frame["month"] < source_maximum_month].copy()
    train, test, cutoff = chronological_split(model_frame, holdout_months)

    baseline = HierarchicalMedianBaseline().fit(train)
    baseline_predictions = baseline.predict(test)
    baseline_metrics = _metrics(test[TARGET], baseline_predictions)

    model = build_model(random_seed=seed, n_estimators=n_estimators)
    model.fit(train[MODEL_FEATURES], train[TARGET])
    model_predictions = model.predict(test[MODEL_FEATURES])
    model_metrics = _metrics(test[TARGET], model_predictions)

    improvement = (
        (baseline_metrics["mae"] - model_metrics["mae"]) / baseline_metrics["mae"] * 100
        if baseline_metrics["mae"] > 0
        else 0.0
    )
    metadata = {
        "experiment": "chronological HDB resale-price holdout",
        "feature_columns": MODEL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "target": TARGET,
        "training_rows": int(len(train)),
        "test_rows": int(len(test)),
        "training_start_month": train["month"].min(),
        "training_end_month": train["month"].max(),
        "test_start_month": test["month"].min(),
        "test_end_month": test["month"].max(),
        "cutoff_month": cutoff,
        "test_months": holdout_months,
        "source_latest_month": source_maximum_month,
        "source_latest_month_was_partial_and_excluded": latest_month_is_partial,
        "partial_month_rows_excluded": partial_month_rows_excluded,
        "random_seed": seed,
        "n_estimators": n_estimators,
        "baseline": baseline_metrics,
        "random_forest": model_metrics,
        "mae_improvement_over_baseline_percent": float(improvement),
    }

    ensure_output_directories()
    output_path = output_path or PROJECT_ROOT / "artifacts" / "models" / "price_model.joblib"
    metrics_path = metrics_path or PROJECT_ROOT / "artifacts" / "metrics" / "price_model.json"
    artifact = {"model": model, "baseline": baseline, "metadata": metadata}
    joblib.dump(artifact, output_path, compress=3)
    write_json(metrics_path, metadata)
    return {"artifact_path": output_path, "metrics_path": metrics_path, **metadata}


def load_price_model(path: Path | None = None) -> dict[str, Any]:
    model_path = path or PROJECT_ROOT / "artifacts" / "models" / "price_model.joblib"
    return joblib.load(model_path)
