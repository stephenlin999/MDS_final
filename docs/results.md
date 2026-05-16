# Results

This file keeps the main numerical results separate from the project README.

## Point Forecast

Final test period: 2021-07-14 to 2022-08-31

Current chronological split:

- Full featured data range after warm-up filtering: 2017-01-02 to 2022-08-31
- Train: 2017-01-02 to 2020-08-17
- Validation: 2020-08-17 to 2021-07-14
- Development set, train plus validation: 2017-01-02 to 2021-07-14
- Final test: 2021-07-14 to 2022-08-31

The metrics below are the canonical numbers for the current multi-year split. Earlier interim numbers were produced under different evaluation windows or settings and should not be compared directly.

| Metric | Value |
|--------|------:|
| Mean MAPE | 36.10% |
| Median APE | 17.42% |
| R2 | 0.8599 |
| RMSE | 452.82 Wh |
| MAE | 261.50 Wh |
| nRMSE, observed capacity | 9.02% |
| Bias | +6.36 Wh |

Interpretation:

- MAPE is inflated by low-generation dawn/dusk and cloudy-transition periods.
- Median APE is roughly half of mean MAPE, confirming that the headline percentage error is driven by a difficult tail of cloudy or transition cases rather than systemic underperformance.
- R2 and nRMSE show that the model is usable as a point forecast.
- The model should still be treated as an optimistic proxy for true day-ahead deployment because same-time measured weather variables are used as forecast-weather proxies.

## Baseline Ladder

The model comparison should be presented as a stepwise improvement rather than only comparing persistence and tuned XGBoost. This makes the design choices empirically grounded.

This table is also based on the current canonical multi-year split above. The persistence baseline changed across earlier drafts because the test window and pipeline settings changed during debugging; the 94.51% value below is the current final-test baseline.

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

The comparison is saved in `model_results/reports/model_comparison.csv`.

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

The extrapolation outputs are saved in `model_results/reports/extrapolation_check_2017.csv` and `model_results/reports/extrapolation_check_2017.json`.

## Overfitting and Full-Range Distribution Shift

This check uses the full available date range in `Renewable_featured.csv`: 2017-01 to 2022-08. The tuned XGBoost model is retrained on the development set and evaluated across train, validation, dev, and final test.

| Split | MAPE | R2 | RMSE | MAE |
|-------|-----:|---:|-----:|----:|
| Train | 26.17% | 0.9481 | 285.95 Wh | 174.35 Wh |
| Validation | 28.72% | 0.9367 | 296.87 Wh | 179.24 Wh |
| Dev fit set | 26.66% | 0.9462 | 288.08 Wh | 175.29 Wh |
| Final test | 36.10% | 0.8599 | 452.82 Wh | 261.50 Wh |

Overfitting interpretation:

- Dev-to-test R2 gap is 0.086.
- Test MAPE is 9.44 percentage points higher than dev MAPE.
- Test RMSE is 164.74 Wh higher than dev RMSE.
- This is a visible generalization gap, but not a collapse. It is consistent with moderate model complexity plus distribution shift, not severe overfitting.

Full-date-range calendar-month averages show the seasonal pattern:

| Calendar month | Mean MAPE | Mean R2 | Mean actual generation | Mean cloud cover | Mean solar elevation |
|---------------:|----------:|--------:|-----------------------:|-----------------:|---------------------:|
| 1 | 35.25% | 0.890 | 452.95 Wh | 78.29 | 10.78 deg |
| 2 | 34.98% | 0.929 | 973.04 Wh | 71.79 | 15.58 deg |
| 3 | 29.89% | 0.929 | 1,318.03 Wh | 65.04 | 22.09 deg |
| 4 | 24.31% | 0.924 | 1,514.31 Wh | 55.15 | 28.18 deg |
| 5 | 24.78% | 0.930 | 1,396.75 Wh | 61.21 | 32.26 deg |
| 6 | 20.05% | 0.951 | 1,381.45 Wh | 58.16 | 33.92 deg |
| 7 | 25.54% | 0.902 | 1,242.60 Wh | 62.84 | 33.18 deg |
| 8 | 27.91% | 0.896 | 1,372.15 Wh | 60.14 | 29.97 deg |
| 9 | 30.86% | 0.912 | 1,259.87 Wh | 67.29 | 24.49 deg |
| 10 | 37.29% | 0.874 | 984.53 Wh | 70.70 | 17.90 deg |
| 11 | 38.50% | 0.861 | 478.60 Wh | 81.18 | 12.13 deg |
| 12 | 35.83% | 0.784 | 337.26 Wh | 83.46 | 9.11 deg |

Distribution-shift interpretation:

- The weakest calendar months are late autumn and winter, especially October-December and January.
- December has the lowest average R2, matching the physical setting: low solar elevation, short daylight, high cloud cover, and low actual generation.
- The final test set includes all seasons from 2021-07 to 2022-08, so the issue is not that the test set is only winter. The issue is that winter-like months remain systematically harder across the full date range.
- The practical report conclusion should be cautious: the model is not severely overfitted, but winter and cloudy low-generation regimes are distribution-shift-sensitive. For MILP, q10 lower-bound predictions are especially important in these months.

The diagnostics are saved in `model_results/reports/overfitting_shift_diagnostics.json`, `model_results/reports/test_monthly_shift_metrics.csv`, and `model_results/reports/full_range_monthly_shift_metrics.csv`.

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

The full diagnostics are saved in `model_results/reports/error_structure_diagnostics.json`.

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

This is an auxiliary diagnostic, not the main research method. The Monte Carlo method is evaluated by calibration, not by point-forecast accuracy: its purpose is to produce uncertainty intervals around plausible sunlight scenarios. The correct headline metric is p10-p90 interval coverage, while the Monte Carlo mean MAPE is reported only as a negative control showing that the analogue mean should not be used as a daily point forecast.

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
| Monte Carlo p10-p90 coverage | 79.85% | Main MC metric; well calibrated versus nominal 80% |
| Monte Carlo mean daily MAPE, negative control | 131.86% | Documents that the MC mean is intentionally not a daily point forecast |

Interpretation:

- Use XGBoost for point prediction.
- Use q10 for conservative MILP scheduling.
- Use Monte Carlo for uncertainty and risk bands, not as the daily point forecast.
- The Monte Carlo mean MAPE should not be compared against XGBoost point-forecast MAPE as a model-selection metric; that would evaluate the wrong object.

### Supplementary Annual Analogue Scenario

This annual scenario is intentionally a secondary output. It is not a meteorological forecast of the next year. It only shows the annual total implied by the analogue sampling assumption, where future sunlight patterns are sampled from historical day-of-year analogues.

Projection setup: 2026-05-16 start, 365 days, 1,000 simulations, +/- 21 day-of-year analogue window.

| Forecast | Annual Mean | Annual P10 | Annual P50 | Annual P90 |
|----------|------------:|-----------:|-----------:|-----------:|
| Point forecast | 19,463.6 kWh | 18,791.2 kWh | 19,460.5 kWh | 20,162.0 kWh |
| Q10 conservative | 12,305.3 kWh | 11,676.1 kWh | 12,299.0 kWh | 12,945.4 kWh |

Interpretation:

- The narrow p10-p90 range is not a claim that true year-ahead weather uncertainty is only about this wide.
- Annual aggregation smooths day-level variability, and the analogue method assumes historical seasonal patterns remain representative.
- Treat this as a planning-scale scenario summary, not as a core research result or a guaranteed future-generation interval.

## Downstream MILP Integration Test

This section documents prototype testing done to verify that the forecast module outputs can be consumed by downstream optimization. The full MILP design, penalty tuning, and operational interpretation belong to the optimization workstream.

| Date | Scenario | Over-contract | End SOC | Status |
|------|----------|--------------:|--------:|--------|
| 2022-06-03 | Sunny | 0 Wh | 15,000 Wh | PASS |
| 2021-12-04 | Cloudy | 12,750 Wh | 15,000 Wh | PASS |
| 2022-03-14 | Solar surplus | 0 Wh | 15,000 Wh | PASS |

Interpretation:

- The forecast handoff file is compatible with the single-day MILP prototype.
- The cloudy-day case showed 12,750 Wh over-contract, suggesting that downstream penalty coefficients and conservative scheduling rules still need calibration by the optimization workstream.
- A rolling multi-day MILP backtest belongs to the optimization workstream after the forecast handoff format is fixed.
