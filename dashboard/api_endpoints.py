"""
FastAPI endpoints for Monte Carlo forecast uncertainty bands.

GET /api/forecast/generation?days=7   → P10/P50/P90 solar generation (Wh)
GET /api/forecast/load?days=7         → P10/P50/P90 factory load (kWh)
GET /api/forecast/annual              → annual planning scenarios (kWh totals)

Run with:
    uvicorn api_endpoints:app --host 0.0.0.0 --port 8000

Models are loaded once at startup; subsequent requests hit the cache.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# ── Ensure EMS root is on path (mirrors monte_carlo_forecast.py) ──────────────
_DASHBOARD = Path(__file__).resolve().parent
_EMS_ROOT  = _DASHBOARD.parent.parent / "mds-final"
if not _EMS_ROOT.is_dir():
    _EMS_ROOT = _DASHBOARD.parent / "mds-final"
if str(_EMS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EMS_ROOT))

from monte_carlo_forecast import (  # noqa: E402
    MCModels,
    mc_generation_forecast,
    mc_load_forecast,
    generate_annual_scenarios,
    STEPS_PER_DAY,
)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="EMS Monte Carlo Forecast API",
    description=(
        "Uncertainty bands (P10/P50/P90) for solar generation and factory load. "
        "For dashboard visualisation only – not for MILP scheduling input."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Global model container (populated at startup) ─────────────────────────────
_models: MCModels | None = None

# Default "current date" for backtesting: start of predict period
_DEFAULT_FORECAST_START = pd.Timestamp("2018-06-29")


@app.on_event("startup")
async def _load_models() -> None:
    global _models
    _models = MCModels.load()


def _require_models() -> MCModels:
    if _models is None:
        raise HTTPException(status_code=503, detail="Models not yet loaded.")
    return _models


def _series_to_list(s: pd.Series) -> list[float]:
    return [round(float(v), 4) for v in s.values]


def _timestamps_to_iso(s: pd.Series) -> list[str]:
    return [ts.isoformat() for ts in s.index]


# ── Endpoint helpers ──────────────────────────────────────────────────────────

def _target_dates(days: int, start: pd.Timestamp = _DEFAULT_FORECAST_START) -> list[pd.Timestamp]:
    """Return list of ``days`` consecutive dates starting from ``start``."""
    return [start + timedelta(days=k) for k in range(days)]


# ── GET /api/forecast/generation ─────────────────────────────────────────────

@app.get("/api/forecast/generation")
async def forecast_generation(
    days: int = Query(default=7, ge=1, le=30, description="Forecast horizon in days"),
    n_simulations: int = Query(default=500, ge=50, le=2000,
                               description="Monte Carlo sample size"),
) -> dict[str, Any]:
    """
    P10/P50/P90 solar generation forecast at 15-min resolution.

    Returns timestamps, p10, p50, p90 arrays of length (days × 96).
    All values in Wh.
    """
    m = _require_models()
    target_dates = _target_dates(days)

    result = mc_generation_forecast(
        target_dates=target_dates,
        solar_model=m.solar_model,
        weather_features_df=m.solar_prepared_train,
        historical_actual_df=m.solar_prepared_train,
        n_simulations=n_simulations,
        _test_dates=m.test_dates,
    )

    p50 = result["p50"]
    return {
        "timestamps":    _timestamps_to_iso(p50),
        "p10":           _series_to_list(result["p10"]),
        "p50":           _series_to_list(p50),
        "p90":           _series_to_list(result["p90"]),
        "unit":          result["unit"],
        "generated_at":  result["generated_at"].isoformat(),
        "forecast_days": days,
        "n_simulations": n_simulations,
    }


# ── GET /api/forecast/load ────────────────────────────────────────────────────

@app.get("/api/forecast/load")
async def forecast_load(
    days: int = Query(default=7, ge=1, le=30, description="Forecast horizon in days"),
    n_simulations: int = Query(default=500, ge=50, le=2000,
                               description="Monte Carlo sample size"),
) -> dict[str, Any]:
    """
    P10/P50/P90 factory load forecast at 15-min resolution.

    Returns timestamps, p10, p50, p90 arrays of length (days × 96).
    All values in kWh/15 min.
    """
    m = _require_models()
    target_dates = _target_dates(days)

    result = mc_load_forecast(
        target_dates=target_dates,
        load_model=m.load_bundle,
        historical_load_df=m.load_prepared_train,
        n_simulations=n_simulations,
        _test_dates=m.test_dates,
    )

    p50 = result["p50"]
    return {
        "timestamps":    _timestamps_to_iso(p50),
        "p10":           _series_to_list(result["p10"]),
        "p50":           _series_to_list(p50),
        "p90":           _series_to_list(result["p90"]),
        "unit":          result["unit"],
        "generated_at":  result["generated_at"].isoformat(),
        "forecast_days": days,
        "n_simulations": n_simulations,
    }


# ── GET /api/forecast/annual ──────────────────────────────────────────────────

@app.get("/api/forecast/annual")
async def forecast_annual(
    n_simulations: int = Query(default=200, ge=50, le=1000,
                               description="Monte Carlo sample size"),
    start_year: int = Query(default=2018, ge=2015, le=2030,
                            description="First year of 365-day projection"),
) -> dict[str, Any]:
    """
    Annual generation and load planning scenarios.

    Returns P10/P50/P90/mean annual totals in kWh.
    Includes disclaimer that this is a planning tool, not a deployment forecast.
    """
    m = _require_models()
    start_date = pd.Timestamp(f"{start_year}-01-01")

    result = generate_annual_scenarios(
        solar_model=m.solar_model,
        load_model=m.load_bundle,
        historical_df={
            "solar": m.solar_prepared_train,
            "load":  m.load_prepared_train,
        },
        start_date=start_date,
        n_simulations=n_simulations,
        _test_dates=m.test_dates,
    )

    gen  = result["annual_generation"]
    load = result["annual_load"]

    return {
        "generation": {
            "p10":  round(gen["p10"],  1),
            "p50":  round(gen["p50"],  1),
            "p90":  round(gen["p90"],  1),
            "mean": round(gen["mean"], 1),
        },
        "load": {
            "p10":  round(load["p10"],  1),
            "p50":  round(load["p50"],  1),
            "p90":  round(load["p90"],  1),
            "mean": round(load["mean"], 1),
        },
        "unit":          result["unit"],
        "n_simulations": result["n_simulations"],
        "start_date":    start_date.date().isoformat(),
        "generated_at":  result["generated_at"].isoformat(),
        "disclaimer":    result["disclaimer"],
    }


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    status = "ready" if _models is not None else "loading"
    return {"status": status}
