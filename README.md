# Solar Power Forecasting + Battery Dispatch Optimization

A end-to-end pipeline that forecasts solar PV generation and uses the forecast to optimally schedule a battery storage system via Mixed-Integer Linear Programming (MILP).

## Overview

The project addresses a real-world energy management problem: given a solar panel installation and a battery, decide when to charge and discharge each hour to minimize electricity cost and over-contract penalties — using only information that would be available in a true day-ahead setting.

**Pipeline stages:**

```
Raw data → Cleaning → Feature Engineering → XGBoost Forecast
        → Quantile Lower Bound → MILP Battery Dispatch

Optional diagnostics:
Monte Carlo Backtest / Year Projection
```

The forecast is **day-ahead strict**: same-time measured GHI and cloud index are excluded from all models. Only lagged and theoretical (pvlib) features are used.

**Important note about Monte Carlo:** Monte Carlo is not part of the main research backbone in this project. The main pipeline is still feature engineering → XGBoost/q10 prediction → MILP dispatch. Monte Carlo is added only as a diagnostic sanity check to verify that the model and conservative forecast are not overly optimistic under different historical sunlight scenarios.

---

## Dataset

The raw dataset (`Renewable.csv`) covers:

- **Frequency:** 15-minute intervals
- **Range:** 2017-01-01 to 2022-08-31
- **Rows after cleaning:** 198,600
- **Target variable:** `Energy delta[Wh]` — solar energy output per 15-minute interval

The dataset is not included in this repository due to file size. Place `Renewable.csv` in the project root before running.

---

## Setup

```bash
pip install -r requirements.txt
```

Python 3.10+ required. XGBoost >= 2.0.0 is required for the `reg:quantileerror` objective.

---

## How to Run

Run each script in order from the project root directory.

**Step 1 — Clean the raw data**

```bash
python clean_renewable.py
```

Outputs `Renewable_cleaned.csv`. Handles missing timestamps, clips physically impossible values, fills gaps using calendar averages.

**Step 2 — Feature engineering**

```bash
python engineer_renewable_features.py
```

Outputs `Renewable_featured.csv`. Adds astronomical features via pvlib (clear-sky irradiance, solar position), cyclic time encodings, lag and rolling features. Site coordinates are estimated from the data itself using day-length and solar noon geometry.

**Step 3 — Train point forecast model**

```bash
python train_xgboost_pipeline.py
```

Trains a forecast-strict XGBoost model (tuned via Optuna) and evaluates on the held-out test set. Outputs predictions, metrics, and SHAP analysis to `model_results/`.

Set `USE_FIXED_PARAMS=1` to skip Optuna and use pre-tuned parameters (faster):

```bash
USE_FIXED_PARAMS=1 python train_xgboost_pipeline.py
```

**Step 4 — Train quantile lower bound model**

```bash
python train_quantile_model.py
```

Trains a 10th-percentile (q10) quantile XGBoost model using the same features and hyperparameters. Outputs 15-min q10 predictions and a hourly MILP-ready forecast file. Run after Step 3.

**Optional — Monte Carlo backtest**

```bash
MC_BACKTEST_SIMULATIONS=1000 python monte_carlo_backtest.py
```

This is an auxiliary diagnostic, not a core stage of the research method. It helps answer whether the trained forecast behaves too optimistically under many historical sunlight scenarios. The model is trained only on the development period, Monte Carlo analogue days are sampled only from the development period, and the results are compared against held-out complete test days.

**Optional — Monte Carlo yearly solar projection**

```bash
python monte_carlo_yearly_solar.py
```

This estimates the next year of solar generation using historical analogue-day Monte Carlo sampling. It first trains the existing point and q10 models on all available featured data, samples historically similar days for each future day, and outputs annual/monthly/daily probability summaries and plots to `model_results/monte_carlo_year/`.

Useful options:

```bash
MC_FUTURE_START=2026-05-16 MC_SIMULATIONS=1000 python monte_carlo_yearly_solar.py
```

**Step 5 — MILP battery dispatch**

```bash
python milp_daily_schedule.py
```

Solves the single-day battery dispatch optimization for three representative test days (sunny, cloudy, solar-surplus). To solve a specific date:

```bash
python milp_daily_schedule.py 2022-06-03
```

---

## Model Results

### Point Forecast (test set: 2021-07-14 to 2022-08-31)

| Metric | Value |
|--------|-------|
| MAPE | 36.10% |
| R² | 0.8599 |
| RMSE | 452.82 Wh |
| MAE | 261.50 Wh |
| nRMSE (observed capacity) | 9.02% |
| Bias | +6.36 Wh |

MAPE is inflated by dawn/dusk and cloudy-transition periods with low actual generation. R² and nRMSE are more reliable indicators of forecast quality for this application.

### Quantile Lower Bound (q10, daylight hours only)

| Metric | Value |
|--------|-------|
| Target coverage (1 − α) | 90% |
| Actual coverage | 89.07% |
| Mean gap (q10 − actual) | −444 Wh |

### Monte Carlo Backtest (held-out daily test)

This is a supplementary sanity check, not the research backbone and not a replacement for the held-out XGBoost test-set evaluation. Its purpose is to check whether the model and q10 conservative forecast are too optimistic when exposed to many sampled historical sunlight scenarios.

- Test period evaluated: 412 complete days, 2021-07-15 to 2022-08-30
- Monte Carlo simulations: 1,000 per test day
- Analogue pool: development data only, ±21 day-of-year window

| Backtest item | Value | Interpretation |
|---------------|-------|----------------|
| Direct model daily MAPE | 17.00% | Point model is accurate at daily aggregation |
| Direct model daily R² | 0.9785 | Very strong daily fit on held-out days |
| Direct model daily RMSE | 5,609 Wh | Average daily-scale error magnitude |
| Direct model total bias | +1.42% | Total generation is only slightly overpredicted |
| Direct q10 daily coverage | 98.06% | Conservative forecast is safely below actual most days |
| MC mean daily MAPE | 131.86% | Analogue Monte Carlo mean is not a good daily point forecast |
| MC p10-p90 coverage | 79.85% | The uncertainty interval is well calibrated versus nominal 80% |

Main takeaway: use the XGBoost model for point prediction, use Monte Carlo for uncertainty/risk bands. The Monte Carlo mean should not replace the model prediction as the daily forecast.

In report wording, this should be described as:

> Monte Carlo simulation is used as an auxiliary robustness check to examine whether the forecast is overly optimistic under uncertain sunlight conditions. It is not the main modeling method; the main predictive model remains the forecast-strict XGBoost/q10 pipeline.

Outputs:

- `model_results/monte_carlo_backtest/monte_carlo_backtest_summary.json`
- `model_results/monte_carlo_backtest/monte_carlo_backtest_daily.csv`
- `model_results/monte_carlo_backtest/backtest_daily_timeseries.png`
- `model_results/monte_carlo_backtest/backtest_actual_vs_prediction.png`
- `model_results/monte_carlo_backtest/backtest_residual_by_month.png`
- `model_results/monte_carlo_backtest/backtest_interval_coverage.png`

Plot PNG files are generated locally by the script and ignored by git. Regenerate them when needed rather than committing image artifacts.

### Monte Carlo Next-Year Solar Projection

Projection period:

- 2026-05-16 + 365 days
- 1,000 Monte Carlo simulations
- historical analogue window: ±21 day-of-year days

| Forecast | Annual mean | Annual p10 | Annual p50 | Annual p90 |
|----------|-------------|------------|------------|------------|
| Point forecast | 19,463.6 kWh | 18,791.2 kWh | 19,460.5 kWh | 20,162.0 kWh |
| Q10 conservative | 12,305.3 kWh | 11,676.1 kWh | 12,299.0 kWh | 12,945.4 kWh |

Outputs:

- `model_results/monte_carlo_year/monte_carlo_summary.json`
- `model_results/monte_carlo_year/monte_carlo_daily_summary.csv`
- `model_results/monte_carlo_year/monte_carlo_monthly_summary.csv`
- `model_results/monte_carlo_year/monte_carlo_annual_scenarios.csv`
- `model_results/monte_carlo_year/annual_total_distribution.png`
- `model_results/monte_carlo_year/monthly_energy_fan.png`
- `model_results/monte_carlo_year/daily_energy_fan.png`
- `model_results/monte_carlo_year/expected_monthly_energy.png`

Plot PNG files are generated locally by the script and ignored by git. Regenerate them when needed rather than committing image artifacts.

### MILP Dispatch (single-day prototype)

| Date | Scenario | Over-contract | End SOC | Status |
|------|----------|---------------|---------|--------|
| 2022-06-03 | Sunny | 0 Wh | 15,000 Wh | PASS |
| 2021-12-04 | Cloudy (661 Wh solar) | 12,750 Wh | 15,000 Wh | PASS |
| 2022-03-14 | Solar surplus | 0 Wh | 15,000 Wh | PASS |

---

## MILP Formulation

The optimizer minimizes grid energy cost and over-contract penalties subject to battery physics constraints.

**Decision variables** (per hour, Δt = 1 h):
- `P_c[t]`, `P_d[t]` — charge and discharge power [Wh/h]
- `b[t]` — binary charging mode indicator
- `SOC[t]` — state of charge at end of hour [Wh]
- `dp_normal[t]`, `dp_excess[t]` — piecewise grid draw split

**Three linearizations:**

1. **Big-M charge/discharge mutual exclusion**
   ```
   P_c[t] ≤ P_max · b[t]
   P_d[t] ≤ P_max · (1 − b[t])
   ```

2. **Over-contract piecewise split** (ΔP_normal / ΔP_excess)
   ```
   dp_normal[t] + dp_excess[t] ≥ P_grid[t]
   0 ≤ dp_normal[t] ≤ P_contract
   Objective penalty: C_e · dp_normal + (C_e + C_oc) · dp_excess
   ```

3. **Terminal SOC hard constraint** (end-of-day continuity + UPS reserve)
   ```
   SOC[23] ≥ max(SOC_init, UPS_reserve)
   ```
   Using `≥` (not `=`) so the model can end higher on surplus days without being forced to dump energy.

**Solver:** CBC via PuLP.

---

## File Structure

```
MDS_final/
├── clean_renewable.py            # Stage 1: data cleaning
├── engineer_renewable_features.py # Stage 2: feature engineering
├── train_xgboost_pipeline.py     # Stage 3: point forecast + Optuna tuning
├── train_quantile_model.py       # Stage 4: q10 quantile forecast
├── milp_daily_schedule.py        # Stage 5: MILP battery dispatch
├── monte_carlo_backtest.py       # Optional: held-out Monte Carlo sanity check
├── monte_carlo_yearly_solar.py   # Optional: next-year Monte Carlo projection
├── requirements.txt
├── model_results/
│   ├── predictions_test.csv          # Point forecast test predictions (15-min)
│   ├── predictions_quantile_q10.csv  # Q10 forecast test predictions (15-min)
│   ├── milp_solar_forecast_hourly.csv # Hourly MILP-ready solar forecast
│   ├── milp_schedule_<date>.csv      # Hourly dispatch schedule
│   ├── milp_summary_<date>.json      # Dispatch summary + validation
│   ├── metrics.json                  # Full pipeline metrics
│   ├── quantile_coverage.json        # Q10 coverage diagnostics
│   ├── monte_carlo_backtest/         # Held-out Monte Carlo backtest summaries + plots
│   ├── monte_carlo_year/             # Yearly Monte Carlo forecast summaries + plots
│   ├── shap_summary.png              # SHAP beeswarm plot
│   ├── shap_importance.csv           # Feature importance ranking
│   └── *.png                         # Residual and diagnostic plots
└── Renewable.csv                 # Raw data (not tracked in git)
```

---

## Key Design Decisions

**Day-ahead forecast strictness:** Same-time GHI and clear-sky index are excluded. Lagged versions (1h, 3h, 1d) are used instead. Same-time weather variables (temperature, humidity, cloud cover) are retained as a proxy for forecast weather inputs.

**Monte Carlo positioning:** Monte Carlo backtesting is intentionally treated as a secondary validation tool. It does not define the final forecast, tune the model, or drive the MILP directly. Its role is to provide evidence that the forecast distribution and q10 lower bound are not unrealistically optimistic.

**MAPE floor:** Denominator is `max(y_true, 100 Wh)` to prevent dawn/dusk near-zero values from dominating the error metric.

**Quantile model re-uses point model hyperparameters:** The q10 model uses the same Optuna-tuned hyperparameters as the point model without additional tuning. This is intentional — tuning the quantile model separately could overfit the coverage metric on the test set.

**Terminal SOC as hard constraint:** A soft SOC penalty in a single-day model is insufficient — the model rationally drains the battery by end of day since future value is not captured. A hard lower bound ensures each day starts from the same state, which is essential for rolling backtest correctness.

---

## Limitations

- Same-time weather variables (temp, clouds, etc.) are measured values, not weather forecasts. Reported MAPE is therefore an optimistic proxy for true day-ahead performance.
- The MILP uses a synthetic load profile. Real deployment requires actual or forecast load data.
- The current MILP is a single-day prototype. Rolling multi-day backtest is the next step.
- Site coordinates are estimated from the data. A small coordinate error affects clear-sky irradiance features but not materially, given that pvlib features rank 3rd–5th in SHAP importance rather than 1st.
