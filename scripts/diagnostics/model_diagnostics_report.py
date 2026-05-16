"""
Build report-ready model diagnostics.

Outputs:
  model_results/reports/model_comparison.csv
  model_results/reports/error_structure_diagnostics.json

The script reuses existing XGBoost predictions for final metrics, adds a
linear-regression baseline using the same forecast-strict feature list, and
re-trains the fixed-parameter tuned XGBoost model only for high-error SHAP slice
diagnostics.
"""
from __future__ import annotations

import json
import os
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

from train_xgboost_pipeline import (
    BASELINE_COLUMN,
    FIXED_TUNED_PARAMS,
    MAPE_FLOOR_WH,
    PRIMARY_FEATURES,
    PREDICTIONS_PATH,
    RANDOM_STATE,
    METRICS_PATH,
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


os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / "matplotlib_cache"))
COMPARISON_PATH = REPORTS_DIR / "model_comparison.csv"
DIAGNOSTICS_PATH = REPORTS_DIR / "error_structure_diagnostics.json"


def fit_linear_baseline(split) -> tuple[np.ndarray, np.ndarray]:
    model = make_pipeline(StandardScaler(), LinearRegression())
    model.fit(split.train[PRIMARY_FEATURES], split.train[TARGET_COLUMN])
    validation_predictions = clip_predictions(model.predict(split.validation[PRIMARY_FEATURES]))

    final_model = make_pipeline(StandardScaler(), LinearRegression())
    final_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])
    test_predictions = clip_predictions(final_model.predict(split.test[PRIMARY_FEATURES]))
    return validation_predictions, test_predictions


def load_existing_metrics() -> dict[str, Any]:
    return json.loads(METRICS_PATH.read_text(encoding="utf-8"))


def mape_for_frame(frame: pd.DataFrame, predictions: np.ndarray) -> float:
    mask = metric_mask(frame)
    return robust_mape(frame.loc[mask, TARGET_COLUMN], predictions[mask.to_numpy()])


def comparison_table(split, linear_validation: np.ndarray, linear_test: np.ndarray) -> pd.DataFrame:
    metrics = load_existing_metrics()
    observed_capacity_wh = float(metrics["capacity_normalization"]["observed_capacity_wh"])
    xgb_validation = metrics["validation_metrics"]["robust_metrics"]
    xgb_test = metrics["test_metrics"]["robust_metrics"]

    rows = [
        {
            "model": "Persistence: previous-day same time",
            "validation_mape": metrics["validation_metrics"]["baseline_mape"],
            **{f"test_{key}": value for key, value in xgb_test["baseline"].items()},
        },
        {
            "model": "Linear regression",
            "validation_mape": mape_for_frame(split.validation, linear_validation),
            **{f"test_{key}": value for key, value in regression_metrics(split.test, linear_test, observed_capacity_wh).items()},
        },
        {
            "model": "XGBoost default",
            "validation_mape": metrics["validation_metrics"]["xgb_default_mape"],
            **{f"test_{key}": value for key, value in xgb_test["xgb_default"].items()},
        },
        {
            "model": "XGBoost tuned",
            "validation_mape": metrics["optuna"]["best_cv_mape"],
            **{f"test_{key}": value for key, value in xgb_test["xgb_tuned"].items()},
        },
    ]
    return pd.DataFrame(rows)


def build_test_analysis_frame(split: Any) -> pd.DataFrame:
    predictions = pd.read_csv(PREDICTIONS_PATH, parse_dates=["Time"])
    feature_columns = [
        "Time",
        TARGET_COLUMN,
        "solar_elevation_deg",
        "month",
        "hour",
        "clouds_all",
        "weather_type",
        "ghi_roll_std_3h",
        "clear_sky_index_lag_1h",
        "energy_delta_lag_1h",
        "energy_roll_mean_3h",
    ]
    frame = split.test[feature_columns].merge(predictions, on="Time", how="left")
    frame = frame.rename(columns={TARGET_COLUMN: "target_from_features"})
    frame["y_true"] = frame["y_true"].astype(float)
    frame["xgb_tuned_pred"] = frame["xgb_tuned_pred"].astype(float)
    frame["residual_wh"] = frame["xgb_tuned_pred"] - frame["y_true"]
    frame["abs_error_wh"] = frame["residual_wh"].abs()
    frame["ape_pct"] = frame["abs_error_wh"] / np.maximum(frame["y_true"], MAPE_FLOOR_WH) * 100.0
    frame["is_metric_row"] = (frame["solar_elevation_deg"] > 0) & (frame["y_true"] > 0)
    return frame[frame["is_metric_row"]].copy()


def grouped_summary(frame: pd.DataFrame, group_column: str) -> list[dict[str, Any]]:
    grouped = (
        frame.groupby(group_column, observed=True)
        .agg(
            rows=("Time", "count"),
            mape=("ape_pct", "mean"),
            median_ape=("ape_pct", "median"),
            mae_wh=("abs_error_wh", "mean"),
            bias_wh=("residual_wh", "mean"),
            actual_mean_wh=("y_true", "mean"),
            pred_mean_wh=("xgb_tuned_pred", "mean"),
        )
        .reset_index()
    )
    grouped[group_column] = grouped[group_column].astype(str)
    return grouped.to_dict(orient="records")


def daily_case_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    daily = (
        frame.groupby(frame["Time"].dt.floor("D"))
        .agg(
            rows=("Time", "count"),
            actual_wh=("y_true", "sum"),
            predicted_wh=("xgb_tuned_pred", "sum"),
            mean_clouds_all=("clouds_all", "mean"),
            mean_weather_type=("weather_type", "mean"),
            mean_ghi_roll_std_3h=("ghi_roll_std_3h", "mean"),
            mean_clear_sky_index_lag_1h=("clear_sky_index_lag_1h", "mean"),
        )
        .reset_index(names="date")
    )
    daily["residual_wh"] = daily["predicted_wh"] - daily["actual_wh"]
    daily["abs_error_wh"] = daily["residual_wh"].abs()
    daily["ape_pct"] = daily["abs_error_wh"] / np.maximum(daily["actual_wh"], 1000.0) * 100.0
    worst = daily.sort_values("abs_error_wh", ascending=False).head(10).copy()
    worst["date"] = worst["date"].dt.strftime("%Y-%m-%d")
    return worst.to_dict(orient="records")


def error_structure(split) -> dict[str, Any]:
    frame = build_test_analysis_frame(split)
    target_bins = [-0.001, 50, 100, 200, 500, 1000, 2000, 5000]
    frame["target_bin"] = pd.cut(frame["y_true"], bins=target_bins)
    abs_error_q90 = float(frame["abs_error_wh"].quantile(0.90))
    high_error = frame[frame["abs_error_wh"] >= abs_error_q90].copy()
    over_prediction = frame[frame["residual_wh"] > 0].copy()
    severe_over_prediction = frame[
        (frame["residual_wh"] >= frame["residual_wh"].quantile(0.95))
        & (frame["y_true"] <= frame["y_true"].quantile(0.35))
    ].copy()

    top_over = (
        severe_over_prediction.sort_values("residual_wh", ascending=False)
        .head(12)[
            [
                "Time",
                "y_true",
                "xgb_tuned_pred",
                "residual_wh",
                "ape_pct",
                "clouds_all",
                "weather_type",
                "ghi_roll_std_3h",
                "clear_sky_index_lag_1h",
                "energy_delta_lag_1h",
            ]
        ]
        .copy()
    )
    top_over["Time"] = top_over["Time"].dt.strftime("%Y-%m-%d %H:%M:%S")

    return {
        "shap_high_error": shap_slice_diagnostics(split, frame, abs_error_q90),
        "metric_rows": int(len(frame)),
        "summary": {
            "mean_mape_pct": float(frame["ape_pct"].mean()),
            "median_ape_pct": float(frame["ape_pct"].median()),
            "mean_abs_error_wh": float(frame["abs_error_wh"].mean()),
            "mean_bias_wh": float(frame["residual_wh"].mean()),
            "over_prediction_share_pct": float((frame["residual_wh"] > 0).mean() * 100.0),
            "high_error_threshold_abs_wh_q90": abs_error_q90,
        },
        "by_month": grouped_summary(frame, "month"),
        "by_target_bin": grouped_summary(frame, "target_bin"),
        "high_error_feature_profile": {
            "high_error_rows": int(len(high_error)),
            "high_error_mean_clouds_all": float(high_error["clouds_all"].mean()),
            "all_rows_mean_clouds_all": float(frame["clouds_all"].mean()),
            "high_error_mean_ghi_roll_std_3h": float(high_error["ghi_roll_std_3h"].mean()),
            "all_rows_mean_ghi_roll_std_3h": float(frame["ghi_roll_std_3h"].mean()),
            "high_error_mean_clear_sky_index_lag_1h": float(high_error["clear_sky_index_lag_1h"].mean()),
            "all_rows_mean_clear_sky_index_lag_1h": float(frame["clear_sky_index_lag_1h"].mean()),
            "over_prediction_mean_clouds_all": float(over_prediction["clouds_all"].mean()),
            "severe_over_prediction_rows": int(len(severe_over_prediction)),
        },
        "top_severe_over_prediction_cases": top_over.to_dict(orient="records"),
        "worst_daily_cases": daily_case_summary(frame),
        "interpretation": [
            "The model is strongest on high-generation bins and weakest on low-to-mid generation bins where MAPE is sensitive and cloud transitions dominate.",
            "Large errors are concentrated in cloudy or transition cases where lagged sunlight history can remain high while actual generation collapses.",
            "SHAP indicates that short-term persistence, clear-sky theoretical irradiance, recent variability, clouds_all, and lagged clear-sky index are the key drivers; this supports the interpretation that remaining error comes from weather-state ambiguity rather than an obvious leakage or split bug.",
        ],
    }


def shap_slice_diagnostics(split: Any, analysis_frame: pd.DataFrame, abs_error_threshold: float) -> dict[str, Any]:
    from xgboost import XGBRegressor
    import shap

    metric_times = analysis_frame[["Time", "abs_error_wh"]].copy()
    test_features = split.test[["Time", *PRIMARY_FEATURES]].merge(metric_times, on="Time", how="inner")
    high_error = test_features[test_features["abs_error_wh"] >= abs_error_threshold]

    sample_size = 1000
    all_sample = test_features.sample(n=min(sample_size, len(test_features)), random_state=RANDOM_STATE)
    high_sample = high_error.sample(n=min(sample_size, len(high_error)), random_state=RANDOM_STATE)

    model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
    model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])

    explainer = shap.TreeExplainer(model)
    all_values = explainer.shap_values(all_sample[PRIMARY_FEATURES])
    high_values = explainer.shap_values(high_sample[PRIMARY_FEATURES])

    all_importance = pd.Series(np.abs(all_values).mean(axis=0), index=PRIMARY_FEATURES)
    high_importance = pd.Series(np.abs(high_values).mean(axis=0), index=PRIMARY_FEATURES)
    comparison = (
        pd.DataFrame(
            {
                "feature": PRIMARY_FEATURES,
                "mean_abs_shap_all_metric_sample": all_importance.reindex(PRIMARY_FEATURES).to_numpy(),
                "mean_abs_shap_high_error": high_importance.reindex(PRIMARY_FEATURES).to_numpy(),
            }
        )
        .assign(
            high_error_to_all_ratio=lambda data: data["mean_abs_shap_high_error"]
            / data["mean_abs_shap_all_metric_sample"].replace(0, np.nan)
        )
        .sort_values("mean_abs_shap_high_error", ascending=False)
    )

    return {
        "method": "Tuned XGBoost retrained on dev; SHAP compared between all sampled test metric rows and top-10% absolute-error rows.",
        "all_sample_rows": int(len(all_sample)),
        "high_error_sample_rows": int(len(high_sample)),
        "high_error_abs_threshold_wh": float(abs_error_threshold),
        "top_high_error_features": comparison.head(12).to_dict(orient="records"),
        "features_most_amplified_in_high_error": comparison.sort_values(
            "high_error_to_all_ratio", ascending=False
        ).head(12).to_dict(orient="records"),
    }


def main() -> None:
    for directory in [RESULTS_DIR, REPORTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    frame = load_featured_data()
    split = chronological_split(frame)

    linear_validation, linear_test = fit_linear_baseline(split)
    comparison = comparison_table(split, linear_validation, linear_test)
    comparison.to_csv(COMPARISON_PATH, index=False)

    diagnostics = error_structure(split)
    diagnostics["outputs"] = {
        "model_comparison_csv": str(COMPARISON_PATH),
        "error_structure_diagnostics_json": str(DIAGNOSTICS_PATH),
    }
    DIAGNOSTICS_PATH.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({
        "comparison": comparison[["model", "validation_mape", "test_mape", "test_r2", "test_rmse_wh"]].to_dict(orient="records"),
        "error_summary": diagnostics["summary"],
        "outputs": diagnostics["outputs"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
