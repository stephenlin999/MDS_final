# React EMS Dashboard Handoff

## Project Summary

`react-dashboard/` 是新的可跑 React EMS dashboard，用來展示 MILP 能源管理結果。目標使用者有兩種：business owner 需要在第一屏看到省多少錢，工程端需要往下鑽調度、SOC、超約、SHAP、Monte Carlo 與參數情境。它不改原本 EMS/MILP 程式，也不搬大型 CSV；前端使用本地 JSON。

原 Streamlit 面板仍保留在 `dashboard/`，適合快速審計與 scenario CLI rerun。新的 React app 是主要展示/視覺原型。

## Tech Stack

- React 19 + Vite
- Recharts
- Tailwind CSS
- shadcn/ui-style local components
- Radix Tabs / Slider
- lucide-react
- Local JSON import only, no API/fetch calls

## File Structure

```text
react-dashboard/
├── README.md
├── HANDOFF.md
├── package.json
├── index.html
├── vite.config.js
├── tailwind.config.js
├── postcss.config.js
├── components.json
├── scripts/
│   └── build-data.mjs              # EMS/model outputs -> frontend JSON
└── src/
    ├── App.jsx
    ├── main.jsx
    ├── dashboard.jsx               # Main four-tab dashboard
    ├── index.css                   # Fonts, tokens, global utilities
    ├── data/
    │   └── ems-dashboard-data.json # Generated local dashboard data
    ├── lib/
    │   └── utils.js
    └── components/ui/
        ├── badge.jsx
        ├── button.jsx
        ├── card.jsx
        ├── input.jsx
        ├── slider.jsx
        └── tabs.jsx
```

## Design System Snapshot

The design direction is Minimalist Modern: off-white canvas, deep slate text, Electric Blue gradient accents, white elevated cards, and semantic green/red only for savings/risk.

Core tokens:

- Background: `#FAFAFA`
- Foreground: `#0F172A`
- Accent gradient: `#0052FF -> #4D7CFF`
- Savings green: `#2D7D46`
- Alert red: `#C0392B`
- Muted text: `#64748B`
- Border: `#E2E8F0`
- Display font: Calistoga
- UI/body font: Inter
- Mono labels: JetBrains Mono

Patterns already in use:

- Section label pills with mono uppercase text and blue dot
- Large executive KPI cards before technical tabs
- Sticky tab rail
- Recharts cards with legends, grid lines, and hover tooltip
- Dark inverted executive readout section
- Live scenario sliders with right-side preview

## Current State

Working:

- Dashboard runs at `http://localhost:5173/` with `npm run dev -- --port 5173`.
- `npm run build:data` creates `src/data/ems-dashboard-data.json` from real local EMS/model outputs.
- `npm run build` succeeds.
- Four tabs are implemented:
  - `總覽與節費`
  - `月調度執行`
  - `MILP 決策解釋`
  - `風險檢查 / 場景重跑`
- Implemented interactions:
  - series toggles
  - click-to-day zoom state
  - Monte Carlo generation/load toggle
  - live parameter sliders
  - ROI input recalculation
- Decision explanation data now covers all 12 months:
  - July and December use complete existing EMS output.
  - Other months use three Monte Carlo-calibrated future scenario days per month.

## Known Issues

Priority:

1. The frontend imports a generated JSON file containing 15-minute schedules, so the build has a large main chunk. It is acceptable for a local prototype, but production should split data by month/day or lazy-load static JSON.
2. The full MILP rerun button is visual-only. If real reruns are needed, wire it to a controlled backend or reuse the Streamlit runner logic.
3. Ten months use generated Monte Carlo-calibrated scenario days, not solved full-month MILP output. Keep this wording visible in the UI to avoid overclaiming.
4. Load SHAP values are prototype values because only solar SHAP output exists in `model_results/reports/shap_importance.csv`.

## Next Steps

1. Split generated data into `overview.json`, `month_07.json`, `month_12.json`, and model/MC JSON so the initial bundle only loads executive data.
2. Add a real scenario execution path after deciding whether the host will be local-only, Streamlit-backed, or API-backed.
3. Add chart-level empty states for months without detailed 15-minute schedules.
4. Replace prototype load SHAP with real load model explanation if that model exists later.
5. Add Playwright visual checks for desktop and mobile once this becomes a committed app.

## Constraints & Conventions

- Keep `react-dashboard/` independent from the legacy Streamlit `dashboard/`.
- Do not modify `/Users/stephenlin/Downloads/mds-final` engine code from this app.
- Keep data generation one-way: EMS/model outputs -> local JSON -> React import.
- Use Tailwind utilities and local shadcn-style components; avoid one-off inline styles except chart colors and dynamic widths.
- Preserve the executive-first layout: money and savings above technical detail.

## Suggested First Action

Refactor `scripts/build-data.mjs` to write one JSON file per month and update `src/dashboard.jsx` to lazy-load selected month data. This directly fixes the largest current technical issue without changing the UI.
