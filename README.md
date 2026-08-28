# Solar Power Forecasting

This project forecasts solar PV generation and uses the forecast to schedule a battery storage system with Mixed-Integer Linear Programming (MILP).

The main research backbone is intentionally simple:

```text
Raw data -> Cleaning -> Feature Engineering -> XGBoost/q10 Forecast -> MILP Dispatch
```

Monte Carlo simulation is included only as an optional diagnostic. It is used to check whether the forecast and q10 conservative lower bound are too optimistic under uncertain sunlight scenarios; it is not the main modeling method.

## P-Robust EMS Optimization

The `robust_ems/` package adds a scenario-based P-robust dispatch study without changing the legacy Gurobi EMS. It builds paired load/PV residual paths from complete historical days, reduces them to representative medoids, solves one perfect-information oracle per scenario, and then limits every scenario's relative cost regret while minimizing probability-weighted expected cost.

The model uses 15-minute battery physics, one hour of non-anticipative charge/discharge commands, scenario-specific recourse afterward, exact two-band monthly excess charges, and an hourly rolling backtest mode. It uses Pyomo with the open-source HiGHS solver, so it is not subject to the existing restricted Gurobi model-size limit. Study runs use a tight MIP gap so the price-of-robustness curve is numerically meaningful.

```bash
python -m robust_ems.cli --date 2018-12-15 --scenarios 10
python -m robust_ems.cli --date 2018-12-15 --scenarios 10 --p 0.15 --rolling
```

Reports are written to `model_results/robust/`. The existing EMS output path defaults to `/Users/stephenlin/Downloads/mds-final` and can be changed with `--ems-root`.

The first S=10 rolling smoke test is deliberately reported as a failed out-of-sample validation: no solver fallback occurred, but the safety-projection rate was 4.17% and ex-post regret was 48.65% for p=0.15. Only 13 eligible paired residual days were available. The implementation is therefore ready for scenario-set research, not for a claim that the selected p currently controls unseen-day regret.

## Documentation

- [Methodology](docs/methodology.md): cleaning, feature engineering, model design, leakage control, evaluation, q10, and MILP formulation.
- [Results](docs/results.md): point forecast, q10 coverage, Monte Carlo calibration, supplementary annual scenario, and downstream MILP handoff checks.
- [Monte Carlo Positioning](docs/monte_carlo_note.md): how to describe Monte Carlo correctly in the report.

## React EMS Dashboard

The primary dashboard showcase now lives in [`react-dashboard/`](react-dashboard/). It is a runnable React/Vite app with Recharts and Tailwind, designed for both executive savings review and engineering drill-down.

The dashboard reads existing EMS/model outputs and converts them into local frontend JSON. The overview uses a direct two-bar comparison between "without system" and "with MILP system" monthly cost. The decision-explanation page covers all 12 months: July and December use complete existing EMS output, while the other months use Monte Carlo-calibrated future scenario days sampled from the annual solar projection.

```bash
cd react-dashboard
npm install
npm run build:data
npm run dev -- --port 5173
```

Then open:

```text
http://localhost:5173/
```

The older Streamlit audit dashboard remains in [`dashboard/`](dashboard/) for quick data checks and controlled local scenario reruns.

Important scope note: the React dashboard is a presentation and review prototype. It does not call a backend or re-solve MILP in the browser. The scenario sliders use a simplified instant estimate; full reruns still belong to the Streamlit/local CLI workflow unless a backend API is added later.

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

Overfitting and full-range distribution-shift check:

```bash
python scripts/diagnostics/overfitting_shift_check.py
```

Seasonal extrapolation check:

```bash
python scripts/diagnostics/extrapolation_check.py
```

Supplementary annual analogue scenario:

```bash
MC_FUTURE_START=2026-05-16 MC_SIMULATIONS=1000 python scripts/diagnostics/monte_carlo_yearly_solar.py
```

Generated plot PNG files are ignored by git. Regenerate them locally when needed.

## For Optimization Teammates

The native 15-minute handoff file for MILP is:

```text
model_results/forecast/milp_solar_forecast_15min.csv
```

If the optimizer stays hourly, use:

```text
model_results/forecast/milp_solar_forecast_hourly.csv
```

Use `solar_q10_wh` for conservative scheduling and `solar_point_wh` for the point forecast.

## Current Results

| Component | Main Result |
|-----------|-------------|
| Point forecast | R2 0.8599, nRMSE 9.02%, mean MAPE 36.10%, median APE 17.42% |
| q10 lower bound | 89.07% actual coverage against 90% target |
| Monte Carlo backtest | p10-p90 interval coverage 79.85%; calibration diagnostic only |
| MILP handoff check | Forecast output is consumable by single-day MILP; optimization tuning remains downstream |

See [Results](docs/results.md) for the full tables and interpretation.

## Repository Layout

```text
MDS_final/
├── README.md
├── requirements.txt
├── react-dashboard/
│   ├── src/
│   └── scripts/
├── robust_ems/
│   ├── scenarios.py       # leakage-safe paired residual scenarios
│   ├── model.py           # Pyomo/HiGHS P-robust MILP
│   └── cli.py             # p scan and hourly rolling backtest
├── dashboard/
│   └── Streamlit EMS audit dashboard
├── scripts/
│   ├── clean_renewable.py
│   ├── engineer_renewable_features.py
│   ├── train_xgboost_pipeline.py
│   ├── train_quantile_model.py
│   ├── milp_daily_schedule.py
│   └── diagnostics/
│       ├── model_diagnostics_report.py
│       ├── overfitting_shift_check.py
│       ├── extrapolation_check.py
│       ├── monte_carlo_backtest.py
│       └── monte_carlo_yearly_solar.py
├── docs/
│   ├── methodology.md
│   ├── results.md
│   └── monte_carlo_note.md
└── model_results/
    ├── README.md
    ├── forecast/
    │   ├── predictions_test.csv
    │   ├── predictions_quantile_q10.csv
    │   ├── milp_solar_forecast_15min.csv
    │   └── milp_solar_forecast_hourly.csv
    ├── milp/
    │   ├── schedules/
    │   └── summaries/
    ├── reports/
    │   ├── metrics.json
    │   ├── quantile_coverage.json
    │   └── *.csv / *.json diagnostics
    ├── monte_carlo/
    │   ├── backtest/
    │   └── yearly_projection/
    ├── robust/             # P-robust scans and rolling validation
    └── plots/              # ignored by git
```

## Output Policy

Tracked outputs are limited to compact CSV/JSON summaries that make the project reproducible and reviewable. Generated images, raw data, processed data, local packages, caches, and Python bytecode are ignored.

If a plot is needed for the report, regenerate it by running the corresponding script instead of committing the PNG artifact.

## Main Limitations

- Same-time weather variables are measured values used as proxies for forecast weather inputs, so true deployed day-ahead performance may be lower.
- The MILP currently uses a synthetic load profile.
- MILP design, penalty calibration, and rolling multi-day optimization belong to the downstream optimization workstream.
