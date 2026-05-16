"""
Phase 1 completion: train a 10th-percentile (q10) quantile XGBoost model.

Same feature whitelist and hyperparameters as the tuned point-forecast model.
Outputs:
  model_results/forecast/predictions_quantile_q10.csv   -- 15-min test-set predictions
  model_results/forecast/milp_solar_forecast_hourly.csv -- hourly MILP-ready forecast
  model_results/reports/quantile_coverage.json          -- coverage diagnostics
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
sys.path.insert(0, str(LOCAL_PACKAGE_DIR))

from train_xgboost_pipeline import (
    FIXED_TUNED_PARAMS,
    FORECAST_DIR,
    MAPE_FLOOR_WH,
    PRIMARY_FEATURES,
    PREDICTIONS_PATH,
    RANDOM_STATE,
    REPORTS_DIR,
    RESULTS_DIR,
    TARGET_COLUMN,
    chronological_split,
    load_featured_data,
    metric_mask,
)

Q10_PREDICTIONS_PATH = FORECAST_DIR / "predictions_quantile_q10.csv"
MILP_HOURLY_PATH = FORECAST_DIR / "milp_solar_forecast_hourly.csv"
COVERAGE_PATH = REPORTS_DIR / "quantile_coverage.json"

QUANTILE_ALPHA = 0.1


def make_quantile_model(XGBRegressor):
    return XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=QUANTILE_ALPHA,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        tree_method="hist",
        verbosity=0,
        **FIXED_TUNED_PARAMS,
    )


def coverage_stats(
    frame: pd.DataFrame,
    q10_predictions: np.ndarray,
    point_predictions: np.ndarray,
) -> dict:
    mask = metric_mask(frame)
    y_true = frame.loc[mask, TARGET_COLUMN].to_numpy(dtype=float)
    q10 = q10_predictions[mask.to_numpy()]
    point = point_predictions[mask.to_numpy()]

    below = q10 < y_true
    coverage = float(np.mean(below))

    # mean gap between q10 and actual (should be negative = conservative)
    mean_gap_wh = float(np.mean(q10 - y_true))

    # what fraction of time q10 is actually above actual (bad over-shooting)
    overshoot_rate = float(np.mean(q10 > y_true))

    # mean absolute deviation from point forecast
    mean_abs_spread = float(np.mean(np.abs(point - q10)))

    return {
        "daylight_rows": int(mask.sum()),
        "target_coverage": float(1.0 - QUANTILE_ALPHA),
        "actual_coverage": coverage,
        "overshoot_rate_pct": overshoot_rate * 100.0,
        "mean_gap_wh": mean_gap_wh,
        "mean_abs_spread_from_point_wh": mean_abs_spread,
        "q10_quantiles": {
            str(q): float(np.quantile(q10, q)) for q in [0.05, 0.25, 0.5, 0.75, 0.95]
        },
    }


def resample_to_hourly(
    frame: pd.DataFrame,
    q10_col: str,
    point_col: str,
) -> pd.DataFrame:
    """Sum 15-min Wh values to hourly Wh totals."""
    hourly = (
        frame.set_index("Time")[[point_col, q10_col]]
        .resample("1h")
        .sum()
        .reset_index()
    )
    hourly = hourly.rename(
        columns={
            "Time": "timestamp",
            point_col: "solar_point_wh",
            q10_col: "solar_q10_wh",
        }
    )
    # clip negatives that can arise from model
    hourly["solar_point_wh"] = hourly["solar_point_wh"].clip(lower=0)
    hourly["solar_q10_wh"] = hourly["solar_q10_wh"].clip(lower=0)
    return hourly


def main() -> None:
    import os
    os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / "matplotlib_cache"))
    for directory in [RESULTS_DIR, FORECAST_DIR, REPORTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    from xgboost import XGBRegressor

    print("Loading featured data...")
    frame = load_featured_data()
    split = chronological_split(frame)

    print(f"Training quantile model (alpha={QUANTILE_ALPHA}) on dev set "
          f"({len(split.dev)} rows)...")
    q_model = make_quantile_model(XGBRegressor)
    q_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])

    print("Predicting on test set...")
    q10_raw = q_model.predict(split.test[PRIMARY_FEATURES])
    q10_predictions = np.clip(q10_raw, 0, None)

    # Load point predictions from the existing pipeline output rather than re-training.
    # Fall back to re-training only if the file is missing or timestamps don't align.
    from train_xgboost_pipeline import make_tuned_model, clip_predictions
    point_predictions: np.ndarray
    if PREDICTIONS_PATH.exists():
        existing = pd.read_csv(PREDICTIONS_PATH, parse_dates=["Time"])
        merged = split.test[["Time"]].reset_index(drop=True).merge(
            existing[["Time", "xgb_tuned_pred"]], on="Time", how="left"
        )
        if merged["xgb_tuned_pred"].notna().all():
            point_predictions = merged["xgb_tuned_pred"].to_numpy(dtype=float)
            print(f"Point predictions loaded from {PREDICTIONS_PATH}")
        else:
            print("Timestamp mismatch — re-training point model as fallback...")
            point_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
            point_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])
            point_predictions = clip_predictions(point_model.predict(split.test[PRIMARY_FEATURES]))
    else:
        print("predictions_test.csv not found — re-training point model...")
        point_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
        point_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])
        point_predictions = clip_predictions(point_model.predict(split.test[PRIMARY_FEATURES]))

    # 15-min prediction CSV
    pred_frame = pd.DataFrame(
        {
            "Time": split.test["Time"].values,
            "y_true": split.test[TARGET_COLUMN].values,
            "xgb_tuned_pred": point_predictions,
            "xgb_q10_pred": q10_predictions,
        }
    )
    pred_frame.to_csv(Q10_PREDICTIONS_PATH, index=False)
    print(f"15-min predictions saved → {Q10_PREDICTIONS_PATH}")

    # hourly MILP-ready CSV
    hourly = resample_to_hourly(pred_frame, "xgb_q10_pred", "xgb_tuned_pred")
    hourly.to_csv(MILP_HOURLY_PATH, index=False)
    print(f"Hourly MILP forecast saved → {MILP_HOURLY_PATH}")

    # coverage diagnostics
    stats = coverage_stats(split.test, q10_predictions, point_predictions)
    COVERAGE_PATH.write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n--- Quantile Coverage Report ---")
    print(f"  Daylight rows evaluated : {stats['daylight_rows']:,}")
    print(f"  Target coverage (1-α)   : {stats['target_coverage']:.0%}")
    print(f"  Actual coverage         : {stats['actual_coverage']:.2%}  "
          f"(q10 below actual)")
    print(f"  Overshoot rate          : {stats['overshoot_rate_pct']:.2f}%  "
          f"(q10 above actual — want this low)")
    print(f"  Mean gap (q10 - actual) : {stats['mean_gap_wh']:.1f} Wh")
    print(f"  Mean q10-to-point spread: {stats['mean_abs_spread_from_point_wh']:.1f} Wh")
    print(f"\nCoverage JSON saved → {COVERAGE_PATH}")


if __name__ == "__main__":
    main()
