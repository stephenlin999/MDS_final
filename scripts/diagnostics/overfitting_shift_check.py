"""
Check overfitting and distribution shift for the tuned XGBoost model.

Outputs:
  model_results/reports/overfitting_shift_diagnostics.json
  model_results/reports/test_monthly_shift_metrics.csv
  model_results/reports/full_range_monthly_shift_metrics.csv
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

from xgboost import XGBRegressor

from train_xgboost_pipeline import (
    FIXED_TUNED_PARAMS,
    MAPE_FLOOR_WH,
    PRIMARY_FEATURES,
    REPORTS_DIR,
    RESULTS_DIR,
    TARGET_COLUMN,
    chronological_split,
    clip_predictions,
    load_featured_data,
    make_tuned_model,
    metric_mask,
    regression_metrics,
    robust_mape,
)


DIAGNOSTICS_JSON = REPORTS_DIR / "overfitting_shift_diagnostics.json"
MONTHLY_CSV = REPORTS_DIR / "test_monthly_shift_metrics.csv"
FULL_RANGE_MONTHLY_CSV = REPORTS_DIR / "full_range_monthly_shift_metrics.csv"


def evaluate_frame(frame: pd.DataFrame, predictions: np.ndarray, observed_capacity_wh: float) -> dict[str, Any]:
    return regression_metrics(frame, predictions, observed_capacity_wh)


def month_metrics(frame: pd.DataFrame, predictions: np.ndarray, observed_capacity_wh: float) -> pd.DataFrame:
    work = frame[["Time", TARGET_COLUMN, "solar_elevation_deg"]].copy()
    work["prediction"] = predictions
    work = work[metric_mask(work.rename(columns={"prediction": "_prediction"}))].copy()
    work["month"] = work["Time"].dt.month
    work["year_month"] = work["Time"].dt.to_period("M").astype(str)

    rows: list[dict[str, Any]] = []
    for year_month, group in work.groupby("year_month", sort=True):
        actual = group[TARGET_COLUMN].to_numpy(dtype=float)
        pred = group["prediction"].to_numpy(dtype=float)
        residual = pred - actual
        ss_res = float(np.sum((actual - pred) ** 2))
        ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
        rmse = float(np.sqrt(np.mean(residual**2)))
        rows.append(
            {
                "year_month": year_month,
                "month": int(group["month"].iloc[0]),
                "rows": int(len(group)),
                "mape": robust_mape(actual, pred),
                "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
                "rmse_wh": rmse,
                "mae_wh": float(np.mean(np.abs(residual))),
                "bias_wh": float(np.mean(residual)),
                "nrmse_observed_capacity_pct": rmse / observed_capacity_wh * 100.0,
                "actual_mean_wh": float(np.mean(actual)),
                "prediction_mean_wh": float(np.mean(pred)),
            }
        )
    return pd.DataFrame(rows)


def full_range_month_metrics(
    split: Any,
    train_predictions: np.ndarray,
    validation_predictions: np.ndarray,
    test_predictions: np.ndarray,
    observed_capacity_wh: float,
) -> pd.DataFrame:
    parts = [
        split.train.assign(_segment="train", _prediction=train_predictions),
        split.validation.assign(_segment="validation", _prediction=validation_predictions),
        split.test.assign(_segment="test", _prediction=test_predictions),
    ]
    full = pd.concat(parts, axis=0).sort_values("Time")
    full = full.loc[metric_mask(full)].copy()
    full["year_month"] = full["Time"].dt.to_period("M").astype(str)
    full["month"] = full["Time"].dt.month
    full["year"] = full["Time"].dt.year

    rows: list[dict[str, Any]] = []
    for year_month, group in full.groupby("year_month", sort=True):
        actual = group[TARGET_COLUMN].to_numpy(dtype=float)
        pred = group["_prediction"].to_numpy(dtype=float)
        residual = pred - actual
        ss_res = float(np.sum((actual - pred) ** 2))
        ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
        rmse = float(np.sqrt(np.mean(residual**2)))
        segment_counts = group["_segment"].value_counts().to_dict()
        rows.append(
            {
                "year_month": year_month,
                "year": int(group["year"].iloc[0]),
                "month": int(group["month"].iloc[0]),
                "dominant_segment": str(group["_segment"].mode().iloc[0]),
                "train_rows": int(segment_counts.get("train", 0)),
                "validation_rows": int(segment_counts.get("validation", 0)),
                "test_rows": int(segment_counts.get("test", 0)),
                "metric_rows": int(len(group)),
                "mape": robust_mape(actual, pred),
                "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
                "rmse_wh": rmse,
                "mae_wh": float(np.mean(np.abs(residual))),
                "bias_wh": float(np.mean(residual)),
                "nrmse_observed_capacity_pct": rmse / observed_capacity_wh * 100.0,
                "actual_mean_wh": float(np.mean(actual)),
                "actual_p10_wh": float(np.quantile(actual, 0.10)),
                "actual_p50_wh": float(np.quantile(actual, 0.50)),
                "actual_p90_wh": float(np.quantile(actual, 0.90)),
                "prediction_mean_wh": float(np.mean(pred)),
                "clouds_all_mean": float(group["clouds_all"].mean()) if "clouds_all" in group else float("nan"),
                "solar_elevation_mean_deg": float(group["solar_elevation_deg"].mean()),
                "ghi_roll_std_3h_mean": float(group["ghi_roll_std_3h"].mean()) if "ghi_roll_std_3h" in group else float("nan"),
            }
        )
    return pd.DataFrame(rows)


def aggregate_month_number(monthly: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for month, group in monthly.groupby("month", sort=True):
        rows.append(
            {
                "month": int(month),
                "periods": int(len(group)),
                "mean_mape": float(group["mape"].mean()),
                "mean_r2": float(group["r2"].mean()),
                "mean_rmse_wh": float(group["rmse_wh"].mean()),
                "mean_bias_wh": float(group["bias_wh"].mean()),
            }
        )
    return rows


def run_check() -> dict[str, Any]:
    for directory in [RESULTS_DIR, REPORTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    frame = load_featured_data()
    observed_capacity_wh = float(frame[TARGET_COLUMN].max())
    split = chronological_split(frame)

    tuned_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
    tuned_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])

    train_predictions = clip_predictions(tuned_model.predict(split.train[PRIMARY_FEATURES]))
    validation_predictions = clip_predictions(tuned_model.predict(split.validation[PRIMARY_FEATURES]))
    dev_predictions = clip_predictions(tuned_model.predict(split.dev[PRIMARY_FEATURES]))
    test_predictions = clip_predictions(tuned_model.predict(split.test[PRIMARY_FEATURES]))

    frame_metrics = {
        "train": evaluate_frame(split.train, train_predictions, observed_capacity_wh),
        "validation": evaluate_frame(split.validation, validation_predictions, observed_capacity_wh),
        "dev_fit_set": evaluate_frame(split.dev, dev_predictions, observed_capacity_wh),
        "test": evaluate_frame(split.test, test_predictions, observed_capacity_wh),
    }

    monthly = month_metrics(split.test, test_predictions, observed_capacity_wh)
    monthly.to_csv(MONTHLY_CSV, index=False)
    full_monthly = full_range_month_metrics(
        split,
        train_predictions,
        validation_predictions,
        test_predictions,
        observed_capacity_wh,
    )
    full_monthly.to_csv(FULL_RANGE_MONTHLY_CSV, index=False)

    train_test_gap = {
        "r2_gap_dev_minus_test": float(frame_metrics["dev_fit_set"]["r2"] - frame_metrics["test"]["r2"]),
        "mape_gap_test_minus_dev": float(frame_metrics["test"]["mape"] - frame_metrics["dev_fit_set"]["mape"]),
        "rmse_gap_test_minus_dev_wh": float(frame_metrics["test"]["rmse_wh"] - frame_metrics["dev_fit_set"]["rmse_wh"]),
    }

    worst_months = monthly.sort_values("mape", ascending=False).head(6).to_dict(orient="records")
    best_months = monthly.sort_values("mape", ascending=True).head(6).to_dict(orient="records")

    payload = {
        "method": "Tuned XGBoost fixed params retrained on dev, then evaluated on train/validation/dev/test and test months.",
        "data_note": "Current featured dataset spans multiple years; final test is 2021-07-14 to 2022-08-31, not only Oct-Dec 2017.",
        "split_ranges": {
            "train": {
                "rows": int(len(split.train)),
                "start": split.train["Time"].min().isoformat(),
                "end": split.train["Time"].max().isoformat(),
            },
            "validation": {
                "rows": int(len(split.validation)),
                "start": split.validation["Time"].min().isoformat(),
                "end": split.validation["Time"].max().isoformat(),
            },
            "dev_fit_set": {
                "rows": int(len(split.dev)),
                "start": split.dev["Time"].min().isoformat(),
                "end": split.dev["Time"].max().isoformat(),
            },
            "test": {
                "rows": int(len(split.test)),
                "start": split.test["Time"].min().isoformat(),
                "end": split.test["Time"].max().isoformat(),
            },
        },
        "frame_metrics": frame_metrics,
        "train_test_gap": train_test_gap,
        "test_monthly_metrics": monthly.to_dict(orient="records"),
        "full_range_monthly_metrics": full_monthly.to_dict(orient="records"),
        "test_month_number_summary": aggregate_month_number(monthly),
        "full_range_month_number_summary": aggregate_month_number(full_monthly),
        "full_range_worst_months_by_mape": full_monthly.sort_values("mape", ascending=False).head(10).to_dict(orient="records"),
        "full_range_lowest_generation_months": full_monthly.sort_values("actual_mean_wh", ascending=True).head(10).to_dict(orient="records"),
        "worst_months_by_mape": worst_months,
        "best_months_by_mape": best_months,
        "interpretation": {
            "overfitting": "Judge by dev-vs-test R2/MAPE/RMSE gap. A small gap suggests no severe overfitting; a very large train/dev advantage would indicate overfit.",
            "distribution_shift": "Judge by month-to-month test metrics. Weak winter months with low actual generation suggest seasonal distribution shift and MAPE sensitivity.",
        },
        "outputs": {
            "diagnostics_json": str(DIAGNOSTICS_JSON),
            "monthly_csv": str(MONTHLY_CSV),
            "full_range_monthly_csv": str(FULL_RANGE_MONTHLY_CSV),
        },
    }
    DIAGNOSTICS_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def main() -> None:
    payload = run_check()
    print(json.dumps(
        {
            "frame_metrics": payload["frame_metrics"],
            "train_test_gap": payload["train_test_gap"],
            "worst_months_by_mape": payload["worst_months_by_mape"],
            "outputs": payload["outputs"],
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
