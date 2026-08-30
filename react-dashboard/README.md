# React EMS Dashboard

這是新的可跑 React/Vite EMS dashboard，用來取代原本只適合快速審計的 Streamlit 畫面，作為展示與答辯用的前端原型。它不呼叫 API；資料由 `scripts/build-data.mjs` 從現有 EMS output 和本 repo 的 `model_results` 轉成 `src/data/ems-dashboard-data.json`，前端直接 import 這份本地 JSON。

目前的展示邏輯是：首頁先用雙長條圖直接比較「無系統」與「有 MILP 系統」每月電費；技術頁再往下拆調度、SOC、超約、SHAP、Monte Carlo 與情境參數。

## Stack

- React 19 + Vite
- Recharts
- Tailwind CSS
- shadcn/ui 風格的本地元件封裝：Card、Badge、Button、Tabs、Slider、Input
- Radix Tabs / Slider
- lucide-react icons

## Commands

```bash
cd /Users/stephenlin/Downloads/MDS_final/react-dashboard
npm install
npm run build:data
npm run dev -- --port 5173
```

開啟：

```text
http://localhost:5173/
```

Production build:

```bash
npm run build
```

## P-Robust Owner Comparison

The main dashboard header links to a standalone interactive comparison page:

```text
public/owner-full-grid-robust-comparison.html
```

The page compares one representative day under four consistent operating modes: full grid purchase without PV or battery, PV only, the previous deterministic EMS, and hourly rolling P-robust dispatch. It includes hover details for cost composition, savings sources, grid energy, peak demand, and the 24-hour grid-power trace.

The displayed P-robust result is a frozen research snapshot derived from `model_results/robust/rolling_2018-12-15_s10_p0.15.json` and the matching legacy EMS output. It must not be presented as an annual guarantee: final SOC differs from initial SOC, and current scenario coverage and out-of-sample regret do not yet pass validation.

## Single-file HTML Export

若只是臨時展示或最簡單部署，可以直接使用：

```text
/Users/stephenlin/Downloads/MDS_final/react-dashboard/demo.html
```

這份檔案是完全獨立的 HTML，不需要 `npm install`、不需要 Vite dev server，也不依賴外部 CDN。所有樣式、互動與 demo 資料都寫在同一個檔案裡，適合快速寄送、投影展示或放到靜態空間。它是展示版，不會讀取 `src/data/ems-dashboard-data.json`，也不會重跑 MILP。

單檔版仍保留展示需要的互動：主要 SVG 圖表支援 hover 浮動資訊卡，月調度支援 series toggle，風險/場景頁提供月份、電池容量、契約容量、超約懲罰、SOC 權重與 CAPEX 的即時估算，並同步更新成本對比圖、容量敏感度圖、風險狀態與簡化公式。

## Data

預設讀取：

- EMS 成本與調度：`/Users/stephenlin/Downloads/mds-final/output/ems_2018`
- Baselines：`/Users/stephenlin/Downloads/mds-final/output/baselines_2018/comparison/all_baselines_metrics.csv`
- Forecast/model metrics：`/Users/stephenlin/Downloads/MDS_final/model_results`

產生的前端資料：

```text
react-dashboard/src/data/ems-dashboard-data.json
```

當 EMS output 更新後，重新執行：

```bash
npm run build:data
```

資料產生規則：

- 總覽成本與 baseline 比較來自既有 EMS/baseline output。
- 7 月與 12 月的調度決策使用完整既有 EMS output。
- 其他月份使用 Monte Carlo 年度發電量投影做校準，每月生成 3 個未來情境抽樣日，每天 96 筆 15 分鐘排程。
- UI 不顯示歷史年份，避免把校準資料誤讀成未來實際日期。

## Dashboard Pages

`總覽與節費`：展示 C-suite 需要先看到的結果，包含無系統 vs 有系統雙長條、策略比較、月份成本拆解與累計節省。

`月調度執行`：按月份檢查負載、PV、購電、充放電與 SOC；支援 series toggle 與點選日期進入 15 分鐘解析度。

`MILP 決策解釋`：按月份與情境日檢查日內決策排程。7 月、12 月是既有 EMS output，其餘月份是 Monte Carlo 校準的未來抽樣情境。

`風險檢查 / 場景重跑`：顯示超約、SOC、需量與預測信心度，並提供即時 slider 估算成本、節省、超約事件與回收年限。

## Current Scope

目前是展示型 dashboard，不會重跑 MILP backend。`風險檢查 / 場景重跑` 的 slider 會即時用簡化公式估算成本與回收期；「執行完整場景」按鈕是 visual-only，之後若要接真實求解，再接原本 Streamlit `scenario_runner.py` 或新增 API。

需要特別說清楚：除 7 月與 12 月外，其餘月份不是完整 MILP 求解結果，而是 Monte Carlo 發電量校準後的未來情境抽樣，用於展示與答辯敘事。
