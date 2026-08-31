# P-Robust EMS Dashboard Handoff

## Project Summary

`react-dashboard/` is the primary owner and engineering presentation surface for the factory EMS project. It compares full grid purchase, PV self-consumption, deterministic MILP, and P-Robust MILP using one formal annual planning simulation. Owners see annual cost, savings, and downside exposure first. Engineers can inspect solved p points, monthly costs, 15-minute dispatch, scenario envelopes, billing components, solver metadata, and validation limitations.

The legacy Streamlit dashboard remains separate. This React app does not call it and does not rerun optimization in the browser.

## Architecture And Stack

- React 19, Vite 7, Recharts 3, Tailwind CSS 3
- Radix Tabs and Slider through local shadcn-style components
- Lucide icons
- Python 3.13, Pyomo, HiGHS, NumPy, pandas, and scikit-learn for annual data generation
- Local JSON import only; no runtime API, fetch, CDN, or external font

```text
react-dashboard/
├── README.md                         # Build, data, and validation instructions
├── HANDOFF.md                        # This continuation brief
├── package.json                      # Dashboard and proposal commands
├── index.html                        # Main dashboard entry
├── proposal.html                     # Proposal build entry
├── vite.config.js                    # Main Vite build
├── vite.proposal.config.js           # Single-entry proposal bundle
├── exports/
│   └── ems-robust-client-proposal.html  # Fully offline deliverable
├── scripts/
│   ├── build-data.mjs                # Formal result validation and copy
│   └── build-proposal.mjs            # Vite build plus JS/CSS inlining
└── src/
    ├── App.jsx
    ├── main.jsx
    ├── dashboard.jsx                 # Four-tab product dashboard
    ├── proposal-main.jsx
    ├── proposal.jsx                  # Six-section client story
    ├── proposal.css
    ├── index.css                     # Shared tokens and chart overflow rules
    ├── data/ems-dashboard-data.json  # Generated formal presentation data
    └── components/ui/                # Local UI primitives

robust_ems/annual_plan.py              # Formal annual simulator and data writer
model_results/robust/annual_planning/  # Versioned formal outputs
```

## Data Contract

The sole UI source is `model_results/robust/annual_planning/presentation.json`:

- `meta`: run ID, status, tariff, seed, scenario counts, solver, source limitations
- `executiveSummary`: annual costs, robust savings, robust premium, downside reduction
- `strategyComparison`: annual, P50, P90, worst cost, events, peak, PV utilization
- `monthlyComparison`: 12 monthly strategy records
- `robustnessFrontier`: solved p points only; no browser interpolation
- `scenarioCoverage`: envelope, p calibration, solve time, and ex-post regret evidence
- `dailyDispatch`: three representative days per month, 96 intervals per day
- `billingBreakdown`: energy, basic, excess, and degradation cost
- `modelAssumptions`: battery, contracts, decision structure, and data limitations

`scripts/build-data.mjs` fails closed when the source is missing or invalid. Do not reintroduce mock fallback logic.

## Design System

- Graphite `#18201C`: primary text and inverted evidence sections
- Project green `#2D7D46`: savings, P-Robust, and positive status
- Alert red `#C0392B`: full-grid cost, over-contract exposure, failed validation
- SOC blue `#1B4F72`
- Neutral gray `#9CA3AF`
- Background `#F8FAF9`, cards white, border `#D9E0DC`
- System UI fonts only; tabular numerals for metrics
- Card radius is at most 8 px
- Stable chart heights, `min-width: 0`, and overflow-visible Recharts tooltips
- No persistent floating, pulsing, scale, glow-orb, or background animation

## Current State

Implemented and working:

- Formal 1,000-draw, 10-scenario, 365-day annual simulation
- Four owner strategies and 12-month comparison
- Daily two-stage P-Robust dispatch with one-hour non-anticipativity
- P calibration, solved robustness frontier, paired stress envelope, and daily ex-post regret calculation
- React tabs: Decision Overview, Robust Strategy, Daily Dispatch, Model Evidence
- Month and representative-day synchronization
- Deterministic/P-Robust dispatch switch, series toggles, scenario band, and floating tooltips
- Six-section client proposal with Executive/Technical mode, solved-point p slider, ROI input, and offline charts
- Fail-closed data build and fully inlined proposal build

## Known Issues

1. **Critical scientific limitation:** daily ex-post regret coverage does not currently support a hard P-Robust guarantee. Keep the failed/passed result visible. The annual cost and downside results remain planning-simulation evidence, not a future guarantee.
2. **High:** the annual scenario envelope is an in-sample planning-path check. It must not be described as independent coverage.
3. **High:** load and PV are calendar-aligned cross-year analogues because a same-year joint history is unavailable. This weakens causal and out-of-sample claims.
4. **Moderate:** the recourse policy selects a full-day analogue branch after one observed hour. A production controller should re-optimize on a rolling horizon instead of assuming that branch remains correct.
5. **Moderate:** the solved p frontier can be nearly flat because p constraints are non-binding over the requested grid. Do not invent variation for presentation.
6. **Minor:** importing full dispatch JSON produces a large initial bundle. The local and offline use case tolerates it; hosted production should split data by month.

## Next Steps

1. Rebuild scenario generation with a genuinely held-out joint load/PV validation period, then recalibrate p against daily ex-post regret.
2. Compare the current branch policy with hourly rolling re-optimization, recording runtime and regret improvement before changing the production claim.
3. Add an explicit model-validation state separate from solver/data-build status if this moves beyond proposal use.
4. Split dashboard data by month for hosted deployment while keeping the proposal export fully inlined.
5. Add Playwright screenshot and interaction regression tests for the four required viewport sizes.

## Constraints And Conventions

- Keep UI text free of the historical source year; display months as `1月` through `12月`.
- Keep `全年規劃模擬，非未來節費保證` visible.
- Never substitute mock data when formal output is missing or invalid.
- Never interpolate p results or imply that a slider reruns MILP.
- Preserve the distinction between pipeline status, in-sample envelope coverage, and out-of-sample regret validation.
- Do not modify the external EMS source project from the React build.
- Keep charts responsive, fixed-height, hoverable, and free of layout-changing animation.

## Suggested First Action

Create a held-out replay experiment that uses one month only: build scenarios from dates strictly before the replay month, execute the current one-hour branch policy on each replay day, and compare daily ex-post regret against hourly rolling re-optimization. Record p50/p90/p95 regret, coverage at each solved p, event count, and median/P95 runtime. This directly tests the most important unresolved claim without redesigning the UI first.
