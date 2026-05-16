# Model Results Layout

This folder keeps generated model outputs grouped by purpose, so optimization work can find the right files quickly.

## Forecast Handoff

Use this file for MILP integration:

```text
forecast/milp_solar_forecast_hourly.csv
```

Important columns:

- `solar_point_wh`: point forecast from the tuned XGBoost model.
- `solar_q10_wh`: conservative q10 lower-bound forecast. Prefer this for safer MILP scheduling.

## Subfolders

| Folder | Contents |
|--------|----------|
| `forecast/` | Test predictions, q10 predictions, and the hourly MILP-ready solar forecast. |
| `reports/` | Compact CSV/JSON metrics, model comparisons, SHAP importance, and diagnostics. |
| `milp/schedules/` | Daily MILP decision schedules. |
| `milp/summaries/` | Daily MILP status and constraint summaries. |
| `monte_carlo/backtest/` | Monte Carlo backtest tables and summary JSON. |
| `monte_carlo/yearly_projection/` | One-year Monte Carlo scenario outputs. |
| `plots/` | Generated PNG figures. These are ignored by git and can be regenerated locally. |

## Notes

- Raw and processed datasets are intentionally not stored here.
- PNG plots and matplotlib cache files are generated artifacts, not source-of-truth results.
- The main report interpretation lives in `docs/results.md`.
