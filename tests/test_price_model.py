from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from homelens.data.hdb import demo_hdb_frame  # noqa: E402
from homelens.features import clean_hdb_transactions  # noqa: E402
from homelens.price_model import (  # noqa: E402
    MODEL_FEATURES,
    chronological_split,
    train_price_model,
)


class PriceModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.clean, _ = clean_hdb_transactions(demo_hdb_frame())

    def test_time_split_has_no_overlap(self) -> None:
        train, test, cutoff = chronological_split(self.clean, test_months=6)
        self.assertLess(train["month"].max(), test["month"].min())
        self.assertEqual(test["month"].min(), cutoff)

    def test_training_metrics_and_reload_are_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            metrics_path = Path(directory) / "metrics.json"
            partial = self.clean.tail(5).copy()
            partial["month"] = pd.Timestamp.now().to_period("M").to_timestamp()
            augmented = pd.concat([self.clean, partial], ignore_index=True)
            result = train_price_model(
                augmented,
                output_path=model_path,
                metrics_path=metrics_path,
                test_months=6,
                n_estimators=12,
            )
            self.assertTrue(model_path.exists())
            self.assertTrue(metrics_path.exists())
            self.assertLess(result["random_forest"]["mae"], result["baseline"]["mae"])
            self.assertTrue(result["source_latest_month_was_partial_and_excluded"])
            self.assertEqual(result["partial_month_rows_excluded"], 5)
            artifact_a = joblib.load(model_path)
            predictions_a = artifact_a["model"].predict(self.clean[MODEL_FEATURES].tail(5))
            artifact_b = joblib.load(model_path)
            predictions_b = artifact_b["model"].predict(self.clean[MODEL_FEATURES].tail(5))
            np.testing.assert_allclose(predictions_a, predictions_b, rtol=0, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
