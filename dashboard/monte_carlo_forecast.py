"""
Monte Carlo uncertainty bands for EMS dashboard.

Generates P10/P50/P90 bands for:
  - 7-day ahead solar generation (15-min resolution, Wh)
  - 7-day ahead factory load  (15-min resolution, kWh)
  - Annual generation/load planning scenarios (kWh totals)

Approach: analogue-day resampling.  For each future target date we find
historical days with similar seasonal position (and optionally similar
cloud cover / weekday status) from the DEVELOPMENT PERIOD ONLY, sample
them with replacement, run the trained XGBoost models on those historical
feature rows, and aggregate P10/P50/P90 across simulations.

Important constraints
---------------------
* Analogue pool is strictly limited to development period (before test
  set cutoff).  Test set dates are auto-detected from the predict CSVs.
* Same-timestamp measured GHI / clear_sky_index are NOT used as features
  for the target date – we use the analogue day's own historical feature
  rows (lags are from that day's past, not from the target date).
* This module is for UNCERTAINTY VISUALISATION only.  The MILP scheduler
  uses point forecasts and quantile models directly.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── EMS engine path ──────────────────────────────────────────────────────────
_DASHBOARD = Path(__file__).resolve().parent
_EMS_ROOT  = _DASHBOARD.parent.parent / "mds-final"
if not _EMS_ROOT.is_dir():               # fallback for alternative layouts
    _EMS_ROOT = _DASHBOARD.parent / "mds-final"
if str(_EMS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EMS_ROOT))

import mds_solar                                          # noqa: E402
import xgboost as xgb                                    # noqa: E402
from sklearn.preprocessing import StandardScaler         # noqa: E402
from ems_config import (                                  # noqa: E402
    CFG,
    RENEWABLE_TRAIN_CSV,
    RENEWABLE_PREDICT_CSV,
    STEEL_TRAIN_CSV,
    STEEL_PREDICT_CSV,
)
from ems_forecast_load import (                           # noqa: E402
    _get_prepared_steel,
    fit_pload_model_once,
    get_pload_bundle,
)

# ── Module-level constants ────────────────────────────────────────────────────
SEED          = 42
STEPS_PER_DAY = 96                      # 15-min intervals per day
DT_HOURS      = 0.25                    # hours per 15-min interval
_INTERVAL     = timedelta(minutes=15)
_MIN_POOL     = 5                       # minimum pool size before fallback

# Cloud cover categories: 0 = low (0-33 %), 1 = medium (34-66 %), 2 = high (67-100 %)
_CC_THRESHOLDS = (34.0, 67.0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cloud_cat(clouds_pct: float) -> int:
    if clouds_pct < _CC_THRESHOLDS[0]:
        return 0
    if clouds_pct < _CC_THRESHOLDS[1]:
        return 1
    return 2


def _detect_test_dates(
    solar_predict_csv: Path | str = RENEWABLE_PREDICT_CSV,
    load_predict_csv:  Path | str = STEEL_PREDICT_CSV,
) -> frozenset[pd.Timestamp]:
    """Return frozenset of calendar DATEs appearing in either predict CSV."""
    dates: set[pd.Timestamp] = set()
    p = Path(solar_predict_csv)
    if p.is_file():
        df = pd.read_csv(p, usecols=["Time"], parse_dates=["Time"])
        dates.update(df["Time"].dt.normalize().unique())
    p = Path(load_predict_csv)
    if p.is_file():
        df = pd.read_csv(p, usecols=["date"])
        df["date"] = pd.to_datetime(df["date"], format="%d/%m/%Y %H:%M")
        dates.update(df["date"].dt.normalize().unique())
    return frozenset(pd.Timestamp(d) for d in dates)


def _build_solar_dev_pool(
    prepared_train: pd.DataFrame,
    test_dates: frozenset[pd.Timestamp],
) -> pd.DataFrame:
    """
    Daily summary for analogue matching (solar).

    Columns: mean_clouds (float), cloud_category (int 0/1/2), is_weekend (int 0/1)
    Index  : day-normalised Timestamps (development period only)
    """
    daily = (
        prepared_train
        .groupby(prepared_train.index.normalize())
        .agg(mean_clouds=("clouds_all", "mean"))
    )
    daily.index.name = "date"
    daily["cloud_category"] = daily["mean_clouds"].apply(_cloud_cat).astype(int)
    daily["is_weekend"] = pd.DatetimeIndex(daily.index).weekday.isin([5, 6]).astype(int)
    return daily[~daily.index.isin(test_dates)]


def _build_load_dev_pool(
    prepared_train: pd.DataFrame,
    test_dates: frozenset[pd.Timestamp],
) -> pd.DataFrame:
    """
    Daily summary for analogue matching (load).

    Columns: mean_usage_kwh (float), is_weekend (int 0/1)
    Index  : day-normalised Timestamps (development period only)
    """
    daily = (
        prepared_train
        .groupby(prepared_train.index.normalize())
        .agg(mean_usage_kwh=("Usage_kWh", "mean"))
    )
    daily.index.name = "date"
    daily["is_weekend"] = pd.DatetimeIndex(daily.index).weekday.isin([5, 6]).astype(int)
    return daily[~daily.index.isin(test_dates)]


# ── Component 1: Analogue Day Sampler ─────────────────────────────────────────

def sample_analogue_days(
    target_date:          pd.Timestamp,
    historical_df:        pd.DataFrame,
    n_simulations:        int = 500,
    window_days:          int = 21,
    *,
    target_cloud_category: int | None = None,
    is_weekend:            int | None = None,
    rng:                   np.random.Generator | None = None,
) -> list[pd.Timestamp]:
    """
    Sample ``n_simulations`` analogue days from ``historical_df`` for ``target_date``.

    ``historical_df`` must already be restricted to the development period by the
    caller (i.e. test set dates excluded).  Index is DatetimeIndex of dates.
    Optional matching columns: ``cloud_category`` (int 0/1/2), ``is_weekend`` (int 0/1).

    Matching criteria
    -----------------
    1. Day-of-year distance ≤ ``window_days``  (circular, handles Dec/Jan wrap)
    2. |cloud_category − target_cloud_category| ≤ 1   (if both supplied)
    3. is_weekend == target is_weekend               (if supplied)

    Falls back to month-only, then to full pool if constraints leave < _MIN_POOL dates.
    Returns list of ``n_simulations`` day-normalised Timestamps (sampled with replacement).
    """
    if rng is None:
        rng = np.random.default_rng(SEED)

    target_date = pd.Timestamp(target_date).normalize()
    idx         = pd.DatetimeIndex(historical_df.index)

    doy        = idx.day_of_year
    target_doy = target_date.day_of_year
    raw_diff   = np.abs(doy - target_doy)
    doy_diff   = np.minimum(raw_diff, 365 - raw_diff)

    mask = doy_diff <= window_days
    # Exclude the exact target date (safe-guard for annual scenarios)
    mask &= (idx != target_date)

    if target_cloud_category is not None and "cloud_category" in historical_df.columns:
        mask &= np.abs(historical_df["cloud_category"].to_numpy() - target_cloud_category) <= 1

    if is_weekend is not None and "is_weekend" in historical_df.columns:
        mask &= historical_df["is_weekend"].to_numpy() == is_weekend

    pool = historical_df.index[mask]

    if len(pool) < _MIN_POOL:
        # Fallback 1: same month, no cloud/weekend constraint
        month_mask = (idx.month == target_date.month) & (idx != target_date)
        pool = historical_df.index[month_mask]

    if len(pool) < _MIN_POOL:
        # Fallback 2: entire dev pool
        pool = historical_df.index[idx != target_date]

    if len(pool) == 0:
        raise ValueError(
            f"Empty analogue pool for target_date={target_date.date()}.  "
            "Ensure historical_df contains development-period data."
        )

    sampled = rng.choice(pool, size=n_simulations, replace=True)
    return [pd.Timestamp(d).normalize() for d in sampled]


# ── Batch prediction helpers ──────────────────────────────────────────────────

def _day_slice(df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """Return rows for a single calendar day from a 15-min DataFrame."""
    start = date.normalize()
    end   = start + pd.Timedelta(days=1)
    return df.loc[(df.index >= start) & (df.index < end)]


def _batch_predict_solar(
    unique_dates:            list[pd.Timestamp],
    prepared_train:          pd.DataFrame,
    solar_model:             xgb.XGBRegressor,
    generation_scale_factor: float,
) -> dict[pd.Timestamp, np.ndarray]:
    """
    Predict solar generation for each date in ``unique_dates``.

    Uses the analogue day's own historical PRIMARY_FEATURES (lags from that
    day's past, clear-sky irradiance, weather, calendar – no same-timestamp
    measured GHI or clear_sky_index for the target date).

    Returns dict: date → np.ndarray of shape (STEPS_PER_DAY,) in Wh (scaled).
    """
    result: dict[pd.Timestamp, np.ndarray] = {}
    features_to_use = mds_solar.PRIMARY_FEATURES

    for date in unique_dates:
        rows = _day_slice(prepared_train, date)
        out  = np.zeros(STEPS_PER_DAY)
        if not rows.empty:
            available_features = [f for f in features_to_use if f in rows.columns]
            n   = min(len(rows), STEPS_PER_DAY)
            raw = solar_model.predict(rows.iloc[:n][available_features].values)
            raw = np.clip(raw, 0.0, None) * generation_scale_factor
            out[:n] = raw
        result[date] = out

    return result


def _batch_predict_load(
    unique_dates:  list[pd.Timestamp],
    prepared_train: pd.DataFrame,
    model:          xgb.XGBRegressor,
    scaler:         StandardScaler,
    feature_cols:   list[str],
    cols_to_scale:  list[str],
) -> dict[pd.Timestamp, np.ndarray]:
    """
    Predict factory load for each date in ``unique_dates``.

    Model was trained with np.log1p(y), so predictions need np.expm1().

    Returns dict: date → np.ndarray of shape (STEPS_PER_DAY,) in kWh/15 min.
    """
    result: dict[pd.Timestamp, np.ndarray] = {}

    for date in unique_dates:
        rows = _day_slice(prepared_train, date)
        out  = np.zeros(STEPS_PER_DAY)
        if not rows.empty:
            available_feature_cols = [c for c in feature_cols if c in rows.columns]
            n    = min(len(rows), STEPS_PER_DAY)
            feat = rows.iloc[:n][available_feature_cols].copy()

            avail_scale = [c for c in cols_to_scale if c in feat.columns]
            feat[avail_scale] = scaler.transform(feat[avail_scale])

            raw = np.expm1(model.predict(feat.values))
            raw = np.clip(raw, 0.0, None)
            out[:n] = raw
        result[date] = out

    return result


def _build_simulation_matrix(
    analogue_list:  list[list[pd.Timestamp]],   # [n_target_days][n_sim] analogue dates
    day_preds_dict: dict[pd.Timestamp, np.ndarray],
) -> tuple[np.ndarray, list[pd.Timestamp]]:
    """
    Stack simulation results into (n_sim, n_target_days × STEPS_PER_DAY) matrix.
    analogue_list[i][k] = analogue date for target day i, simulation k.
    """
    n_sim     = len(analogue_list[0])
    n_days    = len(analogue_list)
    total_steps = n_days * STEPS_PER_DAY
    matrix = np.empty((n_sim, total_steps), dtype=np.float64)
    for i, analogues in enumerate(analogue_list):
        col_start = i * STEPS_PER_DAY
        col_end   = col_start + STEPS_PER_DAY
        for k, date in enumerate(analogues):
            matrix[k, col_start:col_end] = day_preds_dict.get(
                date, np.zeros(STEPS_PER_DAY)
            )
    return matrix


# ── Component 2: Generation Monte Carlo ───────────────────────────────────────

def mc_generation_forecast(
    target_dates:            list[pd.Timestamp | datetime],
    solar_model:             xgb.XGBRegressor,
    weather_features_df:     pd.DataFrame,
    historical_actual_df:    pd.DataFrame,
    n_simulations:           int  = 500,
    *,
    window_days:             int   = 21,
    generation_scale_factor: float = CFG.generation_scale_factor,
    seed:                    int   = SEED,
    _test_dates:             frozenset[pd.Timestamp] | None = None,
) -> dict[str, Any]:
    """
    Monte Carlo P10/P50/P90 for solar generation over ``target_dates``.

    Parameters
    ----------
    target_dates         : list of future dates to forecast (e.g. 7 days)
    solar_model          : trained XGBoostRegressor (raw Wh/15 min, unscaled)
    weather_features_df  : prepared solar training features (index=Time, 15-min)
                           Must cover the development period (caller responsibility).
    historical_actual_df : same DataFrame (used for analogue pool metadata)
    n_simulations        : analogue draws per target day
    _test_dates          : pre-computed test dates (skip auto-detect in tests)

    Returns
    -------
    dict with keys:
        'p10', 'p50', 'p90'  → pd.Series (index=timestamps, Wh)
        'generated_at'       → pd.Timestamp UTC
        'unit'               → 'Wh'
    """
    rng = np.random.default_rng(seed)
    target_dates = [pd.Timestamp(d).normalize() for d in target_dates]

    test_dates = _test_dates if _test_dates is not None else _detect_test_dates()
    dev_pool   = _build_solar_dev_pool(weather_features_df, test_dates)

    # Sample analogue days per target day
    analogue_list: list[list[pd.Timestamp]] = []
    for td in target_dates:
        analogue_list.append(
            sample_analogue_days(td, dev_pool,
                                 n_simulations=n_simulations,
                                 window_days=window_days,
                                 rng=rng)
        )

    # Batch predict unique analogue days once
    unique_days = list({d for days in analogue_list for d in days})
    day_preds   = _batch_predict_solar(
        unique_days, weather_features_df, solar_model, generation_scale_factor
    )

    # Build simulation matrix (n_sim × total_steps)
    matrix = _build_simulation_matrix(analogue_list, day_preds)

    # Build timestamp index
    timestamps = pd.DatetimeIndex([
        td + k * _INTERVAL
        for td in target_dates
        for k  in range(STEPS_PER_DAY)
    ])

    return {
        "p10":          pd.Series(np.percentile(matrix, 10, axis=0), index=timestamps),
        "p50":          pd.Series(np.percentile(matrix, 50, axis=0), index=timestamps),
        "p90":          pd.Series(np.percentile(matrix, 90, axis=0), index=timestamps),
        "generated_at": pd.Timestamp.now(tz="UTC"),
        "unit":         "Wh",
    }


# ── Component 3: Load Monte Carlo ─────────────────────────────────────────────

def mc_load_forecast(
    target_dates:     list[pd.Timestamp | datetime],
    load_model:       dict[str, Any],          # bundle dict from fit_pload_model_once
    historical_load_df: pd.DataFrame,          # prepared training DataFrame
    n_simulations:    int  = 500,
    *,
    window_days:      int  = 21,
    seed:             int  = SEED,
    _test_dates:      frozenset[pd.Timestamp] | None = None,
) -> dict[str, Any]:
    """
    Monte Carlo P10/P50/P90 for factory load over ``target_dates``.

    Parameters
    ----------
    target_dates      : list of future dates to forecast
    load_model        : bundle dict from ``fit_pload_model_once`` containing
                        'model', 'scaler', 'feature_cols', 'cols_to_scale'
    historical_load_df: prepared load training DataFrame (from _get_prepared_steel)
    n_simulations     : analogue draws per target day

    Returns
    -------
    dict with keys:
        'p10', 'p50', 'p90'  → pd.Series (index=timestamps, kWh/15 min)
        'generated_at'       → pd.Timestamp UTC
        'unit'               → 'kWh'
    """
    rng = np.random.default_rng(seed)
    target_dates = [pd.Timestamp(d).normalize() for d in target_dates]

    model        = load_model["model"]
    scaler       = load_model["scaler"]
    feature_cols = load_model["feature_cols"]
    cols_scale   = load_model["cols_to_scale"]

    test_dates = _test_dates if _test_dates is not None else _detect_test_dates()
    dev_pool   = _build_load_dev_pool(historical_load_df, test_dates)

    analogue_list: list[list[pd.Timestamp]] = []
    for td in target_dates:
        is_wkend = 1 if td.weekday() >= 5 else 0
        analogue_list.append(
            sample_analogue_days(td, dev_pool,
                                 n_simulations=n_simulations,
                                 window_days=window_days,
                                 is_weekend=is_wkend,
                                 rng=rng)
        )

    unique_days = list({d for days in analogue_list for d in days})
    day_preds   = _batch_predict_load(
        unique_days, historical_load_df,
        model, scaler, feature_cols, cols_scale
    )

    matrix = _build_simulation_matrix(analogue_list, day_preds)

    timestamps = pd.DatetimeIndex([
        td + k * _INTERVAL
        for td in target_dates
        for k  in range(STEPS_PER_DAY)
    ])

    return {
        "p10":          pd.Series(np.percentile(matrix, 10, axis=0), index=timestamps),
        "p50":          pd.Series(np.percentile(matrix, 50, axis=0), index=timestamps),
        "p90":          pd.Series(np.percentile(matrix, 90, axis=0), index=timestamps),
        "generated_at": pd.Timestamp.now(tz="UTC"),
        "unit":         "kWh",
    }


# ── Component 4: Annual Scenario Generator ────────────────────────────────────

_ANNUAL_DISCLAIMER = (
    "Planning scenario only, not a meteorological forecast.  "
    "Model training data originates from a European industrial plant; "
    "actual performance under Taiwan operating conditions may differ."
)


def generate_annual_scenarios(
    solar_model:             xgb.XGBRegressor,
    load_model:              dict[str, Any],
    historical_df:           dict[str, pd.DataFrame],
    start_date:              pd.Timestamp | datetime,
    n_simulations:           int   = 200,
    *,
    window_days:             int   = 21,
    generation_scale_factor: float = CFG.generation_scale_factor,
    seed:                    int   = SEED,
    _test_dates:             frozenset[pd.Timestamp] | None = None,
) -> dict[str, Any]:
    """
    Generate annual (365-day) generation and load planning scenarios.

    Parameters
    ----------
    solar_model      : trained XGBoost solar model
    load_model       : trained load model bundle
    historical_df    : dict with keys 'solar' (prepared solar train DF) and
                       'load' (prepared load train DF)
    start_date       : first day of the 365-day projection
    n_simulations    : number of independent annual scenarios (default 200)

    Returns
    -------
    dict with keys:
        'annual_generation' : {'p10', 'p50', 'p90', 'mean'}  in kWh
        'annual_load'       : {'p10', 'p50', 'p90', 'mean'}  in kWh
        'generated_at'      : pd.Timestamp UTC
        'unit'              : 'kWh'
        'n_simulations'     : int
        'disclaimer'        : str
    """
    rng         = np.random.default_rng(seed)
    start_date  = pd.Timestamp(start_date).normalize()
    target_days = [start_date + timedelta(days=k) for k in range(365)]

    solar_df   = historical_df["solar"]
    load_df    = historical_df["load"]
    model      = load_model["model"]
    scaler     = load_model["scaler"]
    feat_cols  = load_model["feature_cols"]
    scale_cols = load_model["cols_to_scale"]

    test_dates       = _test_dates if _test_dates is not None else _detect_test_dates()
    solar_dev_pool   = _build_solar_dev_pool(solar_df,  test_dates)
    load_dev_pool    = _build_load_dev_pool(load_df,    test_dates)

    # ── Sample all analogue days upfront ────────────────────────────────────
    # solar_analogue[i] = list of n_sim dates for target day i
    # load_analogue[i]  = same for load
    solar_analogue: list[list[pd.Timestamp]] = []
    load_analogue:  list[list[pd.Timestamp]] = []

    for td in target_days:
        solar_analogue.append(
            sample_analogue_days(td, solar_dev_pool,
                                 n_simulations=n_simulations,
                                 window_days=window_days,
                                 rng=rng)
        )
        is_wkend = 1 if pd.Timestamp(td).weekday() >= 5 else 0
        load_analogue.append(
            sample_analogue_days(td, load_dev_pool,
                                 n_simulations=n_simulations,
                                 window_days=window_days,
                                 is_weekend=is_wkend,
                                 rng=rng)
        )

    # ── Batch predict unique analogue days ───────────────────────────────────
    unique_solar = list({d for days in solar_analogue for d in days})
    unique_load  = list({d for days in load_analogue  for d in days})

    solar_preds = _batch_predict_solar(
        unique_solar, solar_df, solar_model, generation_scale_factor
    )
    load_preds  = _batch_predict_load(
        unique_load, load_df, model, scaler, feat_cols, scale_cols
    )

    # ── Compute annual totals per simulation ─────────────────────────────────
    # shape: (n_sim, 365 * STEPS_PER_DAY)
    solar_matrix = _build_simulation_matrix(solar_analogue, solar_preds)
    load_matrix  = _build_simulation_matrix(load_analogue,  load_preds)

    # Sum over all time steps; Wh → kWh for solar, kWh for load (per 15 min)
    annual_gen_kwh  = solar_matrix.sum(axis=1) / 1000.0   # Wh → kWh
    annual_load_kwh = load_matrix.sum(axis=1)              # already kWh/15-min summed

    def _stats(arr: np.ndarray) -> dict[str, float]:
        return {
            "p10":  float(np.percentile(arr, 10)),
            "p50":  float(np.percentile(arr, 50)),
            "p90":  float(np.percentile(arr, 90)),
            "mean": float(arr.mean()),
        }

    return {
        "annual_generation": _stats(annual_gen_kwh),
        "annual_load":       _stats(annual_load_kwh),
        "generated_at":      pd.Timestamp.now(tz="UTC"),
        "unit":              "kWh",
        "n_simulations":     n_simulations,
        "disclaimer":        _ANNUAL_DISCLAIMER,
    }


# ── Model / data loader (convenience) ────────────────────────────────────────

class MCModels:
    """
    Container for loaded and trained models + prepared data.

    Usage
    -----
    models = MCModels.load()
    result = mc_generation_forecast(target_dates, models.solar_model, ...)
    """

    def __init__(
        self,
        solar_model:          xgb.XGBRegressor,
        solar_prepared_train: pd.DataFrame,
        load_bundle:          dict[str, Any],
        load_prepared_train:  pd.DataFrame,
        test_dates:           frozenset[pd.Timestamp],
    ) -> None:
        self.solar_model          = solar_model
        self.solar_prepared_train = solar_prepared_train
        self.load_bundle          = load_bundle
        self.load_prepared_train  = load_prepared_train
        self.test_dates           = test_dates

    @classmethod
    def load(
        cls,
        solar_train_csv: Path | str = RENEWABLE_TRAIN_CSV,
        load_train_csv:  Path | str = STEEL_TRAIN_CSV,
    ) -> "MCModels":
        """Load data, train (or retrieve cached) models, return ready-to-use container."""
        solar_train_csv = Path(solar_train_csv)
        load_train_csv  = Path(load_train_csv)

        # ── Solar ──────────────────────────────────────────────────────────
        solar_df = mds_solar.load_and_prepare_solar(solar_train_csv)
        solar_model, _ = mds_solar.fit_solar_model_once(solar_df, solar_train_csv)

        # ── Load ───────────────────────────────────────────────────────────
        load_df, feat_cols, scale_cols, resolved = _get_prepared_steel(load_train_csv)
        load_bundle = fit_pload_model_once(
            load_df, feat_cols, scale_cols, resolved
        )

        return cls(
            solar_model=solar_model,
            solar_prepared_train=solar_df,
            load_bundle=load_bundle,
            load_prepared_train=load_df,
            test_dates=_detect_test_dates(),
        )
