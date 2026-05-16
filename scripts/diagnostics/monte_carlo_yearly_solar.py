"""
Monte Carlo projection for the next year of solar generation.

This is a scenario generator, not a deterministic weather forecast. Future
weather is unknown, so each future day is sampled from historical analogue days
with a similar day-of-year. Historical analogue profiles are first converted
through the existing forecast-strict XGBoost point and q10 models.

Outputs are written to:
  model_results/monte_carlo_year/
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
sys.path.insert(0, str(LOCAL_PACKAGE_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
RESULTS_DIR = PROJECT_DIR / "model_results"
MC_DIR = RESULTS_DIR / "monte_carlo_year"
os.environ.setdefault("MPLCONFIGDIR", str(RESULTS_DIR / "matplotlib_cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from xgboost import XGBRegressor

from train_xgboost_pipeline import (
    FIXED_TUNED_PARAMS,
    PRIMARY_FEATURES,
    RANDOM_STATE,
    TARGET_COLUMN,
    clip_predictions,
    load_featured_data,
    make_tuned_model,
)
from train_quantile_model import QUANTILE_ALPHA, make_quantile_model


FUTURE_START = os.environ.get("MC_FUTURE_START", "2026-05-16")
FUTURE_DAYS = int(os.environ.get("MC_FUTURE_DAYS", "365"))
N_SIMULATIONS = int(os.environ.get("MC_SIMULATIONS", "1000"))
ANALOG_WINDOW_DAYS = int(os.environ.get("MC_ANALOG_WINDOW_DAYS", "21"))


@dataclass(frozen=True)
class HistoricalProfiles:
    daily: pd.DataFrame
    profile_15min: pd.DataFrame


def circular_day_distance(day_a: np.ndarray, day_b: int) -> np.ndarray:
    raw = np.abs(day_a - day_b)
    return np.minimum(raw, 365 - raw)


def train_models(frame: pd.DataFrame) -> tuple[XGBRegressor, XGBRegressor]:
    point_model = make_tuned_model(XGBRegressor, FIXED_TUNED_PARAMS)
    point_model.fit(frame[PRIMARY_FEATURES], frame[TARGET_COLUMN])

    q10_model = make_quantile_model(XGBRegressor)
    q10_model.fit(frame[PRIMARY_FEATURES], frame[TARGET_COLUMN])

    return point_model, q10_model


def build_historical_profiles(frame: pd.DataFrame, point_model: XGBRegressor, q10_model: XGBRegressor) -> HistoricalProfiles:
    scored = frame[["Time", TARGET_COLUMN, "solar_elevation_deg", "month"]].copy()
    scored["point_pred_wh"] = clip_predictions(point_model.predict(frame[PRIMARY_FEATURES]))
    scored["q10_pred_wh"] = np.clip(q10_model.predict(frame[PRIMARY_FEATURES]), 0, None)
    scored["date"] = scored["Time"].dt.floor("D")
    scored["minute_of_day"] = scored["Time"].dt.hour * 60 + scored["Time"].dt.minute
    scored["day_of_year"] = scored["Time"].dt.dayofyear.clip(upper=365)

    counts = scored.groupby("date").size()
    complete_dates = counts[counts == 96].index
    profile = scored[scored["date"].isin(complete_dates)].copy()

    daily = (
        profile.groupby("date")
        .agg(
            day_of_year=("day_of_year", "median"),
            month=("month", "median"),
            actual_wh=(TARGET_COLUMN, "sum"),
            point_wh=("point_pred_wh", "sum"),
            q10_wh=("q10_pred_wh", "sum"),
            daylight_points=("solar_elevation_deg", lambda x: int((x > 0).sum())),
        )
        .reset_index()
    )
    daily["day_of_year"] = daily["day_of_year"].astype(int)
    daily["month"] = daily["month"].astype(int)

    return HistoricalProfiles(daily=daily, profile_15min=profile)


def choose_analog_dates(daily: pd.DataFrame, future_day_of_year: int, rng: np.random.Generator) -> np.ndarray:
    distances = circular_day_distance(daily["day_of_year"].to_numpy(), future_day_of_year)
    candidates = daily.loc[distances <= ANALOG_WINDOW_DAYS, "date"].to_numpy()
    if len(candidates) < 10:
        nearest = np.argsort(distances)[:30]
        candidates = daily.iloc[nearest]["date"].to_numpy()
    return rng.choice(candidates, size=N_SIMULATIONS, replace=True)


def run_monte_carlo(profiles: HistoricalProfiles) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(RANDOM_STATE)
    future_dates = pd.date_range(FUTURE_START, periods=FUTURE_DAYS, freq="D")

    daily_records: list[dict] = []
    annual_point = np.zeros(N_SIMULATIONS)
    annual_q10 = np.zeros(N_SIMULATIONS)
    monthly_point = {(sim, month): 0.0 for sim in range(N_SIMULATIONS) for month in range(1, 13)}
    monthly_q10 = {(sim, month): 0.0 for sim in range(N_SIMULATIONS) for month in range(1, 13)}

    daily_lookup = profiles.daily.set_index("date")

    for future_date in future_dates:
        future_doy = min(int(future_date.dayofyear), 365)
        chosen_dates = choose_analog_dates(profiles.daily, future_doy, rng)
        chosen = daily_lookup.loc[chosen_dates]
        point_values = chosen["point_wh"].to_numpy(dtype=float)
        q10_values = chosen["q10_wh"].to_numpy(dtype=float)

        annual_point += point_values
        annual_q10 += q10_values
        month = int(future_date.month)
        for sim, value in enumerate(point_values):
            monthly_point[(sim, month)] += float(value)
        for sim, value in enumerate(q10_values):
            monthly_q10[(sim, month)] += float(value)

        daily_records.append(
            {
                "date": future_date.date().isoformat(),
                "day_of_year": future_doy,
                "mean_point_wh": float(np.mean(point_values)),
                "p10_point_wh": float(np.quantile(point_values, 0.10)),
                "p50_point_wh": float(np.quantile(point_values, 0.50)),
                "p90_point_wh": float(np.quantile(point_values, 0.90)),
                "mean_q10_wh": float(np.mean(q10_values)),
                "p10_q10_wh": float(np.quantile(q10_values, 0.10)),
                "p50_q10_wh": float(np.quantile(q10_values, 0.50)),
                "p90_q10_wh": float(np.quantile(q10_values, 0.90)),
                "analog_days_used": int(len(np.unique(chosen_dates))),
            }
        )

    annual = pd.DataFrame(
        {
            "simulation": np.arange(N_SIMULATIONS),
            "annual_point_wh": annual_point,
            "annual_q10_wh": annual_q10,
            "annual_point_kwh": annual_point / 1000.0,
            "annual_q10_kwh": annual_q10 / 1000.0,
        }
    )

    monthly_records = []
    for month in range(1, 13):
        point = np.array([monthly_point[(sim, month)] for sim in range(N_SIMULATIONS)])
        q10 = np.array([monthly_q10[(sim, month)] for sim in range(N_SIMULATIONS)])
        monthly_records.append(
            {
                "month": month,
                "mean_point_kwh": float(np.mean(point) / 1000.0),
                "p10_point_kwh": float(np.quantile(point, 0.10) / 1000.0),
                "p50_point_kwh": float(np.quantile(point, 0.50) / 1000.0),
                "p90_point_kwh": float(np.quantile(point, 0.90) / 1000.0),
                "mean_q10_kwh": float(np.mean(q10) / 1000.0),
                "p10_q10_kwh": float(np.quantile(q10, 0.10) / 1000.0),
                "p50_q10_kwh": float(np.quantile(q10, 0.50) / 1000.0),
                "p90_q10_kwh": float(np.quantile(q10, 0.90) / 1000.0),
            }
        )

    return pd.DataFrame(daily_records), pd.DataFrame(monthly_records), annual


def write_summary(daily: pd.DataFrame, monthly: pd.DataFrame, annual: pd.DataFrame, historical: HistoricalProfiles) -> dict:
    point = annual["annual_point_kwh"].to_numpy()
    q10 = annual["annual_q10_kwh"].to_numpy()
    summary = {
        "method": "Historical analogue Monte Carlo using forecast-strict XGBoost point and q10 models.",
        "future_start": FUTURE_START,
        "future_days": FUTURE_DAYS,
        "simulations": N_SIMULATIONS,
        "analog_window_days": ANALOG_WINDOW_DAYS,
        "historical_complete_days": int(len(historical.daily)),
        "assumptions": [
            "Future weather is unknown; each future day samples historical analogue days with similar day-of-year.",
            "Daily 15-min shape and weather persistence are inherited from sampled historical analogue days.",
            "This is a probabilistic planning scenario, not a deterministic meteorological forecast.",
        ],
        "annual_point_kwh": {
            "mean": float(np.mean(point)),
            "p05": float(np.quantile(point, 0.05)),
            "p10": float(np.quantile(point, 0.10)),
            "p50": float(np.quantile(point, 0.50)),
            "p90": float(np.quantile(point, 0.90)),
            "p95": float(np.quantile(point, 0.95)),
        },
        "annual_q10_kwh": {
            "mean": float(np.mean(q10)),
            "p05": float(np.quantile(q10, 0.05)),
            "p10": float(np.quantile(q10, 0.10)),
            "p50": float(np.quantile(q10, 0.50)),
            "p90": float(np.quantile(q10, 0.90)),
            "p95": float(np.quantile(q10, 0.95)),
        },
        "outputs": {
            "daily_summary_csv": str(MC_DIR / "monte_carlo_daily_summary.csv"),
            "monthly_summary_csv": str(MC_DIR / "monte_carlo_monthly_summary.csv"),
            "annual_scenarios_csv": str(MC_DIR / "monte_carlo_annual_scenarios.csv"),
            "annual_histogram_png": str(MC_DIR / "annual_total_distribution.png"),
            "monthly_fan_png": str(MC_DIR / "monthly_energy_fan.png"),
            "daily_fan_png": str(MC_DIR / "daily_energy_fan.png"),
            "expected_monthly_bar_png": str(MC_DIR / "expected_monthly_energy.png"),
        },
    }
    (MC_DIR / "monte_carlo_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def make_plots(daily: pd.DataFrame, monthly: pd.DataFrame, annual: pd.DataFrame) -> None:
    MC_DIR.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(8, 5))
    plt.hist(annual["annual_point_kwh"], bins=30, alpha=0.7, label="Point forecast")
    plt.hist(annual["annual_q10_kwh"], bins=30, alpha=0.6, label="Q10 conservative")
    plt.xlabel("Annual solar generation [kWh]")
    plt.ylabel("Simulation count")
    plt.title("Monte Carlo Annual Solar Generation Distribution")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MC_DIR / "annual_total_distribution.png", dpi=200, bbox_inches="tight")
    plt.close()

    x = monthly["month"].to_numpy()
    plt.figure(figsize=(9, 5))
    plt.fill_between(x, monthly["p10_point_kwh"], monthly["p90_point_kwh"], alpha=0.25, label="Point p10-p90")
    plt.plot(x, monthly["p50_point_kwh"], marker="o", label="Point p50")
    plt.plot(x, monthly["p50_q10_kwh"], marker="o", label="Q10 p50")
    plt.xlabel("Month")
    plt.ylabel("Monthly solar generation [kWh]")
    plt.title("Monthly Monte Carlo Forecast Fan")
    plt.xticks(range(1, 13))
    plt.legend()
    plt.tight_layout()
    plt.savefig(MC_DIR / "monthly_energy_fan.png", dpi=200, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(9, 5))
    plt.bar(x - 0.18, monthly["mean_point_kwh"], width=0.36, label="Point mean")
    plt.bar(x + 0.18, monthly["mean_q10_kwh"], width=0.36, label="Q10 mean")
    plt.xlabel("Month")
    plt.ylabel("Expected monthly solar generation [kWh]")
    plt.title("Expected Monthly Solar Generation")
    plt.xticks(range(1, 13))
    plt.legend()
    plt.tight_layout()
    plt.savefig(MC_DIR / "expected_monthly_energy.png", dpi=200, bbox_inches="tight")
    plt.close()

    plot_daily = daily.copy()
    plot_daily["date"] = pd.to_datetime(plot_daily["date"])
    plt.figure(figsize=(12, 5))
    plt.fill_between(plot_daily["date"], plot_daily["p10_point_wh"] / 1000.0, plot_daily["p90_point_wh"] / 1000.0, alpha=0.25, label="Point p10-p90")
    plt.plot(plot_daily["date"], plot_daily["p50_point_wh"] / 1000.0, linewidth=1.2, label="Point p50")
    plt.plot(plot_daily["date"], plot_daily["p50_q10_wh"] / 1000.0, linewidth=1.2, label="Q10 p50")
    plt.xlabel("Date")
    plt.ylabel("Daily solar generation [kWh]")
    plt.title("Daily Monte Carlo Forecast Fan")
    plt.legend()
    plt.tight_layout()
    plt.savefig(MC_DIR / "daily_energy_fan.png", dpi=200, bbox_inches="tight")
    plt.close()


def main() -> None:
    MC_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading featured data...")
    frame = load_featured_data()

    print(f"Training point and q10 models on all available featured data ({len(frame):,} rows)...")
    point_model, q10_model = train_models(frame)

    print("Scoring historical analogue profiles...")
    historical = build_historical_profiles(frame, point_model, q10_model)
    print(f"Complete historical analogue days: {len(historical.daily):,}")

    print(
        f"Running Monte Carlo: start={FUTURE_START}, days={FUTURE_DAYS}, "
        f"simulations={N_SIMULATIONS}, analogue window=±{ANALOG_WINDOW_DAYS} days..."
    )
    daily, monthly, annual = run_monte_carlo(historical)

    daily.to_csv(MC_DIR / "monte_carlo_daily_summary.csv", index=False)
    monthly.to_csv(MC_DIR / "monte_carlo_monthly_summary.csv", index=False)
    annual.to_csv(MC_DIR / "monte_carlo_annual_scenarios.csv", index=False)

    print("Creating plots...")
    make_plots(daily, monthly, annual)
    summary = write_summary(daily, monthly, annual, historical)

    print("\n--- Monte Carlo Yearly Solar Summary ---")
    print(f"Future period       : {FUTURE_START} + {FUTURE_DAYS} days")
    print(f"Simulations         : {N_SIMULATIONS:,}")
    print(f"Point annual mean   : {summary['annual_point_kwh']['mean']:.1f} kWh")
    print(f"Point annual p10/p50/p90: "
          f"{summary['annual_point_kwh']['p10']:.1f} / "
          f"{summary['annual_point_kwh']['p50']:.1f} / "
          f"{summary['annual_point_kwh']['p90']:.1f} kWh")
    print(f"Q10 annual mean     : {summary['annual_q10_kwh']['mean']:.1f} kWh")
    print(f"Q10 annual p10/p50/p90: "
          f"{summary['annual_q10_kwh']['p10']:.1f} / "
          f"{summary['annual_q10_kwh']['p50']:.1f} / "
          f"{summary['annual_q10_kwh']['p90']:.1f} kWh")
    print(f"Outputs written to  : {MC_DIR}")


if __name__ == "__main__":
    main()
