# Solar Power Forecasting + Battery Dispatch Optimization

This project forecasts solar PV generation and uses the forecast to schedule a battery storage system with Mixed-Integer Linear Programming (MILP).

The main research backbone is intentionally simple:

```text
Raw data -> Cleaning -> Feature Engineering -> XGBoost/q10 Forecast -> MILP Dispatch
```

Monte Carlo simulation is included only as an optional diagnostic. It is used to check whether the forecast and q10 conservative lower bound are too optimistic under uncertain sunlight scenarios; it is not the main modeling method.

## Documentation

- [Methodology](docs/methodology.md): cleaning, feature engineering, model design, leakage control, evaluation, q10, and MILP formulation.
- [Results](docs/results.md): point forecast, q10 coverage, Monte Carlo backtest, year projection, and MILP prototype results.
- [Monte Carlo Positioning](docs/monte_carlo_note.md): how to describe Monte Carlo correctly in the report.

## Dataset

The raw dataset is expected as `Renewable.csv` in the project root.

- Frequency: 15-minute intervals
- Range: 2017-01-01 to 2022-08-31
- Target: `Energy delta[Wh]`

Large data files are ignored by git:

- `Renewable.csv`
- `Renewable_cleaned.csv`
- `Renewable_featured.csv`

## Setup

```bash
pip install -r requirements.txt
```

Python 3.10+ is recommended. XGBoost >= 2.0.0 is required for quantile regression.

## Main Pipeline

Run from the project root.

```bash
python scripts/clean_renewable.py
python scripts/engineer_renewable_features.py
USE_FIXED_PARAMS=1 python scripts/train_xgboost_pipeline.py
python scripts/train_quantile_model.py
python scripts/milp_daily_schedule.py
```

To run full Optuna tuning instead of fixed tuned parameters:

```bash
python scripts/train_xgboost_pipeline.py
```

## Optional Diagnostics

Monte Carlo backtest:

```bash
MC_BACKTEST_SIMULATIONS=1000 python scripts/diagnostics/monte_carlo_backtest.py
```

Report-ready error diagnostics and baseline ladder:

```bash
python scripts/diagnostics/model_diagnostics_report.py
```

Seasonal extrapolation check:

```bash
python scripts/diagnostics/extrapolation_check.py
```

Next-year Monte Carlo projection:

```bash
MC_FUTURE_START=2026-05-16 MC_SIMULATIONS=1000 python scripts/diagnostics/monte_carlo_yearly_solar.py
```

Generated plot PNG files are ignored by git. Regenerate them locally when needed.

## Current Results

| Component | Main Result |
|-----------|-------------|
| Point forecast | R2 0.8599, nRMSE 9.02%, MAPE 36.10% |
| q10 lower bound | 89.07% actual coverage against 90% target |
| Monte Carlo backtest | p10-p90 interval coverage 79.85%; diagnostic only |
| MILP prototype | Representative sunny/cloudy/surplus days solve successfully |

See [Results](docs/results.md) for the full tables and interpretation.

## Repository Layout

```text
MDS_final/
├── README.md
├── requirements.txt
├── scripts/
│   ├── clean_renewable.py
│   ├── engineer_renewable_features.py
│   ├── train_xgboost_pipeline.py
│   ├── train_quantile_model.py
│   ├── milp_daily_schedule.py
│   └── diagnostics/
│       ├── monte_carlo_backtest.py
│       └── monte_carlo_yearly_solar.py
├── docs/
│   ├── methodology.md
│   ├── results.md
│   └── monte_carlo_note.md
└── model_results/
    ├── metrics.json
    ├── quantile_coverage.json
    ├── predictions_test.csv
    ├── predictions_quantile_q10.csv
    ├── milp_solar_forecast_hourly.csv
    ├── monte_carlo_backtest/
    └── monte_carlo_year/
```

## Output Policy

Tracked outputs are limited to compact CSV/JSON summaries that make the project reproducible and reviewable. Generated images, raw data, processed data, local packages, caches, and Python bytecode are ignored.

If a plot is needed for the report, regenerate it by running the corresponding script instead of committing the PNG artifact.

## Main Limitations

- Same-time weather variables are measured values used as proxies for forecast weather inputs, so true deployed day-ahead performance may be lower.
- The MILP currently uses a synthetic load profile.
- The current MILP is a single-day prototype; rolling multi-day optimization is the next step.
