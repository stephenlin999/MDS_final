# Methodology

This project forecasts solar PV generation and uses the forecast in a battery dispatch optimizer. The main research backbone is:

```text
Raw data -> Cleaning -> Feature Engineering -> XGBoost/q10 Forecast -> MILP Dispatch
```

Monte Carlo simulations are intentionally treated as optional diagnostics. They are not the primary modeling method.

## 1. Data Cleaning

Input: `Renewable.csv`

Output: `Renewable_cleaned.csv`

Cleaning steps:

- Clip physically impossible values:
  - negative radiation to zero
  - humidity above 100% to 100%
  - negative wind speed treated as invalid
- Validate timestamp continuity.
- Fill missing weather values using time-aware interpolation or calendar-hour averages instead of yearly means.
- Preserve true weather extremes when physically plausible.

## 2. Feature Engineering

Input: `Renewable_cleaned.csv`

Output: `Renewable_featured.csv`

Feature groups:

- Astronomical features from `pvlib`:
  - solar elevation
  - solar zenith
  - solar azimuth
  - theoretical clear-sky irradiance
  - top-of-atmosphere horizontal irradiance
- Cyclic time encodings:
  - hour sin/cos
  - weekday sin/cos
  - month sin/cos
  - season
  - weekend flag
- Weather and historical features:
  - temperature, pressure, humidity, wind, rain, snow, cloud proxy
  - GHI lags
  - energy lags
  - rolling means and rolling standard deviation
  - lagged clear-sky index

All lag and rolling features are shifted so that they use only information available before the prediction timestamp.

## 3. Forecast Model

The primary model is forecast-strict XGBoost.

The primary feature list excludes same-time measured irradiance features that would leak future information:

- same-time `GHI`
- same-time `clear_sky_index`
- same-time `cloud_cover_proxy`
- same-time GHI/CSI interaction terms

This keeps the model aligned with the day-ahead/MILP setting. Same-time weather variables are retained only as a proxy for forecast weather inputs, and this limitation is stated in the report.

## 4. Evaluation Design

The split is chronological:

- first 80%: development set
- last 20%: final test set
- validation is carved out from the development set

The test set is opened only at the end for final evaluation.

Primary MAPE mask:

```text
solar_elevation_deg > 0 and Energy delta[Wh] > 0
```

MAPE denominator:

```text
max(y_true, 100 Wh)
```

This prevents dawn/dusk tiny denominators from dominating the metric.

## 5. Quantile Forecast

The q10 model estimates a conservative lower-bound solar forecast using XGBoost quantile regression.

Purpose:

- reduce over-optimistic solar assumptions
- provide a safer forecast input for MILP dispatch
- support conservative scheduling under uncertainty

The q10 model reuses the tuned point-forecast hyperparameters to avoid overfitting the quantile coverage on the test set.

## 6. MILP Dispatch

The MILP optimizer schedules battery charge/discharge using the solar forecast.

Core constraints:

- charge/discharge mutual exclusion via Big-M binary mode
- battery state-of-charge dynamics
- charge/discharge power limits
- terminal SOC lower bound
- over-contract grid draw penalty

The current implementation is a single-day prototype using a synthetic load profile.
