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

## Baseline Ladder

The model comparison should be presented as a stepwise improvement rather than only comparing persistence and tuned XGBoost. This makes the design choices empirically grounded.

| Model | Validation or CV MAPE | Test MAPE | Test R2 | Test RMSE |
|-------|----------------------:|----------:|--------:|----------:|
| Persistence, previous-day same time | 123.62% | 94.51% | 0.3299 | 990.22 Wh |
| Linear regression, same feature list | 65.65% | 59.23% | 0.8124 | 523.86 Wh |
| XGBoost default | 41.71% | 39.26% | 0.8501 | 468.34 Wh |
| XGBoost tuned | 38.75% CV | 36.10% | 0.8599 | 452.82 Wh |

Interpretation:

- Persistence is weak because adjacent days often have very different cloud conditions.
- Linear regression already captures much of the weather-to-generation relationship, improving test MAPE from 94.51% to 59.23%.
- XGBoost improves strongly over linear regression, showing that nonlinear interactions and threshold effects matter.
- Optuna tuning gives a smaller but still useful improvement over default XGBoost.

The comparison is saved in `model_results/model_comparison.csv`.

## Seasonal Extrapolation Check

This diagnostic trains only on 2017 January-June and evaluates on 2017 July-December. It tests whether the model over-relies on seasonal patterns that it has already seen.

| Model | Test MAPE | Test R2 | Test RMSE | Test Bias |
|-------|----------:|--------:|----------:|----------:|
| Persistence, previous-day same time | 121.07% | 0.0430 | 1,106.33 Wh | -27.36 Wh |
| Linear regression | 83.56% | 0.7560 | 558.63 Wh | +64.19 Wh |
| XGBoost default | 48.17% | 0.7583 | 556.00 Wh | -9.79 Wh |
| XGBoost tuned fixed params | 46.07% | 0.7873 | 521.62 Wh | -5.33 Wh |

Monthly tuned XGBoost performance on the unseen half-year:

| Month | MAPE | MAE | Bias |
|------:|-----:|----:|-----:|
| 7 | 37.72% | 319.03 Wh | +24.38 Wh |
| 8 | 35.08% | 372.93 Wh | -45.83 Wh |
| 9 | 43.30% | 361.02 Wh | -25.48 Wh |
| 10 | 48.33% | 294.26 Wh | -12.83 Wh |
| 11 | 60.83% | 243.82 Wh | +6.65 Wh |
| 12 | 74.42% | 228.00 Wh | +41.74 Wh |

Interpretation:

- The extrapolation setting is intentionally harder than the main split because the model sees only half a year of training data.
- XGBoost performance drops relative to the main full-history test, but it does not collapse: tuned XGBoost still improves strongly over persistence and linear regression.
- The deterioration is largest in late autumn and winter, where generation is lower and percentage errors become more sensitive.
- This supports a cautious conclusion: the feature set has meaningful seasonal generalization, but a full-year training set is important for robust winter performance.

The extrapolation outputs are saved in `model_results/extrapolation_check_2017.csv` and `model_results/extrapolation_check_2017.json`.

## Error Structure Diagnostics

The tuned XGBoost model has mean MAPE 36.10%, but median APE is only 17.42%. This gap means the headline MAPE is driven by difficult subsets rather than uniform poor performance. Mean bias is +6.36 Wh and overprediction occurs on 53.15% of metric rows, so there is no large global bias.

### Error by Month

The highest MAPE months are February, November, January, September, May, and October.

| Month | MAPE | Median APE | MAE | Bias |
|------:|-----:|-----------:|----:|-----:|
| 2 | 50.51% | 25.60% | 236.52 Wh | +5.95 Wh |
| 11 | 48.19% | 30.99% | 150.64 Wh | +35.84 Wh |
| 1 | 44.28% | 21.36% | 158.06 Wh | -2.97 Wh |
| 9 | 40.25% | 19.09% | 277.72 Wh | +22.87 Wh |
| 5 | 39.12% | 17.23% | 316.70 Wh | +23.88 Wh |
| 10 | 38.08% | 20.55% | 272.95 Wh | -78.10 Wh |

Interpretation:

- Winter months have lower generation, so MAPE is more sensitive to small absolute deviations.
- Spring and autumn transition months are also difficult because cloud states change quickly.
- March and June perform better, suggesting the model is healthier when sunlight patterns are more stable.

### Error by Generation Level

| Target bin | Rows | MAPE | Median APE | Bias |
|------------|-----:|-----:|-----------:|-----:|
| 50-100 Wh | 1,462 | 52.00% | 22.92% | +41.58 Wh |
| 100-200 Wh | 2,138 | 57.01% | 25.45% | +62.86 Wh |
| 200-500 Wh | 3,516 | 51.36% | 23.13% | +117.23 Wh |
| 500-1000 Wh | 2,862 | 41.14% | 22.74% | +185.02 Wh |
| 1000-2000 Wh | 3,162 | 28.51% | 18.94% | +111.61 Wh |
| 2000-5000 Wh | 4,844 | 14.68% | 9.61% | -289.44 Wh |

Interpretation:

- The model is strongest when generation is high; the 2000-5000 Wh bin has only 14.68% MAPE.
- The weak area is low-to-mid generation, especially 100-500 Wh.
- This is exactly where cloudy or transition cases dominate and where percentage errors are most sensitive.

### High-Error Feature Pattern

The top 10% absolute-error rows have absolute error above 746 Wh.

| Feature diagnostic | All metric rows | High-error rows |
|--------------------|----------------:|----------------:|
| Mean `clouds_all` | 67.80 | 70.57 |
| Mean `ghi_roll_std_3h` | 17.98 | 25.57 |
| Mean lagged clear-sky index | 0.176 | 0.176 |

The high-error subset has much larger recent GHI variability. This supports the interpretation that the model struggles most during fast cloud transitions rather than during stable sunny periods.

Slice SHAP was also computed for the top-10% absolute-error rows. The most important high-error features are:

| Feature | High-error mean abs SHAP | Ratio vs all-row SHAP |
|---------|-------------------------:|----------------------:|
| `energy_delta_lag_1h` | 683.21 | 1.51x |
| `energy_roll_mean_3h` | 298.80 | 1.32x |
| `dni_clear_sky_wm2` | 236.08 | 1.35x |
| `hour_sin` | 169.82 | 1.09x |
| `ghi_clear_sky_wm2` | 165.13 | 1.55x |
| `ghi_roll_mean_3h` | 77.87 | 1.59x |
| `ghi_roll_std_3h` | 72.13 | 1.28x |
| `clouds_all` | 71.87 | 1.51x |
| `clear_sky_index_lag_1h` | 41.68 | 1.91x |

The SHAP pattern is consistent with the physical story: high-error predictions depend heavily on recent generation, recent irradiance variability, theoretical sun position, and cloud/weather variables. When the recent history suggests sunlight but the current cloud state collapses generation, the model can overpredict.

### Concrete Overprediction Cases

| Time | Actual | Prediction | Residual | Cloud | Weather type | Recent GHI std | Lagged energy |
|------|-------:|-----------:|---------:|------:|-------------:|---------------:|--------------:|
| 2022-05-26 11:00 | 180 Wh | 2,603 Wh | +2,423 Wh | 55 | 3 | 33.65 | 805 Wh |
| 2022-05-13 12:30 | 229 Wh | 2,341 Wh | +2,112 Wh | 71 | 3 | 32.68 | 1,933 Wh |
| 2021-08-22 08:30 | 2 Wh | 1,934 Wh | +1,932 Wh | 100 | 4 | 27.03 | 1,715 Wh |
| 2022-07-01 08:15 | 144 Wh | 2,071 Wh | +1,927 Wh | 95 | 4 | 34.31 | 2,029 Wh |

These are not random failures. They are cloudy or transition cases where lagged generation and theoretical irradiance still imply meaningful solar potential, but actual generation is suppressed by the current cloud state.

The full diagnostics are saved in `model_results/error_structure_diagnostics.json`.

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
