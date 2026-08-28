# EMS Dashboard Handoff

## Current Direction

The primary visual dashboard has moved to `../react-dashboard/`. That app is a runnable React/Vite dashboard with Tailwind, Recharts, local shadcn-style components, and generated local JSON from the existing EMS outputs. Use `../react-dashboard/HANDOFF.md` for the current frontend handoff.

This `dashboard/` folder is now the legacy Streamlit audit dashboard. Keep it for quick inspection, Plotly-based debugging, and controlled CLI scenario reruns through `ems_run.py`; do not treat it as the main presentation UI.

## Project Summary

This project is an independent Streamlit dashboard for auditing an EMS MILP dispatch workflow. It reads existing EMS outputs from `/Users/stephenlin/Downloads/mds-final/output`, compares Advanced EMS against B1-B5 baselines, visualizes dispatch behavior, explains MILP objective terms and energy flows, surfaces risk checks, and supports controlled scenario reruns through the original `ems_run.py` CLI.

The intended users are project teammates, reviewers, and presentation/defense audiences who need to understand why the battery charges or discharges, whether contract capacity is exceeded, whether SOC behavior is reasonable, and how the optimized EMS compares with baseline strategies.

## Tech Stack

- Python: 3.13 via `/Users/stephenlin/Downloads/MDS_final/dashboard/.venv`
- Streamlit: 1.58.0
- Plotly: 6.7.0
- pandas: 3.0.3
- EMS solver/runtime dependencies installed in the same dashboard venv:
  - gurobipy: 13.0.2
  - xgboost: 3.2.0
- Source EMS engine: `/Users/stephenlin/Downloads/mds-final/ems_run.py`
- Dashboard source root: `/Users/stephenlin/Downloads/MDS_final/dashboard`

## File Structure

```text
dashboard/
├── .gitignore
│   └── Ignores scenario_runs/, .streamlit/, .venv/, __pycache__, and *.pyc.
├── README.md
│   └── Startup instructions and dashboard purpose.
├── HANDOFF.md
│   └── This review and continuation brief.
├── app.py
│   └── Streamlit entry point. Defines sidebar source controls, four dashboard views, KPI sections, scenario rerun form, and page composition.
├── charts.py
│   └── Plotly chart builders for cost stacks, metric bars, dispatch time series, objective terms, energy flow, forecast/actual, and peak tracking.
├── data_loader.py
│   └── CSV/JSON loading, source path construction, schema normalization, risk summaries, scenario run discovery, and missing-file errors.
├── requirements.txt
│   └── Dashboard-only Python dependencies: streamlit, plotly, pandas.
├── scenario_runner.py
│   └── Builds and runs subprocess calls to EMS `ems_run.py`, writes scenario metadata, and redirects Matplotlib/cache output into scenario run folders.
├── scenario_runs/
│   └── Generated and ignored. Contains rerun outputs and run_meta.json files. One verified successful run exists: 20260529_144147_4444c3c0.
├── .venv/
│   └── Generated and ignored local virtual environment.
└── __pycache__/
    └── Generated and ignored Python bytecode.
```

## Design System Snapshot

There is no formal custom design system yet. The UI currently relies almost entirely on Streamlit defaults and Plotly defaults.

Colors currently in use:

- Plotly base template: `plotly_white`
- TOU background colors in `dashboard/charts.py`:
  - off-peak: `rgba(46, 204, 113, 0.08)`
  - semi-peak: `rgba(241, 196, 15, 0.11)`
  - peak: `rgba(231, 76, 60, 0.12)`
- Dispatch chart series:
  - load: `#34495e`
  - PV: `#27ae60`
  - grid import: `#8e44ad`
  - contract capacity: `#c0392b`
  - charge: `#2ecc71`
  - discharge: `#e74c3c`
  - SOC: `#2980b9`

Typography:

- Streamlit default system font.
- Plotly default font from `plotly_white`.
- No explicit typography scale or heading hierarchy beyond `st.title`, `st.subheader`, `st.metric`, and chart titles.

Spacing and layout:

- Streamlit default page spacing with `layout="wide"` in `dashboard/app.py`.
- KPI rows use `st.columns(4)` and `st.columns(5)`.
- Scenario form uses repeated `st.columns(3)`.
- Chart heights are fixed:
  - small/empty charts: 360-430px
  - forecast chart: 560px
  - dispatch chart: 760px
- Plot margins are manually set in `dashboard/charts.py`.

UI patterns:

- Sidebar source selector and EMS root path input.
- Four tabbed sections: Overview, Dispatch, MILP Explanation, Risk/Rerun.
- KPI metric rows.
- Plotly charts with legends and modebar.
- Streamlit form for scenario rerun.
- Expanders for diagnostics, stdout, and stderr.

## Current State

Built and working:

- `dashboard/app.py` loads successfully through Streamlit.
- Existing EMS output loads from `/Users/stephenlin/Downloads/mds-final/output/ems_2018`.
- Baseline comparison loads from `/Users/stephenlin/Downloads/mds-final/output/baselines_2018/comparison/all_baselines_metrics.csv`.
- The dashboard displays:
  - total cost, energy cost, excess cost, monthly peak
  - Advanced EMS vs B1-B5 cost comparison
  - PV utilization and curtailment charts
  - daily dispatch chart with load, PV, grid import, contract capacity, charge/discharge, SOC, and TOU background
  - objective term breakdown
  - energy flow chart
  - forecast vs actual chart
  - monthly peak tracking
  - risk metrics and diagnostics JSON
  - scenario rerun form
- Browser check at 1280x800 and 390x844 showed no horizontal page overflow.
- Verified successful scenario rerun:
  - run id: `20260529_144147_4444c3c0`
  - command format: `python3 /Users/stephenlin/Downloads/mds-final/ems_run.py --year 2018 --months 7 --out ... --diag-days 1 --fast --days 2 --Q 2000 --contract-kw 400 --lambda-excess 300 --w-soc 1500 --lambda-store 0`
  - produced `report_costs.json` and `month_07/short_term_executed.csv`
  - dashboard can switch to and load that scenario result
- Failed scenario runs are filtered out of the sidebar source selector if they do not contain `report_costs.json`.

Startup command:

```bash
cd /Users/stephenlin/Downloads/MDS_final/dashboard
.venv/bin/streamlit run app.py
```

Then open:

```text
http://localhost:8501
```

## Review Findings

### UI/UX Design

What's working well:

- The information architecture matches the audit use case: overview, dispatch, MILP explanation, and risk/rerun are separated clearly in `dashboard/app.py`.
- The overview immediately exposes decision-critical numbers: total cost, energy cost, excess cost, and monthly peak.
- The dispatch chart combines load, PV, grid import, contract capacity, charge/discharge, SOC, and TOU background in one place, which is useful for explaining why EMS actions happen.
- Empty chart states exist through `empty_figure()` in `dashboard/charts.py`, so missing data does not always produce a blank visual.

Issues found:

- Moderate: There is no custom visual system. The app looks like a default Streamlit prototype rather than a polished decision dashboard.
- Moderate: The dashboard does not explain unfamiliar technical terms in context. `MILP 行為解釋`, objective terms, `lambda_excess`, `w_soc`, and `lambda_store` appear without inline help.
- Moderate: TOU background colors are useful but not labeled in the chart. Users see colored bands but need domain knowledge to interpret them.
- Minor: Plotly modebar controls create visual clutter and tiny touch targets, especially on mobile.
- Minor: Some labels mix Chinese and English (`Scenario rerun`, `Run scenario`, `Q kWh`, `lambda_excess`). This is acceptable for internal use but weak for presentation.

Recommendations:

- Add `.streamlit/config.toml` with a deliberate theme, and set Streamlit toolbar mode to minimal if appropriate.
- Add short captions under each tab title explaining the purpose of the page.
- Add `help=` text to scenario inputs so users know what each parameter controls.
- Add a visible TOU legend or caption to the dispatch chart.
- Use a consistent bilingual strategy: either Chinese UI with parameter names in code-style labels, or English technical UI with Chinese descriptions.
- Disable or simplify Plotly modebars for presentation-oriented charts using Plotly config.

### Code Quality

What's working well:

- The code is split into clear modules: `app.py`, `data_loader.py`, `charts.py`, and `scenario_runner.py`.
- Data loading errors are wrapped in `DashboardDataError`, which makes missing files readable to users.
- Scenario command construction uses a list of subprocess arguments instead of shell string interpolation, reducing quoting and injection risk.
- `@st.cache_data` is used for baseline/report/month data loading, which helps repeated interactions.

Issues found:

- Critical: Streamlit tabs render all tab bodies, and `main()` currently calls every tab render path on every app run. This means hidden charts and hidden dataframes are still computed and mounted.
- Moderate: `select_month_day()` loads `long_term_daily.csv` but does not use it. This creates unnecessary IO and can fail a page even when short-term data is enough.
- Moderate: Several render functions assume exact columns exist after partial normalization. For example, `render_dispatch()` directly accesses `energy_cost`, `P_grid`, `P_ch`, and `P_dis`; `dispatch_timeseries()` directly accesses `P_grid`, `P_ch`, and `P_dis`.
- Moderate: Scenario rerun is synchronous and blocks the Streamlit request until subprocess completion. There is no default timeout, cancellation, progress streaming, or log tail while running.
- Minor: Failed scenario runs remain in `scenario_runs/` but are mostly hidden from the UI. There is no failed-run history, cleanup control, or direct stderr inspection unless the failure happened in the current session.
- Minor: Magic constants are spread through the code, such as `0.25` for 15-minute energy conversion and `0.205` for near-min SOC.
- Minor: `__pycache__` exists under `dashboard/`; it is ignored but should not be committed.

Recommendations:

- Replace `st.tabs()` with a single active-page control such as `st.segmented_control()` or `st.radio()` and conditionally render only the selected page.
- Remove `_load_long()` from `select_month_day()` until long-term data is actually visualized, or make it optional and page-specific.
- Add a schema validation layer per chart/page. Missing optional columns should produce warnings or fallback traces, not `KeyError`.
- Add a timeout and better status model to `run_scenario()`. For V1.1, at least set a conservative timeout and show failed run metadata in a table.
- Move constants like timestep hours and SOC near-min threshold into named constants in `data_loader.py` or a small `settings.py`.
- Clean generated files before committing.

### Responsiveness

What's working well:

- At 1280x800 and 390x844, the page did not produce horizontal overflow.
- `width="stretch"` is used for Streamlit Plotly charts and dataframes, which is correct for current Streamlit.
- Streamlit columns stack on mobile, so KPI values remain readable instead of clipping.
- The four tab labels fit within a 390px viewport, though they are close to the limit.

Issues found:

- Moderate: Fixed chart heights make mobile pages very long. The dispatch chart is 760px tall, forecast chart is 560px, and peak/cost charts are around 430px.
- Moderate: Because all tabs render at once, mobile loads hidden heavy charts too. This harms initial load and interaction responsiveness.
- Moderate: Long baseline labels require rotated x-axis labels and large bottom margins. On mobile, charts become text-heavy and harder to scan.
- Minor: KPI rows with four or five columns become a long stacked sequence on mobile, but there is no mobile-specific prioritization.
- Minor: Plotly modebar buttons are 24px wide and are not comfortable touch targets.

Recommendations:

- First fix conditional rendering so only one page renders at a time.
- Introduce compact mobile chart variants or shorter chart heights for overview/risk pages.
- Prefer horizontal bars for baseline comparisons on narrow widths, or abbreviate labels to B1-B5 with a legend/table below.
- Keep the first mobile screen focused on 2-3 critical KPIs instead of stacking every metric immediately.
- Consider disabling Plotly modebar on mobile-facing/presentation charts.

## Known Issues, Prioritized

1. Critical: All tab contents are rendered on every page run, causing hidden charts/dataframes to load and hurting performance. Fix `dashboard/app.py`.
2. Moderate: Scenario rerun blocks Streamlit synchronously with no timeout/cancel/log streaming. Fix `dashboard/app.py` and `dashboard/scenario_runner.py`.
3. Moderate: Unused long-term CSV load can fail or slow the app unnecessarily. Fix `dashboard/app.py`.
4. Moderate: Column assumptions can produce runtime `KeyError` if scenario output schema changes. Fix `dashboard/app.py` and `dashboard/charts.py`.
5. Moderate: Visual design is still Streamlit-default and not presentation-grade.
6. Moderate: Fixed chart heights and long labels make mobile usable but not polished.
7. Minor: No formal dashboard tests exist beyond manual browser checks and Python compile checks.
8. Minor: Generated `__pycache__` files exist locally and should stay uncommitted.

## Next Steps

1. Replace `st.tabs()` with conditional rendering so only the active page loads.
2. Remove or defer unused `long_term_daily.csv` loading.
3. Add column validation/fallback utilities for each chart and metric block.
4. Add a Streamlit theme config and basic visual polish: KPI cards, tighter chart styling, consistent color tokens, and minimal toolbar.
5. Improve scenario rerun UX with timeout, clearer parameter help, failed-run history, and visible stderr for failed historical runs.
6. Add mobile-oriented chart variants or at least reduce chart heights and convert baseline comparisons to horizontal bars.
7. Add lightweight tests for data loading, metrics composition, chart creation with missing optional columns, and scenario command construction.
8. Clean generated cache files before any commit.

## Constraints & Conventions

- Do not modify `/Users/stephenlin/Downloads/mds-final` source code unless the user explicitly approves it.
- Do not move or duplicate large EMS CSV outputs into `MDS_final/dashboard`.
- Keep the dashboard self-contained under `/Users/stephenlin/Downloads/MDS_final/dashboard`.
- Default EMS engine root should remain `/Users/stephenlin/Downloads/mds-final`, but the sidebar can let users override it.
- Preserve scenario outputs under `dashboard/scenario_runs/`; this directory is ignored by git.
- Preserve dashboard virtual environment under `dashboard/.venv/`; this directory is ignored by git.
- Keep UI copy primarily in Traditional Chinese, with technical parameter names preserved where needed.
- Prefer Streamlit + Plotly improvements for the next iteration. Do not introduce React/Vue or a separate frontend build unless the user explicitly asks to move away from Streamlit.
- Use structured loaders/parsers for CSV/JSON. Avoid ad hoc string parsing for data.
- Keep rerun commands as subprocess argument lists, not shell strings.
- Avoid changing unrelated dirty files in `/Users/stephenlin/Downloads/MDS_final`.

## Suggested First Action

Refactor `dashboard/app.py` so only the selected page renders. Replace the current `st.tabs()` block with an active-view control and conditional calls.

Concrete target:

```python
page = st.segmented_control(
    "頁面",
    ["總覽", "月/日調度", "MILP 行為解釋", "風險檢查 / 重跑"],
    default="總覽",
)

if page == "總覽":
    render_overview(metrics)
elif page == "月/日調度":
    _, day_df, _ = select_month_day(ems_output, months, key_prefix="dispatch")
    render_dispatch(day_df)
elif page == "MILP 行為解釋":
    _, day_df, _ = select_month_day(ems_output, months, key_prefix="explain")
    render_explanation(day_df)
else:
    _, day_df, month_df = select_month_day(ems_output, months, key_prefix="risk")
    render_risk(day_df, month_df, ems_output)
    render_rerun(engine_root)
```

After this change, reload `http://localhost:8501` and verify that the overview page no longer mounts all hidden Plotly charts. Then test the other three pages manually.
