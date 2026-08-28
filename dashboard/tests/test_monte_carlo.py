"""
Unit tests for monte_carlo_forecast.py

Coverage:
  - No test set leakage: sampled analogue dates are not in test set
  - Percentile ordering: P10 ≤ P50 ≤ P90 at every time step
  - Correct output shapes (days × 96 time steps)
  - Annual scenario returns valid statistics

Run with:
    cd /Users/stephenlin/Downloads/MDS_final/dashboard
    .venv/bin/pytest tests/test_monte_carlo.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_DASHBOARD = Path(__file__).resolve().parent.parent
_EMS_ROOT  = _DASHBOARD.parent.parent / "mds-final"
if not _EMS_ROOT.is_dir():
    _EMS_ROOT = _DASHBOARD.parent / "mds-final"
if str(_EMS_ROOT) not in sys.path:
    sys.path.insert(0, str(_EMS_ROOT))
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

from monte_carlo_forecast import (
    SEED,
    STEPS_PER_DAY,
    _detect_test_dates,
    _build_solar_dev_pool,
    _build_load_dev_pool,
    _batch_predict_solar,
    _batch_predict_load,
    sample_analogue_days,
    mc_generation_forecast,
    mc_load_forecast,
    generate_annual_scenarios,
    MCModels,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_dates():
    return _detect_test_dates()


@pytest.fixture(scope="session")
def models(tmp_path_factory):
    """Load models once for the entire test session (expensive)."""
    return MCModels.load()


@pytest.fixture(scope="session")
def solar_dev_pool(models, test_dates):
    return _build_solar_dev_pool(models.solar_prepared_train, test_dates)


@pytest.fixture(scope="session")
def load_dev_pool(models, test_dates):
    return _build_load_dev_pool(models.load_prepared_train, test_dates)


# Lightweight synthetic fixtures for shape / ordering tests (fast, no model loading)

@pytest.fixture(scope="module")
def fake_solar_df():
    """Minimal DataFrame mimicking prepared solar training data."""
    import mds_solar
    rng  = np.random.default_rng(0)
    idx  = pd.date_range("2017-01-01", periods=365 * STEPS_PER_DAY, freq="15min")
    data = {f: rng.uniform(0, 10, len(idx)) for f in mds_solar.PRIMARY_FEATURES}
    data["clouds_all"]          = rng.uniform(0, 100, len(idx))
    data["Energy delta[Wh]"]    = rng.uniform(0, 5000, len(idx))
    data["energy_delta_lag_1d"] = rng.uniform(0, 5000, len(idx))
    return pd.DataFrame(data, index=idx)


@pytest.fixture(scope="module")
def fake_load_df():
    """Minimal DataFrame mimicking prepared load training data."""
    rng = np.random.default_rng(1)
    idx = pd.date_range("2018-01-01", periods=180 * STEPS_PER_DAY, freq="15min")
    data: dict = {
        "Usage_kWh":        rng.uniform(5, 50, len(idx)),
        "Lag_1":            rng.uniform(5, 50, len(idx)),
        "Lag_2":            rng.uniform(5, 50, len(idx)),
        "Lag_4":            rng.uniform(5, 50, len(idx)),
        "Lag_96":           rng.uniform(5, 50, len(idx)),
        "Trend_15min":      rng.uniform(-5, 5, len(idx)),
        "Rolling_Mean_1h":  rng.uniform(5, 50, len(idx)),
        "Rolling_Std_2h":   rng.uniform(0, 5, len(idx)),
        "WeekStatus":       rng.integers(0, 2, len(idx)).astype(float),
        "Taipower_TOU":     rng.integers(1, 5, len(idx)).astype(float),
        "Month_sin":        np.sin(2 * np.pi * idx.month / 12),
        "Month_cos":        np.cos(2 * np.pi * idx.month / 12),
        "Hour_sin":         np.sin(2 * np.pi * idx.hour / 24),
        "Hour_cos":         np.cos(2 * np.pi * idx.hour / 24),
    }
    for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        data[f"Day_of_week_{day}"] = 0.0
    return pd.DataFrame(data, index=idx)


@pytest.fixture(scope="module")
def fake_xgb_solar(fake_solar_df):
    """XGBoost solar model trained on synthetic data."""
    import mds_solar
    import xgboost as xgb
    model = xgb.XGBRegressor(n_estimators=10, max_depth=3, random_state=SEED, verbosity=0)
    X = fake_solar_df[mds_solar.PRIMARY_FEATURES]
    y = fake_solar_df["Energy delta[Wh]"]
    model.fit(X, y)
    return model


@pytest.fixture(scope="module")
def fake_xgb_load(fake_load_df):
    """XGBoost load model + scaler trained on synthetic data (with log1p)."""
    import xgboost as xgb
    from sklearn.preprocessing import StandardScaler
    feature_cols = [c for c in fake_load_df.columns if c != "Usage_kWh"]
    cols_scale   = [c for c in feature_cols
                    if c not in ("WeekStatus", "Taipower_TOU")
                    and not c.startswith("Day_of_week")]
    X = fake_load_df[feature_cols]
    y = fake_load_df["Usage_kWh"]
    scaler = StandardScaler()
    Xs = X.copy()
    Xs[cols_scale] = scaler.fit_transform(Xs[cols_scale])
    model = xgb.XGBRegressor(n_estimators=10, max_depth=3, random_state=SEED, verbosity=0)
    model.fit(Xs, np.log1p(y))
    return {
        "model":         model,
        "scaler":        scaler,
        "feature_cols":  feature_cols,
        "cols_to_scale": cols_scale,
    }


# ── Test: no test set leakage ─────────────────────────────────────────────────

class TestNoTestSetLeakage:
    def test_solar_dev_pool_excludes_test_dates(self, solar_dev_pool, test_dates):
        pool_dates = frozenset(pd.Timestamp(d).normalize() for d in solar_dev_pool.index)
        leaked = pool_dates & test_dates
        assert len(leaked) == 0, f"Test dates leaked into solar dev pool: {sorted(leaked)[:5]}"

    def test_load_dev_pool_excludes_test_dates(self, load_dev_pool, test_dates):
        pool_dates = frozenset(pd.Timestamp(d).normalize() for d in load_dev_pool.index)
        leaked = pool_dates & test_dates
        assert len(leaked) == 0, f"Test dates leaked into load dev pool: {sorted(leaked)[:5]}"

    def test_sample_analogue_days_excludes_test_dates(
        self, solar_dev_pool, test_dates
    ):
        target = pd.Timestamp("2018-07-01")
        sampled = sample_analogue_days(target, solar_dev_pool, n_simulations=200)
        sampled_dates = frozenset(pd.Timestamp(d).normalize() for d in sampled)
        leaked = sampled_dates & test_dates
        assert len(leaked) == 0, f"Sampled dates in test set: {sorted(leaked)[:5]}"

    def test_sample_excludes_exact_target_date(self, solar_dev_pool):
        """Analogue pool must not include the target date itself."""
        # Use a target date that IS in the solar dev pool
        target = solar_dev_pool.index[50]
        sampled = sample_analogue_days(target, solar_dev_pool, n_simulations=300)
        sampled_set = {pd.Timestamp(d).normalize() for d in sampled}
        assert target.normalize() not in sampled_set


# ── Test: percentile ordering ─────────────────────────────────────────────────

class TestPercentileOrdering:
    def test_generation_p10_le_p50_le_p90(
        self, fake_solar_df, fake_xgb_solar
    ):
        test_dates_fake = frozenset()   # no test dates in synthetic data
        target = [pd.Timestamp("2017-07-01") + pd.Timedelta(days=k) for k in range(3)]
        result = mc_generation_forecast(
            target_dates=target,
            solar_model=fake_xgb_solar,
            weather_features_df=fake_solar_df,
            historical_actual_df=fake_solar_df,
            n_simulations=50,
            _test_dates=test_dates_fake,
        )
        p10, p50, p90 = result["p10"].values, result["p50"].values, result["p90"].values
        assert np.all(p10 <= p50 + 1e-9), "P10 > P50 at some time step"
        assert np.all(p50 <= p90 + 1e-9), "P50 > P90 at some time step"

    def test_load_p10_le_p50_le_p90(self, fake_load_df, fake_xgb_load):
        test_dates_fake = frozenset()
        target = [pd.Timestamp("2018-01-08") + pd.Timedelta(days=k) for k in range(3)]
        result = mc_load_forecast(
            target_dates=target,
            load_model=fake_xgb_load,
            historical_load_df=fake_load_df,
            n_simulations=50,
            _test_dates=test_dates_fake,
        )
        p10, p50, p90 = result["p10"].values, result["p50"].values, result["p90"].values
        assert np.all(p10 <= p50 + 1e-9), "P10 > P50 at some time step (load)"
        assert np.all(p50 <= p90 + 1e-9), "P50 > P90 at some time step (load)"

    def test_annual_p10_le_p50_le_p90(
        self, fake_solar_df, fake_xgb_solar, fake_load_df, fake_xgb_load
    ):
        test_dates_fake = frozenset()
        result = generate_annual_scenarios(
            solar_model=fake_xgb_solar,
            load_model=fake_xgb_load,
            historical_df={"solar": fake_solar_df, "load": fake_load_df},
            start_date=pd.Timestamp("2017-01-01"),
            n_simulations=30,
            _test_dates=test_dates_fake,
        )
        g, l = result["annual_generation"], result["annual_load"]
        assert g["p10"] <= g["p50"] <= g["p90"], "Annual generation percentile order violated"
        assert l["p10"] <= l["p50"] <= l["p90"], "Annual load percentile order violated"


# ── Test: correct output shapes ───────────────────────────────────────────────

class TestOutputShapes:
    @pytest.mark.parametrize("days", [1, 3, 7])
    def test_generation_shape(self, fake_solar_df, fake_xgb_solar, days):
        test_dates_fake = frozenset()
        target = [pd.Timestamp("2017-07-01") + pd.Timedelta(days=k) for k in range(days)]
        result = mc_generation_forecast(
            target_dates=target,
            solar_model=fake_xgb_solar,
            weather_features_df=fake_solar_df,
            historical_actual_df=fake_solar_df,
            n_simulations=20,
            _test_dates=test_dates_fake,
        )
        expected_len = days * STEPS_PER_DAY
        for key in ("p10", "p50", "p90"):
            assert len(result[key]) == expected_len, (
                f"{key} has {len(result[key])} elements, expected {expected_len}"
            )

    @pytest.mark.parametrize("days", [1, 7])
    def test_load_shape(self, fake_load_df, fake_xgb_load, days):
        test_dates_fake = frozenset()
        target = [pd.Timestamp("2018-01-08") + pd.Timedelta(days=k) for k in range(days)]
        result = mc_load_forecast(
            target_dates=target,
            load_model=fake_xgb_load,
            historical_load_df=fake_load_df,
            n_simulations=20,
            _test_dates=test_dates_fake,
        )
        expected_len = days * STEPS_PER_DAY
        for key in ("p10", "p50", "p90"):
            assert len(result[key]) == expected_len

    def test_annual_keys_present(
        self, fake_solar_df, fake_xgb_solar, fake_load_df, fake_xgb_load
    ):
        test_dates_fake = frozenset()
        result = generate_annual_scenarios(
            solar_model=fake_xgb_solar,
            load_model=fake_xgb_load,
            historical_df={"solar": fake_solar_df, "load": fake_load_df},
            start_date=pd.Timestamp("2017-01-01"),
            n_simulations=20,
            _test_dates=test_dates_fake,
        )
        for section in ("annual_generation", "annual_load"):
            for stat in ("p10", "p50", "p90", "mean"):
                assert stat in result[section], f"Missing {section}.{stat}"
        assert "disclaimer" in result
        assert "generated_at" in result

    def test_timestamps_are_monotone(self, fake_solar_df, fake_xgb_solar):
        test_dates_fake = frozenset()
        target = [pd.Timestamp("2017-07-01") + pd.Timedelta(days=k) for k in range(7)]
        result = mc_generation_forecast(
            target_dates=target,
            solar_model=fake_xgb_solar,
            weather_features_df=fake_solar_df,
            historical_actual_df=fake_solar_df,
            n_simulations=20,
            _test_dates=test_dates_fake,
        )
        ts = result["p50"].index
        assert ts.is_monotonic_increasing, "Output timestamps are not monotonically increasing"


# ── Test: sample_analogue_days pool behaviour ─────────────────────────────────

class TestAnalogueSampler:
    def test_returns_correct_count(self, solar_dev_pool):
        for n in (10, 100, 500):
            sampled = sample_analogue_days(
                pd.Timestamp("2018-01-15"), solar_dev_pool, n_simulations=n
            )
            assert len(sampled) == n

    def test_all_dates_in_dev_pool(self, solar_dev_pool):
        pool_set = {pd.Timestamp(d).normalize() for d in solar_dev_pool.index}
        target   = pd.Timestamp("2018-01-15")
        sampled  = sample_analogue_days(target, solar_dev_pool, n_simulations=200)
        for d in sampled:
            assert pd.Timestamp(d).normalize() in pool_set, (
                f"Sampled date {d} not in dev pool"
            )

    def test_fallback_when_pool_too_small(self):
        """If initial pool is tiny, fallback should still return requested count."""
        tiny_df = pd.DataFrame(
            {"cloud_category": [1], "is_weekend": [0]},
            index=pd.DatetimeIndex(["2017-01-15"]),
        )
        sampled = sample_analogue_days(
            pd.Timestamp("2017-06-15"), tiny_df, n_simulations=50,
            target_cloud_category=1,
        )
        assert len(sampled) == 50


# ── Integration test (slow, uses real models – mark to allow skipping) ────────

@pytest.mark.slow
class TestIntegration:
    def test_7day_generation_real_models(self, models):
        target = [pd.Timestamp("2018-06-29") + pd.Timedelta(days=k) for k in range(7)]
        result = mc_generation_forecast(
            target_dates=target,
            solar_model=models.solar_model,
            weather_features_df=models.solar_prepared_train,
            historical_actual_df=models.solar_prepared_train,
            n_simulations=100,
            _test_dates=models.test_dates,
        )
        assert len(result["p50"]) == 7 * STEPS_PER_DAY
        assert np.all(result["p10"].values <= result["p90"].values + 1e-9)
        # P50 should be non-negative everywhere
        assert np.all(result["p50"].values >= 0.0)

    def test_7day_load_real_models(self, models):
        target = [pd.Timestamp("2018-06-29") + pd.Timedelta(days=k) for k in range(7)]
        result = mc_load_forecast(
            target_dates=target,
            load_model=models.load_bundle,
            historical_load_df=models.load_prepared_train,
            n_simulations=100,
            _test_dates=models.test_dates,
        )
        assert len(result["p50"]) == 7 * STEPS_PER_DAY
        assert np.all(result["p50"].values >= 0.0)
