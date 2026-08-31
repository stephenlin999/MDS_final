# P-Robust EMS Dashboard

This React application presents annual factory energy-planning results for four strategies: full grid purchase, PV self-consumption, deterministic MILP, and two-stage P-Robust MILP. The first screen is owner-facing; dispatch, scenario, billing, and validation evidence remain available in the lower tabs.

The UI never creates fallback numbers. It only builds from a formal annual result with `meta.status: "valid"`.

## Stack

- React 19 and Vite 7
- Recharts 3
- Tailwind CSS 3
- Local shadcn-style Card, Badge, Tabs, Slider, Button, and Input components
- Radix Tabs and Slider
- Lucide icons
- Imported local JSON; no runtime API or network request

## Build The Formal Annual Result

The annual planner requires Python 3.13, Pyomo, HiGHS, NumPy, pandas, and scikit-learn. From the repository root:

```bash
PYTHONPATH=.python_packages /opt/homebrew/bin/python3.13 -m robust_ems.annual_plan \
  --draws 1000 \
  --scenarios 10 \
  --days 365 \
  --output-dir model_results/robust/annual_planning
```

The planner writes:

```text
model_results/robust/annual_planning/
├── presentation.json
├── summary.json
├── comparison.json
├── scenario_metadata.json
├── p_calibration.json
├── monthly_metrics.csv
└── daily_dispatch.csv
```

`presentation.json` is the single UI data contract. It contains `meta`, `executiveSummary`, `strategyComparison`, `monthlyComparison`, `robustnessFrontier`, `scenarioCoverage`, `dailyDispatch`, `billingBreakdown`, and `modelAssumptions`.

## Run The React Dashboard

```bash
cd /Users/stephenlin/Downloads/MDS_final/react-dashboard
npm install
npm run build:data
npm run dev -- --port 5173
```

Open `http://localhost:5173/`.

`npm run build:data` validates the formal result and copies it to `src/data/ems-dashboard-data.json`. It fails when the source is missing, invalid, incomplete, lacks 12 months, or lacks representative dispatch days. It never substitutes mock data.

Production build:

```bash
npm run build
```

## Offline Client Proposal

Create the self-contained proposal file with:

```bash
npm run build:proposal
```

Output:

```text
exports/ems-robust-client-proposal.html
```

The export inlines React, Recharts, CSS, and formal annual data. It uses system fonts and has no CDN, server, API, or external font dependency. Open it directly with `file://`; charts, tooltips, month/day selectors, solved-point p slider, Executive/Technical switch, and ROI calculator remain interactive offline.

## Model And Evidence Boundary

The planner uses 1,000 paired seven-day bootstrap paths, reduces them to eight optimization medoids, and retains two paired stress envelopes for coverage checks. The first hour of battery decisions is non-anticipative. The rest of the day follows the closest paired scenario branch selected from observed first-hour load and PV.

The UI distinguishes two validation concepts:

- Planning-path envelope coverage is an in-sample scenario-set check.
- Daily ex-post regret coverage compares the dispatched policy with a same-state perfect-information oracle on the settlement path.

The latter is the scientifically relevant warning for P-Robust claims. A valid data build means the simulation and solver pipeline completed; it does not mean out-of-sample regret passed. The Technical view must retain that distinction.

The load and PV records are calendar-aligned cross-year analogues because same-year PV records are unavailable. This limitation, tariff version, seed, run ID, solver, SOC bounds, and simulation status are embedded in the formal data and shown in Technical mode.

**Required client wording:** `全年規劃模擬，非未來節費保證`.
