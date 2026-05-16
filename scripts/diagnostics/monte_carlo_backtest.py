"""
Monte Carlo backtest for solar forecast accuracy.

This script is different from monte_carlo_yearly_solar.py:
  - yearly projection asks "what could next year look like?"
  - this backtest asks "would the Monte Carlo method have been accurate on
    held-out historical test days?"

The analogue pool is restricted to the development period. Test days are never
used to choose analogue days or train models.

Outputs are written to:
  model_results/monte_carlo/backtest/
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
sys.path.insert(0, str(LOCAL_PACKAGE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

RESULTS_DIR = PROJECT_DIR / "model_results"
BACKTEST_DIR = RESULTS_DIR / "monte_carlo" / "backtest"
PLOTS_DIR = RESULTS_DIR / "plots" / "monte_carlo" / "backtest"
os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / "matplotlib_cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBRegressor

from train_quantile_model import QUANTILE_ALPHA, make_quantile_model
from train_xgboost_pipeline import (
    FIXED_TUNED_PARAMS,
    MAPE_FLOOR_WH,
    PRIMARY_FEATURES,
    RANDOM_STATE,
    TARGET_COLUMN,
    chronological_split,
    clip_predictions,
    load_featured_data,
    make_tuned_model,
)


N_SIMULATIONS = int(os.environ.get("MC_BACKTEST_SIMULATIONS", "1000"))
ANALOG_WINDOW_DAYS = int(os.environ.get("MC_ANALOG_WINDOW_DAYS", "21"))
DAILY_MAPE_FLOOR_WH = float(os.environ.get("MC_DAILY_MAPE_FLOOR_WH", "1000"))
ROWS_PER_COMPLETE_DAY = 96


def circular_day_distance(day_a: np.ndarray, day_b: int) -> np.ndarray:
    raw = np.abs(day_a - day_b)
    return np.minimum(raw, 365 - raw)


def train_models(frame: pd.DataFrame) -> tuple[XGBRegressor, XGBRegressor]:
    point_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
    point_model.fit(frame[PRIMARY_FEATURES], frame[TARGET_COLUMN])

    q10_model = make_quantile_model(XGBRegressor)
    q10_model.fit(frame[PRIMARY_FEATURES], frame[TARGET_COLUMN])

    return point_model, q10_model


def score_frame(frame: pd.DataFrame, point_model: XGBRegressor, q10_model: XGBRegressor) -> pd.DataFrame:
    scored = frame[["Time", TARGET_COLUMN, "solar_elevation_deg"]].copy()
    scored["point_pred_wh"] = clip_predictions(point_model.predict(frame[PRIMARY_FEATURES]))
    scored["q10_pred_wh"] = np.clip(q10_model.predict(frame[PRIMARY_FEATURES]), 0, None)
    scored["date"] = scored["Time"].dt.floor("D")
    scored["day_of_year"] = scored["Time"].dt.dayofyear.clip(upper=365)
    scored["month"] = scored["Time"].dt.month
    return scored


def daily_complete(scored: pd.DataFrame) -> pd.DataFrame:
    counts = scored.groupby("date").size()
    complete_dates = counts[counts == ROWS_PER_COMPLETE_DAY].index
    complete = scored[scored["date"].isin(complete_dates)].copy()
    daily = (
        complete.groupby("date")
        .agg(
            day_of_year=("day_of_year", "median"),
            month=("month", "median"),
            actual_wh=(TARGET_COLUMN, "sum"),
            direct_point_wh=("point_pred_wh", "sum"),
            direct_q10_wh=("q10_pred_wh", "sum"),
            daylight_points=("solar_elevation_deg", lambda values: int((values > 0).sum())),
        )
        .reset_index()
    )
    daily["day_of_year"] = daily["day_of_year"].astype(int)
    daily["month"] = daily["month"].astype(int)
    return daily


def choose_analog_rows(dev_daily: pd.DataFrame, test_day_of_year: int, rng: np.random.Generator) -> pd.DataFrame:
    distances = circular_day_distance(dev_daily["day_of_year"].to_numpy(), test_day_of_year)
    candidates = dev_daily.loc[distances <= ANALOG_WINDOW_DAYS]
    if len(candidates) < 20:
        nearest = np.argsort(distances)[:60]
        candidates = dev_daily.iloc[nearest]
    sampled_index = rng.choice(candidates.index.to_numpy(), size=N_SIMULATIONS, replace=True)
    return dev_daily.loc[sampled_index]


def run_monte_carlo_backtest(dev_daily: pd.DataFrame, test_daily: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_STATE)
    records: list[dict] = []

    for row in test_daily.itertuples(index=False):
        analogs = choose_analog_rows(dev_daily, int(row.day_of_year), rng)
        point_values = analogs["direct_point_wh"].to_numpy(dtype=float)
        q10_values = analogs["direct_q10_wh"].to_numpy(dtype=float)

        records.append(
            {
                "date": row.date,
                "day_of_year": int(row.day_of_year),
                "month": int(row.month),
                "actual_wh": float(row.actual_wh),
                "direct_point_wh": float(row.direct_point_wh),
                "direct_q10_wh": float(row.direct_q10_wh),
                "mc_mean_point_wh": float(np.mean(point_values)),
                "mc_p10_point_wh": float(np.quantile(point_values, 0.10)),
                "mc_p50_point_wh": float(np.quantile(point_values, 0.50)),
                "mc_p90_point_wh": float(np.quantile(point_values, 0.90)),
                "mc_mean_q10_wh": float(np.mean(q10_values)),
                "mc_p50_q10_wh": float(np.quantile(q10_values, 0.50)),
                "analog_unique_days": int(analogs["date"].nunique()),
            }
        )

    return pd.DataFrame(records)


def regression_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float | int]:
    actual = y_true.to_numpy(dtype=float)
    pred = y_pred.to_numpy(dtype=float)
    residual = pred - actual
    ss_res = float(np.sum((actual - pred) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    corr = float(np.corrcoef(actual, pred)[0, 1]) if len(actual) > 1 else float("nan")
    mape = float(np.mean(np.abs(actual - pred) / np.maximum(actual, DAILY_MAPE_FLOOR_WH)) * 100.0)
    return {
        "rows": int(len(actual)),
        "mape_pct": mape,
        "r2": 1.0 - ss_res / ss_tot if ss_tot else float("nan"),
        "rmse_wh": rmse,
        "mae_wh": mae,
        "bias_wh": float(np.mean(residual)),
        "corr": corr,
    }


def summarize(backtest: pd.DataFrame, split_info: dict) -> dict:
    actual = backtest["actual_wh"]
    point = backtest["direct_point_wh"]
    mc_mean = backtest["mc_mean_point_wh"]
    mc_p50 = backtest["mc_p50_point_wh"]
    q10 = backtest["direct_q10_wh"]

    interval_hit = (
        (backtest["actual_wh"] >= backtest["mc_p10_point_wh"])
        & (backtest["actual_wh"] <= backtest["mc_p90_point_wh"])
    )
    summary = {
        "method": "Held-out daily Monte Carlo backtest. Analogue pool is development data only.",
        "simulations": N_SIMULATIONS,
        "analog_window_days": ANALOG_WINDOW_DAYS,
        "daily_mape_floor_wh": DAILY_MAPE_FLOOR_WH,
        "fifteen_min_mape_floor_wh_from_pipeline": MAPE_FLOOR_WH,
        "quantile_alpha": QUANTILE_ALPHA,
        "split": split_info,
        "complete_test_days": int(len(backtest)),
        "direct_model_daily_metrics": regression_metrics(actual, point),
        "direct_q10_daily_coverage": {
            "target_coverage": float(1.0 - QUANTILE_ALPHA),
            "actual_coverage": float(np.mean(q10 <= actual)),
            "overshoot_rate_pct": float(np.mean(q10 > actual) * 100.0),
            "mean_gap_wh": float(np.mean(q10 - actual)),
        },
        "monte_carlo_mean_daily_metrics": regression_metrics(actual, mc_mean),
        "monte_carlo_p50_daily_metrics": regression_metrics(actual, mc_p50),
        "monte_carlo_interval": {
            "nominal_coverage": 0.80,
            "actual_coverage": float(np.mean(interval_hit)),
            "actual_coverage_pct": float(np.mean(interval_hit) * 100.0),
            "mean_interval_width_wh": float(np.mean(backtest["mc_p90_point_wh"] - backtest["mc_p10_point_wh"])),
        },
        "outputs": {
            "daily_csv": str(BACKTEST_DIR / "monte_carlo_backtest_daily.csv"),
            "summary_json": str(BACKTEST_DIR / "monte_carlo_backtest_summary.json"),
            "timeseries_png": str(PLOTS_DIR / "backtest_daily_timeseries.png"),
            "scatter_png": str(PLOTS_DIR / "backtest_actual_vs_prediction.png"),
            "residual_by_month_png": str(PLOTS_DIR / "backtest_residual_by_month.png"),
            "interval_coverage_png": str(PLOTS_DIR / "backtest_interval_coverage.png"),
        },
    }
    return summary


def make_plots(backtest: pd.DataFrame) -> None:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(backtest["date"])

    plt.figure(figsize=(12, 5))
    plt.fill_between(
        dates,
        backtest["mc_p10_point_wh"],
        backtest["mc_p90_point_wh"],
        alpha=0.22,
        label="Monte Carlo p10-p90",
    )
    plt.plot(dates, backtest["actual_wh"], linewidth=1.2, label="Actual daily solar")
    plt.plot(dates, backtest["direct_point_wh"], linewidth=1.0, label="Direct model prediction")
    plt.plot(dates, backtest["mc_mean_point_wh"], linewidth=1.0, label="MC mean")
    plt.xlabel("Date")
    plt.ylabel("Daily solar generation [Wh]")
    plt.title("Monte Carlo Backtest: Daily Actual vs Forecast")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "backtest_daily_timeseries.png", dpi=200, bbox_inches="tight")
    plt.close()

    limit = float(max(backtest["actual_wh"].max(), backtest["direct_point_wh"].max(), backtest["mc_mean_point_wh"].max()))
    plt.figure(figsize=(6, 6))
    plt.scatter(backtest["actual_wh"], backtest["direct_point_wh"], s=14, alpha=0.55, label="Direct model")
    plt.scatter(backtest["actual_wh"], backtest["mc_mean_point_wh"], s=14, alpha=0.45, label="MC mean")
    plt.plot([0, limit], [0, limit], color="black", linewidth=1, label="45-degree line")
    plt.xlabel("Actual daily solar [Wh]")
    plt.ylabel("Predicted daily solar [Wh]")
    plt.title("Backtest Actual vs Prediction")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "backtest_actual_vs_prediction.png", dpi=200, bbox_inches="tight")
    plt.close()

    residuals = backtest.copy()
    residuals["direct_residual_wh"] = residuals["direct_point_wh"] - residuals["actual_wh"]
    residuals["mc_mean_residual_wh"] = residuals["mc_mean_point_wh"] - residuals["actual_wh"]
    monthly = (
        residuals.groupby("month")[["direct_residual_wh", "mc_mean_residual_wh"]]
        .mean()
        .reset_index()
    )
    x = np.arange(len(monthly))
    width = 0.38
    plt.figure(figsize=(9, 5))
    plt.bar(x - width / 2, monthly["direct_residual_wh"], width=width, label="Direct model")
    plt.bar(x + width / 2, monthly["mc_mean_residual_wh"], width=width, label="MC mean")
    plt.axhline(0, color="black", linewidth=1)
    plt.xticks(x, monthly["month"])
    plt.xlabel("Month")
    plt.ylabel("Mean residual [Wh], prediction - actual")
    plt.title("Backtest Residual by Month")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "backtest_residual_by_month.png", dpi=200, bbox_inches="tight")
    plt.close()

    covered = (
        (backtest["actual_wh"] >= backtest["mc_p10_point_wh"])
        & (backtest["actual_wh"] <= backtest["mc_p90_point_wh"])
    )
    coverage_by_month = backtest.assign(covered=covered).groupby("month")["covered"].mean().reset_index()
    plt.figure(figsize=(9, 5))
    plt.bar(coverage_by_month["month"], coverage_by_month["covered"] * 100.0)
    plt.axhline(80, color="black", linewidth=1, linestyle="--", label="Nominal 80% interval")
    plt.xticks(range(1, 13))
    plt.ylim(0, 100)
    plt.xlabel("Month")
    plt.ylabel("Coverage [%]")
    plt.title("Monte Carlo p10-p90 Interval Coverage by Month")
    plt.legend()
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "backtest_interval_coverage.png", dpi=200, bbox_inches="tight")
    plt.close()


def main() -> None:
    for directory in [BACKTEST_DIR, PLOTS_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

    print("Loading featured data...")
    frame = load_featured_data()
    split = chronological_split(frame)
    split_info = {
        "dev_rows": int(len(split.dev)),
        "test_rows": int(len(split.test)),
        "dev_start": split.dev["Time"].min().isoformat(),
        "dev_end": split.dev["Time"].max().isoformat(),
        "test_start": split.test["Time"].min().isoformat(),
        "test_end": split.test["Time"].max().isoformat(),
        "test_after_dev": bool(split.test["Time"].min() > split.dev["Time"].max()),
    }
    if not split_info["test_after_dev"]:
        raise ValueError("Test set is not strictly later than dev set.")

    print(f"Training point and q10 models on dev set ({len(split.dev):,} rows)...")
    point_model, q10_model = train_models(split.dev)

    print("Scoring dev and held-out test rows...")
    dev_scored = score_frame(split.dev, point_model, q10_model)
    test_scored = score_frame(split.test, point_model, q10_model)
    dev_daily = daily_complete(dev_scored)
    test_daily = daily_complete(test_scored)

    print(
        f"Running Monte Carlo backtest with {N_SIMULATIONS:,} simulations per test day "
        f"and ±{ANALOG_WINDOW_DAYS} day analogue window..."
    )
    backtest = run_monte_carlo_backtest(dev_daily, test_daily)
    backtest.to_csv(BACKTEST_DIR / "monte_carlo_backtest_daily.csv", index=False)

    summary = summarize(
        backtest,
        {
            **split_info,
            "complete_dev_days": int(len(dev_daily)),
            "complete_test_days": int(len(test_daily)),
        },
    )
    (BACKTEST_DIR / "monte_carlo_backtest_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    make_plots(backtest)

    direct = summary["direct_model_daily_metrics"]
    mc_mean = summary["monte_carlo_mean_daily_metrics"]
    interval = summary["monte_carlo_interval"]
    q10 = summary["direct_q10_daily_coverage"]

    print("\n--- Monte Carlo Backtest Report ---")
    print(f"Complete test days          : {summary['complete_test_days']:,}")
    print(f"Direct model daily MAPE     : {direct['mape_pct']:.2f}%")
    print(f"Direct model daily R2       : {direct['r2']:.4f}")
    print(f"Direct model daily RMSE     : {direct['rmse_wh']:.1f} Wh")
    print(f"Direct q10 coverage         : {q10['actual_coverage']:.2%}")
    print(f"MC mean daily MAPE          : {mc_mean['mape_pct']:.2f}%")
    print(f"MC mean daily R2            : {mc_mean['r2']:.4f}")
    print(f"MC p10-p90 actual coverage  : {interval['actual_coverage']:.2%}")
    print(f"Summary saved -> {BACKTEST_DIR / 'monte_carlo_backtest_summary.json'}")


if __name__ == "__main__":
    main()
