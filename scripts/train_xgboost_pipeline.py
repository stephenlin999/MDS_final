from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
FEATURED_PATH = PROJECT_DIR / "Renewable_featured.csv"
RESULTS_DIR = PROJECT_DIR / "model_results"
METRICS_PATH = RESULTS_DIR / "metrics.json"
PREDICTIONS_PATH = RESULTS_DIR / "predictions_test.csv"
SHAP_SUMMARY_PATH = RESULTS_DIR / "shap_summary.png"
SHAP_IMPORTANCE_PATH = RESULTS_DIR / "shap_importance.csv"
PREDICTION_SCATTER_PATH = RESULTS_DIR / "prediction_scatter_tuned.png"
RESIDUAL_BY_MONTH_PATH = RESULTS_DIR / "residual_by_month.png"
RESIDUAL_BY_TARGET_BIN_PATH = RESULTS_DIR / "residual_by_target_bin.png"
APE_BY_TARGET_BIN_PATH = RESULTS_DIR / "ape_by_target_bin.png"

TARGET_COLUMN = "Energy delta[Wh]"
BASELINE_COLUMN = "energy_delta_lag_1d"
MAPE_FLOOR_WH = float(os.environ.get("MAPE_FLOOR_WH", "100"))
REPORTED_CAPACITY_WH = 7700.0
RANDOM_STATE = 42
TEST_FRACTION = 0.20
VALIDATION_FRACTION_OF_DEV = 0.20
OPTUNA_TRIALS = int(os.environ.get("OPTUNA_TRIALS", "40"))
OPTUNA_CV_SPLITS = 3
SHAP_SAMPLE_SIZE = 2000
FIXED_TUNED_PARAMS = {
    "max_depth": 8,
    "learning_rate": 0.02140235297964198,
    "subsample": 0.6454562418017751,
    "n_estimators": 751,
}
FIXED_TUNED_CV_MAPE = 38.75239522553416

PRIMARY_FEATURES = [
    "solar_elevation_deg",
    "solar_zenith_deg",
    "solar_azimuth_deg",
    "cos_solar_zenith",
    "ghi_clear_sky_wm2",
    "dni_clear_sky_wm2",
    "dhi_clear_sky_wm2",
    "ghi_toa_horizontal_wm2",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "month_sin",
    "month_cos",
    "season",
    "is_weekend",
    "temp",
    "pressure",
    "humidity",
    "wind_speed",
    "rain_1h",
    "snow_1h",
    "clouds_all",
    "weather_type",
    "ghi_lag_1h",
    "ghi_lag_3h",
    "ghi_lag_1d",
    "clear_sky_index_lag_1h",
    "clear_sky_index_lag_3h",
    "clear_sky_index_lag_1d",
    "energy_delta_lag_1h",
    "energy_delta_lag_3h",
    "energy_delta_lag_1d",
    "ghi_roll_mean_3h",
    "ghi_roll_std_3h",
    "energy_roll_mean_3h",
]

FORBIDDEN_PRIMARY_FEATURES = {
    "GHI",
    "clear_sky_index",
    "cloud_cover_proxy",
    "temp_x_ghi",
    "humidity_x_cloud_cover",
    "wind_x_clear_sky_index",
}


@dataclass(frozen=True)
class SplitData:
    train: pd.DataFrame
    validation: pd.DataFrame
    dev: pd.DataFrame
    test: pd.DataFrame


def add_local_packages_to_path() -> None:
    if LOCAL_PACKAGE_DIR.exists():
        sys.path.insert(0, str(LOCAL_PACKAGE_DIR))


def load_model_libraries():
    add_local_packages_to_path()
    RESULTS_DIR.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / "matplotlib_cache"))

    import matplotlib

    matplotlib.use("Agg")

    import matplotlib.pyplot as plt
    import optuna
    import shap
    from optuna.samplers import TPESampler
    from sklearn.model_selection import TimeSeriesSplit
    from xgboost import XGBRegressor

    return {
        "plt": plt,
        "optuna": optuna,
        "shap": shap,
        "TPESampler": TPESampler,
        "TimeSeriesSplit": TimeSeriesSplit,
        "XGBRegressor": XGBRegressor,
    }


def robust_mape(y_true: pd.Series | np.ndarray, y_pred: pd.Series | np.ndarray) -> float:
    y_true_array = np.asarray(y_true, dtype=float)
    y_pred_array = np.asarray(y_pred, dtype=float)
    denominator = np.maximum(y_true_array, MAPE_FLOOR_WH)
    return float(np.mean(np.abs((y_true_array - y_pred_array) / denominator)) * 100.0)


def metric_mask(frame: pd.DataFrame) -> pd.Series:
    return (frame["solar_elevation_deg"] > 0) & (frame[TARGET_COLUMN] > 0)


def require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def load_featured_data() -> pd.DataFrame:
    required_columns = ["Time", TARGET_COLUMN, BASELINE_COLUMN, *PRIMARY_FEATURES]
    frame = pd.read_csv(FEATURED_PATH, parse_dates=["Time"]).sort_values("Time")
    require_columns(frame, required_columns)

    forbidden_present = sorted(FORBIDDEN_PRIMARY_FEATURES.intersection(PRIMARY_FEATURES))
    if forbidden_present:
        raise ValueError(f"Primary feature list contains forbidden leakage-prone features: {forbidden_present}")

    model_columns = [TARGET_COLUMN, BASELINE_COLUMN, *PRIMARY_FEATURES]
    frame = frame.dropna(subset=model_columns).reset_index(drop=True)
    return frame


def chronological_split(frame: pd.DataFrame) -> SplitData:
    test_start = int(len(frame) * (1.0 - TEST_FRACTION))
    dev = frame.iloc[:test_start].copy()
    test = frame.iloc[test_start:].copy()

    validation_start = int(len(dev) * (1.0 - VALIDATION_FRACTION_OF_DEV))
    train = dev.iloc[:validation_start].copy()
    validation = dev.iloc[validation_start:].copy()

    if not (train["Time"].max() < validation["Time"].min() < test["Time"].min()):
        raise ValueError("Chronological split failed: train < validation < test is not true.")

    return SplitData(train=train, validation=validation, dev=dev, test=test)


def x_y(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    return frame[PRIMARY_FEATURES], frame[TARGET_COLUMN]


def make_default_model(XGBRegressor):
    return XGBRegressor(
        objective="reg:squarederror",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        tree_method="hist",
        verbosity=0,
    )


def make_tuned_model(XGBRegressor, best_params: dict[str, Any]):
    return XGBRegressor(
        objective="reg:squarederror",
        random_state=RANDOM_STATE,
        n_jobs=-1,
        tree_method="hist",
        verbosity=0,
        **best_params,
    )


def clip_predictions(predictions: np.ndarray) -> np.ndarray:
    return np.clip(predictions, 0, None)


def mape_on_frame(frame: pd.DataFrame, predictions: np.ndarray) -> float:
    mask = metric_mask(frame)
    if not bool(mask.any()):
        raise ValueError("MAPE mask selected zero rows.")
    return robust_mape(frame.loc[mask, TARGET_COLUMN], predictions[mask.to_numpy()])


def evaluate_baseline(frame: pd.DataFrame) -> float:
    return mape_on_frame(frame, frame[BASELINE_COLUMN].to_numpy())


def regression_metrics(
    frame: pd.DataFrame,
    predictions: np.ndarray,
    observed_capacity_wh: float,
) -> dict[str, float | int]:
    mask = metric_mask(frame)
    y_true = frame.loc[mask, TARGET_COLUMN].to_numpy(dtype=float)
    y_pred = np.asarray(predictions, dtype=float)[mask.to_numpy()]

    residual = y_pred - y_true
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    corr = float(np.corrcoef(y_true, y_pred)[0, 1]) if len(y_true) > 1 else float("nan")

    return {
        "rows": int(len(y_true)),
        "mape": robust_mape(y_true, y_pred),
        "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
        "rmse_wh": rmse,
        "mae_wh": mae,
        "bias_wh": float(np.mean(residual)),
        "corr": corr,
        "nrmse_observed_capacity_pct": rmse / observed_capacity_wh * 100.0,
        "nrmse_reported_capacity_pct": rmse / REPORTED_CAPACITY_WH * 100.0,
    }


def fit_default_model(split: SplitData, XGBRegressor):
    model = make_default_model(XGBRegressor)
    X_train, y_train = x_y(split.train)
    model.fit(X_train, y_train)
    return model


def tune_model(split: SplitData, libs: dict[str, Any]) -> tuple[dict[str, Any], float, list[dict[str, Any]]]:
    optuna = libs["optuna"]
    TPESampler = libs["TPESampler"]
    TimeSeriesSplit = libs["TimeSeriesSplit"]
    XGBRegressor = libs["XGBRegressor"]

    X_train, y_train = x_y(split.train)
    cv = TimeSeriesSplit(n_splits=OPTUNA_CV_SPLITS)
    trials: list[dict[str, Any]] = []

    def objective(trial) -> float:
        params = {
            "max_depth": trial.suggest_int("max_depth", 6, 8),
            "learning_rate": trial.suggest_float("learning_rate", 0.015, 0.08, log=True),
            "subsample": trial.suggest_float("subsample", 0.60, 0.85),
            "n_estimators": trial.suggest_int("n_estimators", 650, 1200),
        }
        fold_scores = []
        for train_index, validation_index in cv.split(X_train):
            train_fold = split.train.iloc[train_index]
            validation_fold = split.train.iloc[validation_index]
            model = make_tuned_model(XGBRegressor, params)
            model.fit(
                train_fold[PRIMARY_FEATURES],
                train_fold[TARGET_COLUMN],
            )
            predictions = clip_predictions(model.predict(validation_fold[PRIMARY_FEATURES]))
            fold_scores.append(mape_on_frame(validation_fold, predictions))
        score = float(np.mean(fold_scores))
        trials.append({"number": trial.number, "params": params, "cv_mape": score})
        return score

    study = optuna.create_study(
        direction="minimize",
        sampler=TPESampler(seed=RANDOM_STATE),
    )
    study.optimize(objective, n_trials=OPTUNA_TRIALS, show_progress_bar=False)

    return dict(study.best_params), float(study.best_value), trials


def summarize_split(frame: pd.DataFrame) -> dict[str, Any]:
    mask = metric_mask(frame)
    return {
        "rows": int(len(frame)),
        "metric_rows": int(mask.sum()),
        "start_time": str(frame["Time"].min()),
        "end_time": str(frame["Time"].max()),
    }


def baseline_error_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    metric_frame = frame.loc[metric_mask(frame)].copy()
    metric_frame["baseline_ape"] = (
        (metric_frame[TARGET_COLUMN] - metric_frame[BASELINE_COLUMN]).abs()
        / np.maximum(metric_frame[TARGET_COLUMN], MAPE_FLOOR_WH)
        * 100.0
    )
    metric_frame["month"] = metric_frame["Time"].dt.month
    metric_frame["hour"] = metric_frame["Time"].dt.hour
    metric_frame["target_bin"] = pd.cut(
        metric_frame[TARGET_COLUMN],
        bins=[0, 50, 100, 200, 500, 1000, 2000, 5000],
        include_lowest=True,
    ).astype(str)

    def summarize(grouped) -> list[dict[str, Any]]:
        return [
            {
                "group": str(index),
                "count": int(row["count"]),
                "mean_mape": float(row["mean"]),
                "median_mape": float(row["median"]),
            }
            for index, row in grouped["baseline_ape"].agg(["count", "mean", "median"]).iterrows()
        ]

    return {
        "baseline_mape_quantiles": {
            str(q): float(metric_frame["baseline_ape"].quantile(q))
            for q in [0.5, 0.75, 0.9, 0.95, 0.99]
        },
        "by_month": summarize(metric_frame.groupby("month", observed=True)),
        "by_hour": summarize(metric_frame.groupby("hour", observed=True)),
        "by_target_bin": summarize(metric_frame.groupby("target_bin", observed=True)),
        "top_errors": metric_frame.sort_values("baseline_ape", ascending=False)
        .head(20)[["Time", TARGET_COLUMN, BASELINE_COLUMN, "solar_elevation_deg", "baseline_ape"]]
        .assign(Time=lambda x: x["Time"].astype(str))
        .to_dict(orient="records"),
    }


def plot_diagnostics(test_frame: pd.DataFrame, tuned_predictions: np.ndarray, libs: dict[str, Any]) -> dict[str, str]:
    plt = libs["plt"]
    metric_frame = test_frame.loc[metric_mask(test_frame)].copy()
    metric_frame["prediction"] = tuned_predictions[metric_mask(test_frame).to_numpy()]
    metric_frame["residual"] = metric_frame["prediction"] - metric_frame[TARGET_COLUMN]
    metric_frame["abs_percentage_error"] = (
        metric_frame["residual"].abs() / np.maximum(metric_frame[TARGET_COLUMN], MAPE_FLOOR_WH) * 100.0
    )
    metric_frame["month"] = metric_frame["Time"].dt.month
    metric_frame["target_bin"] = pd.cut(
        metric_frame[TARGET_COLUMN],
        bins=[0, 100, 500, 1000, 2000, 5000],
        include_lowest=True,
    ).astype(str)

    max_axis = float(max(metric_frame[TARGET_COLUMN].max(), metric_frame["prediction"].max()))
    plt.figure(figsize=(7, 7))
    plt.scatter(metric_frame[TARGET_COLUMN], metric_frame["prediction"], s=5, alpha=0.25)
    plt.plot([0, max_axis], [0, max_axis], color="black", linewidth=1)
    plt.xlabel("Actual Energy delta[Wh]")
    plt.ylabel("Tuned XGBoost prediction[Wh]")
    plt.title("Tuned Prediction vs Actual")
    plt.tight_layout()
    plt.savefig(PREDICTION_SCATTER_PATH, dpi=200, bbox_inches="tight")
    plt.close()

    monthly = metric_frame.groupby("month", observed=True)["residual"].mean()
    plt.figure(figsize=(8, 4))
    monthly.plot(kind="bar")
    plt.axhline(0, color="black", linewidth=1)
    plt.xlabel("Month")
    plt.ylabel("Mean residual [Wh]")
    plt.title("Mean Residual By Month")
    plt.tight_layout()
    plt.savefig(RESIDUAL_BY_MONTH_PATH, dpi=200, bbox_inches="tight")
    plt.close()

    residual_by_bin = metric_frame.groupby("target_bin", observed=True)["residual"].mean()
    plt.figure(figsize=(8, 4))
    residual_by_bin.plot(kind="bar")
    plt.axhline(0, color="black", linewidth=1)
    plt.xlabel("Actual generation bin [Wh]")
    plt.ylabel("Mean residual [Wh]")
    plt.title("Mean Residual By Target Bin")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(RESIDUAL_BY_TARGET_BIN_PATH, dpi=200, bbox_inches="tight")
    plt.close()

    ape_by_bin = metric_frame.groupby("target_bin", observed=True)["abs_percentage_error"].mean()
    plt.figure(figsize=(8, 4))
    ape_by_bin.plot(kind="bar")
    plt.xlabel("Actual generation bin [Wh]")
    plt.ylabel("Mean APE [%]")
    plt.title("MAPE By Target Bin")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(APE_BY_TARGET_BIN_PATH, dpi=200, bbox_inches="tight")
    plt.close()

    return {
        "prediction_scatter_tuned_png": str(PREDICTION_SCATTER_PATH),
        "residual_by_month_png": str(RESIDUAL_BY_MONTH_PATH),
        "residual_by_target_bin_png": str(RESIDUAL_BY_TARGET_BIN_PATH),
        "ape_by_target_bin_png": str(APE_BY_TARGET_BIN_PATH),
    }


def run_shap(model, test_frame: pd.DataFrame, libs: dict[str, Any]) -> pd.DataFrame:
    shap = libs["shap"]
    plt = libs["plt"]

    sample = test_frame[PRIMARY_FEATURES].sample(
        n=min(SHAP_SAMPLE_SIZE, len(test_frame)),
        random_state=RANDOM_STATE,
    )
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)
    importance = np.abs(shap_values).mean(axis=0)
    importance_frame = (
        pd.DataFrame({"feature": PRIMARY_FEATURES, "mean_abs_shap": importance})
        .sort_values("mean_abs_shap", ascending=False)
        .reset_index(drop=True)
    )

    shap.summary_plot(shap_values, sample, show=False, max_display=20)
    plt.tight_layout()
    plt.savefig(SHAP_SUMMARY_PATH, dpi=200, bbox_inches="tight")
    plt.close()
    importance_frame.to_csv(SHAP_IMPORTANCE_PATH, index=False)

    return importance_frame


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_pipeline() -> dict[str, Any]:
    libs = load_model_libraries()
    XGBRegressor = libs["XGBRegressor"]
    RESULTS_DIR.mkdir(exist_ok=True)

    frame = load_featured_data()
    observed_capacity_wh = float(frame[TARGET_COLUMN].max())
    split = chronological_split(frame)

    baseline_validation_mape = evaluate_baseline(split.validation)
    default_model = fit_default_model(split, XGBRegressor)
    default_validation_predictions = clip_predictions(default_model.predict(split.validation[PRIMARY_FEATURES]))
    default_validation_mape = mape_on_frame(split.validation, default_validation_predictions)

    tuning_status = "skipped"
    tuning_skip_reason = None
    best_params = None
    best_cv_mape = None
    optuna_trials: list[dict[str, Any]] = []
    tuned_model = None

    if default_validation_mape < baseline_validation_mape:
        if os.environ.get("USE_FIXED_PARAMS") == "1":
            tuning_status = "fixed_params_fast_final"
            best_params = FIXED_TUNED_PARAMS
            best_cv_mape = FIXED_TUNED_CV_MAPE
            optuna_trials = []
        else:
            tuning_status = "completed"
            best_params, best_cv_mape, optuna_trials = tune_model(split, libs)
        tuned_model = make_tuned_model(XGBRegressor, best_params)
        tuned_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])
    else:
        tuning_skip_reason = "Default XGBoost did not beat validation baseline."

    default_final_model = make_default_model(XGBRegressor)
    default_final_model.fit(split.dev[PRIMARY_FEATURES], split.dev[TARGET_COLUMN])

    baseline_test_predictions = split.test[BASELINE_COLUMN].to_numpy()
    default_test_predictions = clip_predictions(default_final_model.predict(split.test[PRIMARY_FEATURES]))
    tuned_test_predictions = (
        clip_predictions(tuned_model.predict(split.test[PRIMARY_FEATURES]))
        if tuned_model is not None
        else np.full(len(split.test), np.nan)
    )

    baseline_test_mape = evaluate_baseline(split.test)
    default_test_mape = mape_on_frame(split.test, default_test_predictions)
    tuned_test_mape = (
        mape_on_frame(split.test, tuned_test_predictions)
        if tuned_model is not None
        else None
    )
    validation_metric_bundle = {
        "baseline": regression_metrics(split.validation, split.validation[BASELINE_COLUMN].to_numpy(), observed_capacity_wh),
        "xgb_default": regression_metrics(split.validation, default_validation_predictions, observed_capacity_wh),
    }
    test_metric_bundle = {
        "baseline": regression_metrics(split.test, baseline_test_predictions, observed_capacity_wh),
        "xgb_default": regression_metrics(split.test, default_test_predictions, observed_capacity_wh),
        "xgb_tuned": regression_metrics(split.test, tuned_test_predictions, observed_capacity_wh)
        if tuned_model is not None
        else None,
    }

    predictions = pd.DataFrame(
        {
            "Time": split.test["Time"],
            "y_true": split.test[TARGET_COLUMN],
            "baseline_pred": baseline_test_predictions,
            "xgb_default_pred": default_test_predictions,
            "xgb_tuned_pred": tuned_test_predictions,
        }
    )
    predictions.to_csv(PREDICTIONS_PATH, index=False)

    shap_importance_top20 = None
    diagnostic_plot_outputs = {}
    if tuned_model is not None:
        diagnostic_plot_outputs = plot_diagnostics(split.test, tuned_test_predictions, libs)
        importance = run_shap(tuned_model, split.test, libs)
        shap_importance_top20 = importance.head(20).to_dict(orient="records")

    metrics = {
        "data_file": str(FEATURED_PATH),
        "target_column": TARGET_COLUMN,
        "baseline_column": BASELINE_COLUMN,
        "random_state": RANDOM_STATE,
        "test_fraction": TEST_FRACTION,
        "validation_fraction_of_dev": VALIDATION_FRACTION_OF_DEV,
        "splits": {
            "train": summarize_split(split.train),
            "validation": summarize_split(split.validation),
            "dev": summarize_split(split.dev),
            "test": summarize_split(split.test),
        },
        "metric": {
            "name": "MAPE",
            "mask": "solar_elevation_deg > 0 and Energy delta[Wh] > 0",
            "denominator_floor_wh": MAPE_FLOOR_WH,
            "known_limitation": "MAPE remains sensitive to low generation dawn/dusk and cloudy-transition periods even with a denominator floor.",
        },
        "capacity_normalization": {
            "observed_capacity_wh": observed_capacity_wh,
            "reported_capacity_wh": REPORTED_CAPACITY_WH,
            "reported_capacity_note": "External/report capacity assumption used only for alternate nRMSE reporting.",
        },
        "feature_policy": {
            "mode": "forecast_strict",
            "primary_features": PRIMARY_FEATURES,
            "forbidden_primary_features": sorted(FORBIDDEN_PRIMARY_FEATURES),
            "notes": [
                "Synchronous measured GHI and clear_sky_index are excluded from the primary model.",
                "Lagged clear_sky_index features are allowed because they only use historical observations.",
            ],
        },
        "validation_metrics": {
            "baseline_mape": baseline_validation_mape,
            "xgb_default_mape": default_validation_mape,
            "default_beats_baseline": bool(default_validation_mape < baseline_validation_mape),
            "robust_metrics": validation_metric_bundle,
        },
        "optuna": {
            "status": tuning_status,
            "skip_reason": tuning_skip_reason,
            "n_trials": OPTUNA_TRIALS if tuning_status == "completed" else 0,
            "cv_splits": OPTUNA_CV_SPLITS,
            "sampler": f"TPESampler(seed={RANDOM_STATE})",
            "best_params": best_params,
            "best_cv_mape": best_cv_mape,
            "trials": optuna_trials,
        },
        "test_metrics": {
            "baseline_mape": baseline_test_mape,
            "xgb_default_mape": default_test_mape,
            "xgb_tuned_mape": tuned_test_mape,
            "robust_metrics": test_metric_bundle,
        },
        "baseline_error_diagnostics": {
            "validation": baseline_error_diagnostics(split.validation),
            "test": baseline_error_diagnostics(split.test),
        },
        "outputs": {
            "metrics_json": str(METRICS_PATH),
            "predictions_test_csv": str(PREDICTIONS_PATH),
            "shap_summary_png": str(SHAP_SUMMARY_PATH) if tuned_model is not None else None,
            "shap_importance_csv": str(SHAP_IMPORTANCE_PATH) if tuned_model is not None else None,
            **diagnostic_plot_outputs,
        },
        "shap": {
            "status": "completed" if tuned_model is not None else "skipped",
            "skip_reason": None if tuned_model is not None else tuning_skip_reason,
            "sample_size": min(SHAP_SAMPLE_SIZE, len(split.test)) if tuned_model is not None else 0,
            "top20": shap_importance_top20,
        },
    }
    save_json(METRICS_PATH, metrics)

    return metrics


def main() -> None:
    metrics = run_pipeline()
    print(json.dumps({
        "validation_metrics": metrics["validation_metrics"],
        "optuna_status": metrics["optuna"]["status"],
        "test_metrics": metrics["test_metrics"],
        "outputs": metrics["outputs"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
