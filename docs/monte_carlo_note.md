# Monte Carlo Positioning

Monte Carlo is not the main research backbone in this project.

The main modeling flow remains:

```text
Feature engineering -> XGBoost/q10 forecast -> MILP dispatch
```

Monte Carlo is added only as an auxiliary robustness check. Its purpose is to help judge whether the forecast and conservative lower bound are too optimistic under uncertain sunlight conditions.

## What Monte Carlo Does Here

The Monte Carlo scripts sample historical analogue days with similar day-of-year values. Those sampled days create many plausible solar-generation scenarios.

This helps answer:

- Does the q10 conservative forecast stay safely below actual generation often enough?
- Does the uncertainty interval cover actual outcomes at a reasonable rate?
- Is the forecast distribution unrealistically optimistic?
- How wide might the future annual solar-generation range be?

## What Monte Carlo Does Not Do

Monte Carlo does not replace the trained model.

It should not be described as:

- the main forecast model
- the main validation method
- a way to directly prove daily point prediction accuracy
- the input that directly drives MILP in the current main pipeline

The Monte Carlo mean is not reliable as a daily point forecast in the current implementation. The backtest showed high daily MAPE for the Monte Carlo mean, while its p10-p90 interval was well calibrated.

## Recommended Report Wording

Use wording like this:

> Monte Carlo simulation is used as an auxiliary robustness check to examine whether the solar forecast is overly optimistic under uncertain sunlight conditions. It is not the main modeling method; the main predictive model remains the forecast-strict XGBoost/q10 pipeline.

Or in plainer wording:

> XGBoost gives the main point prediction, q10 gives a conservative lower bound for scheduling, and Monte Carlo helps us inspect uncertainty and optimism risk.

## Practical Takeaway

For the current project:

- use XGBoost tuned predictions for point forecast evaluation
- use q10 predictions for conservative MILP experiments
- use Monte Carlo outputs as diagnostic evidence in the report
- do not optimize or select the model based on Monte Carlo results
