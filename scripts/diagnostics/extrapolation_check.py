"""
Seasonal extrapolation check.

Train only on 2017 Jan-Jun and evaluate on 2017 Jul-Dec. This tests whether the
forecast-strict feature set generalizes to unseen later-year seasonal patterns.

Outputs:
  model_results/extrapolation_check_2017.csv
  model_results/extrapolation_check_2017.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
sys.path.insert(0, str(LOCAL_PACKAGE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from train_xgboost_pipeline import (
    BASELINE_COLUMN,
    FIXED_TUNED_PARAMS,
    PRIMARY_FEATURES,
    RANDOM_STATE,
    RESULTS_DIR,
    TARGET_COLUMN,
    clip_predictions,
    load_featured_data,
    make_default_model,
    make_tuned_model,
    metric_mask,
    regression_metrics,
)


SUMMARY_CSV = RESULTS_DIR / "extrapolation_check_2017.csv"
SUMMARY_JSON = RESULTS_DIR / "extrapolation_check_2017.json"


def fit_linear(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    model = make_pipeline(StandardScaler(), LinearRegression())
    model.fit(train[PRIMARY_FEATURES], train[TARGET_COLUMN])
    return clip_predictions(model.predict(test[PRIMARY_FEATURES]))


def evaluate_model(name: str, test: pd.DataFrame, predictions: np.ndarray, observed_capacity_wh: float) -> dict[str, Any]:
    metrics = regression_metrics(test, predictions, observed_capacity_wh)
    return {
        "model": name,
        "rows": metrics["rows"],
        "mape": metrics["mape"],
        "r2": metrics["r2"],
        "rmse_wh": metrics["rmse_wh"],
        "mae_wh": metrics["mae_wh"],
        "bias_wh": metrics["bias_wh"],
        "corr": metrics["corr"],
        "nrmse_observed_capacity_pct": metrics["nrmse_observed_capacity_pct"],
    }


def split_2017(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    year = frame[frame["Time"].dt.year == 2017].copy()
    train = year[year["Time"].dt.month <= 6].copy()
    test = year[year["Time"].dt.month >= 7].copy()

    if train.empty or test.empty:
        raise ValueError("2017 Jan-Jun / Jul-Dec split is empty.")
    if not train["Time"].max() < test["Time"].min():
        raise ValueError("Extrapolation split failed: train period is not before test period.")
    return train, test


def run_check() -> dict[str, Any]:
    RESULTS_DIR.mkdir(exist_ok=True)
    frame = load_featured_data()
    observed_capacity_wh = float(frame[TARGET_COLUMN].max())
    train, test = split_2017(frame)

    baseline_predictions = test[BASELINE_COLUMN].to_numpy(dtype=float)
    linear_predictions = fit_linear(train, test)

    default_model = make_default_model(XGBRegressor)
    default_model.fit(train[PRIMARY_FEATURES], train[TARGET_COLUMN])
    default_predictions = clip_predictions(default_model.predict(test[PRIMARY_FEATURES]))

    tuned_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
    tuned_model.fit(train[PRIMARY_FEATURES], train[TARGET_COLUMN])
    tuned_predictions = clip_predictions(tuned_model.predict(test[PRIMARY_FEATURES]))

    rows = [
        evaluate_model("Persistence: previous-day same time", test, baseline_predictions, observed_capacity_wh),
        evaluate_model("Linear regression", test, linear_predictions, observed_capacity_wh),
        evaluate_model("XGBoost default", test, default_predictions, observed_capacity_wh),
        evaluate_model("XGBoost tuned fixed params", test, tuned_predictions, observed_capacity_wh),
    ]
    comparison = pd.DataFrame(rows)
    comparison.to_csv(SUMMARY_CSV, index=False)

    metric_rows = metric_mask(test)
    monthly = []
    monthly_frame = test.loc[metric_rows, ["Time", TARGET_COLUMN]].copy()
    monthly_frame["prediction"] = tuned_predictions[metric_rows.to_numpy()]
    monthly_frame["month"] = monthly_frame["Time"].dt.month
    monthly_frame["abs_error_wh"] = (monthly_frame["prediction"] - monthly_frame[TARGET_COLUMN]).abs()
    monthly_frame["residual_wh"] = monthly_frame["prediction"] - monthly_frame[TARGET_COLUMN]
    for month, group in monthly_frame.groupby("month"):
        denominator = np.maximum(group[TARGET_COLUMN].to_numpy(dtype=float), 100.0)
        mape = np.mean(group["abs_error_wh"].to_numpy(dtype=float) / denominator) * 100.0
        monthly.append(
            {
                "month": int(month),
                "rows": int(len(group)),
                "mape": float(mape),
                "mae_wh": float(group["abs_error_wh"].mean()),
                "bias_wh": float(group["residual_wh"].mean()),
            }
        )

    payload = {
        "method": "Seasonal extrapolation check: train on 2017 Jan-Jun, test on 2017 Jul-Dec.",
        "purpose": "Check whether the model over-relies on seasonal patterns seen during training.",
        "random_state": RANDOM_STATE,
        "train": {
            "rows": int(len(train)),
            "metric_rows": int(metric_mask(train).sum()),
            "start": train["Time"].min().isoformat(),
            "end": train["Time"].max().isoformat(),
        },
        "test": {
            "rows": int(len(test)),
            "metric_rows": int(metric_mask(test).sum()),
            "start": test["Time"].min().isoformat(),
            "end": test["Time"].max().isoformat(),
        },
        "comparison": rows,
        "tuned_monthly_test": monthly,
        "interpretation": [
            "This is stricter than the main chronological split because the model has not seen Jul-Dec seasonal patterns in training.",
            "If tuned XGBoost remains far above persistence and linear regression, the feature set has reasonable seasonal extrapolation ability.",
            "A performance drop versus the main full-history test is expected because the model is trained on only half a year.",
        ],
        "outputs": {
            "summary_csv": str(SUMMARY_CSV),
            "summary_json": str(SUMMARY_JSON),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> None:
    payload = run_check()
    print(json.dumps(
        {
            "train": payload["train"],
            "test": payload["test"],
            "comparison": payload["comparison"],
            "outputs": payload["outputs"],
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
