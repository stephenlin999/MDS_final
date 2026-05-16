# Results

This file keeps the main numerical results separate from the project README.

## Point Forecast

Final test period: 2021-07-14 to 2022-08-31

| Metric | Value |
|--------|------:|
| MAPE | 36.10% |
| R2 | 0.8599 |
| RMSE | 452.82 Wh |
| MAE | 261.50 Wh |
| nRMSE, observed capacity | 9.02% |
| Bias | +6.36 Wh |

Interpretation:

- MAPE is inflated by low-generation dawn/dusk and cloudy-transition periods.
- R2 and nRMSE show that the model is usable as a point forecast.
- The model should still be treated as an optimistic proxy for true day-ahead deployment because same-time measured weather variables are used as forecast-weather proxies.

## Quantile Lower Bound

The q10 model is evaluated on daylight rows only.

| Metric | Value |
|--------|------:|
| Target coverage | 90% |
| Actual coverage | 89.07% |
| Mean gap, q10 - actual | -444 Wh |

Interpretation:

- The q10 model is close to its intended coverage target.
- It is suitable as the safer forecast input for MILP experiments.

## Monte Carlo Backtest

This is an auxiliary diagnostic, not the main research method.

Backtest setup:

- test days: 412 complete days
- period: 2021-07-15 to 2022-08-30
- simulations: 1,000 per test day
- analogue pool: development period only
- analogue window: +/- 21 day-of-year days

| Backtest Item | Value | Interpretation |
|---------------|------:|----------------|
| Direct model daily MAPE | 17.00% | Daily point forecast is strong |
| Direct model daily R2 | 0.9785 | Very strong daily fit |
| Direct model daily RMSE | 5,609 Wh | Daily-scale error magnitude |
| Direct model total bias | +1.42% | Total generation is only slightly overpredicted |
| Direct q10 daily coverage | 98.06% | Conservative forecast is safely below actual most days |
| Monte Carlo mean daily MAPE | 131.86% | Analogue MC mean is not a good daily point forecast |
| Monte Carlo p10-p90 coverage | 79.85% | Uncertainty interval is well calibrated versus nominal 80% |

Interpretation:

- Use XGBoost for point prediction.
- Use q10 for conservative MILP scheduling.
- Use Monte Carlo for uncertainty/risk bands, not as the daily point forecast.

## Monte Carlo Year Projection

Projection period:

- start: 2026-05-16
- duration: 365 days
- simulations: 1,000
- analogue window: +/- 21 day-of-year days

| Forecast | Annual Mean | Annual P10 | Annual P50 | Annual P90 |
|----------|------------:|-----------:|-----------:|-----------:|
| Point forecast | 19,463.6 kWh | 18,791.2 kWh | 19,460.5 kWh | 20,162.0 kWh |
| Q10 conservative | 12,305.3 kWh | 11,676.1 kWh | 12,299.0 kWh | 12,945.4 kWh |

Interpretation:

- This projection is a planning scenario, not a meteorological forecast.
- It should be used to understand annual uncertainty, not to assert an exact future generation total.

## MILP Single-Day Prototype

| Date | Scenario | Over-contract | End SOC | Status |
|------|----------|--------------:|--------:|--------|
| 2022-06-03 | Sunny | 0 Wh | 15,000 Wh | PASS |
| 2021-12-04 | Cloudy | 12,750 Wh | 15,000 Wh | PASS |
| 2022-03-14 | Solar surplus | 0 Wh | 15,000 Wh | PASS |

Interpretation:

- The optimizer satisfies battery constraints on representative days.
- A rolling multi-day MILP backtest is the next modeling step.
