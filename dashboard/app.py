from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import charts
from data_loader import (
    DEFAULT_ENGINE_ROOT,
    DashboardDataError,
    available_months,
    compose_comparison_metrics,
    list_scenario_runs,
    load_baseline_metrics,
    load_diagnostics,
    load_ems_report,
    load_month_short_term,
    risk_summary,
    source_paths,
)
from scenario_runner import SCENARIO_RUNS_DIR, ScenarioParams, run_scenario


st.set_page_config(page_title="EMS 智慧調度系統", layout="wide", page_icon="⚡")


@st.cache_data(show_spinner=False)
def _load_baselines(engine_root: str) -> pd.DataFrame:
    return load_baseline_metrics(source_paths(engine_root))


@st.cache_data(show_spinner=False)
def _load_report(ems_output: str) -> dict:
    return load_ems_report(Path(ems_output))


@st.cache_data(show_spinner=False)
def _load_short(ems_output: str, month: int) -> pd.DataFrame:
    return load_month_short_term(Path(ems_output), month)


def main() -> None:
    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ 資料來源")
        engine_root = Path(
            st.text_input("EMS 專案根目錄", value=str(DEFAULT_ENGINE_ROOT))
        ).expanduser()
        paths = source_paths(engine_root)

        scenarios = list_scenario_runs(SCENARIO_RUNS_DIR)
        if not scenarios.empty:
            if "report_exists" not in scenarios.columns:
                scenarios["report_exists"] = scenarios["path"].map(
                    lambda p: (Path(p) / "report_costs.json").is_file()
                )
            scenarios = scenarios[scenarios["report_exists"]].copy()

        scenario_options = ["現有 output/ems_2018"] + scenarios.get("run_id", pd.Series(dtype=str)).tolist()
        selected_source = st.selectbox("選擇執行結果", scenario_options)
        if selected_source == "現有 output/ems_2018":
            ems_output = paths.ems_output
            ems_label  = "Advanced EMS (MILP)"
        else:
            row = scenarios[scenarios["run_id"] == selected_source].iloc[0]
            ems_output = Path(row["path"])
            ems_label  = f"Scenario {selected_source}"
        st.caption(f"`{ems_output}`")

    # ── Load data ────────────────────────────────────────────────────────────
    try:
        baseline_metrics = _load_baselines(str(engine_root))
        report           = _load_report(str(ems_output))
        metrics          = compose_comparison_metrics(baseline_metrics, report, ems_label=ems_label)
    except DashboardDataError as exc:
        st.error(str(exc))
        return

    months = available_months(ems_output)
    if not months:
        st.error(f"找不到月份輸出: {ems_output}")
        return

    # ── Page header ──────────────────────────────────────────────────────────
    st.markdown("# ⚡ EMS 智慧調度系統")
    st.caption("MILP 最佳化電能管理系統 — 預測調度結果分析")
    st.divider()

    # ── Tabs ─────────────────────────────────────────────────────────────────
    overview_tab, dispatch_tab, explain_tab, risk_tab = st.tabs(
        ["📊 總覽與節費", "📅 月調度執行", "🔬 MILP 決策解釋", "⚠️ 風險檢查 / 重跑"]
    )

    with overview_tab:
        render_overview(metrics)

    with dispatch_tab:
        st.caption("下方顯示整月 15 分鐘解析度預測調度執行結果，可用右下角 range slider 縮放。")
        _, month_df = select_month(ems_output, months, key_prefix="dispatch")
        render_dispatch(month_df)

    with explain_tab:
        st.caption("MILP 目標函式各項權重貢獻，以及整月能源流向彙總。")
        _, month_df = select_month(ems_output, months, key_prefix="explain")
        render_explanation(month_df)

    with risk_tab:
        st.caption("超約風險、SOC 健康度、預測精度。最下方可重新執行場景。")
        _, month_df = select_month(ems_output, months, key_prefix="risk")
        render_risk(month_df, ems_output)
        render_rerun(engine_root)


# ── Overview ─────────────────────────────────────────────────────────────────

def render_overview(metrics: pd.DataFrame) -> None:
    advanced = metrics[metrics["baseline_id"] == "advanced_ems"]
    b1       = metrics[metrics["baseline_id"] == "no_battery"]
    b4       = metrics[metrics["baseline_id"] == "renewable_priority"]

    if advanced.empty:
        st.warning("找不到 Advanced EMS 結果")
        return

    adv      = advanced.iloc[-1]
    adv_cost = float(adv.get("total_cost", 0) or 0)

    # ── Hero: savings numbers ─────────────────────────────────────────────────
    h1, h2, h3, h4 = st.columns(4)

    h1.metric("MILP 總電費", f"NT$ {adv_cost:,.0f}")

    if not b1.empty:
        b1_cost  = float(b1.iloc[-1].get("total_cost", 0) or 0)
        save_b1  = b1_cost - adv_cost
        h2.metric(
            "相較無電池 (B1) 節省",
            f"NT$ {save_b1:,.0f}",
            delta=f"−{save_b1 / b1_cost * 100:.1f}%",
            delta_color="inverse",
        )

    if not b4.empty:
        b4_cost  = float(b4.iloc[-1].get("total_cost", 0) or 0)
        save_b4  = b4_cost - adv_cost
        h3.metric(
            "相較最佳規則策略 (B4) 節省",
            f"NT$ {save_b4:,.0f}",
            delta=f"−{save_b4 / b4_cost * 100:.1f}%",
            delta_color="inverse",
        )

    adv_pv = float(adv.get("renewable_utilization_ratio", 0) or 0)
    h4.metric("PV 利用率", f"{adv_pv:.1%}")

    st.divider()

    # ── Cost comparison charts ────────────────────────────────────────────────
    col_a, col_b = st.columns([1, 1])
    with col_a:
        st.subheader("各策略總電費比較")
        st.plotly_chart(charts.savings_hero(metrics), width="stretch")
    with col_b:
        st.subheader("電費結構（流動 / 基本 / 超約）")
        st.plotly_chart(charts.cost_stack(metrics), width="stretch")

    st.divider()

    # ── Secondary metrics ─────────────────────────────────────────────────────
    col_c, col_d = st.columns(2)
    with col_c:
        st.plotly_chart(charts.metric_bar(metrics, "renewable_utilization_ratio", "PV 利用率", "比例"), width="stretch")
    with col_d:
        st.plotly_chart(charts.metric_bar(metrics, "excess_cost", "超約電費", "元"), width="stretch")


# ── Month selector ────────────────────────────────────────────────────────────

def select_month(
    ems_output: Path,
    months: list[int],
    *,
    key_prefix: str,
) -> tuple[int, pd.DataFrame]:
    month = st.selectbox("月份", months, index=0, key=f"{key_prefix}_month",
                         format_func=lambda m: f"{m} 月")
    try:
        month_df = _load_short(str(ems_output), int(month))
    except DashboardDataError as exc:
        st.error(str(exc))
        return int(month), pd.DataFrame()
    return int(month), month_df


# ── Dispatch ──────────────────────────────────────────────────────────────────

def render_dispatch(month_df: pd.DataFrame) -> None:
    if not month_df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("月流動電費",  f"NT$ {month_df['energy_cost'].sum():,.0f}")
        m2.metric("月購電峰值",  f"{month_df['P_grid'].max():,.1f} kW")
        m3.metric("月總充電量",  f"{month_df['P_ch'].sum() * 0.25:,.1f} kWh")
        m4.metric("月總放電量",  f"{month_df['P_dis'].sum() * 0.25:,.1f} kWh")
        st.caption("💡 拖動圖表右下角 Range Slider 可放大任意時段")
    st.plotly_chart(charts.dispatch_timeseries(month_df), width="stretch")


# ── MILP Explanation ──────────────────────────────────────────────────────────

def render_explanation(month_df: pd.DataFrame) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("MILP 目標函式各項貢獻")
        st.plotly_chart(charts.objective_terms(month_df), width="stretch")
    with c2:
        st.subheader("整月能源流向")
        st.plotly_chart(charts.energy_flow(month_df), width="stretch")

    if not month_df.empty:
        with st.expander("原始調度資料（整月）"):
            show_cols = ["as_of", "tou", "P_load_actual", "P_pv_actual",
                         "P_ch", "P_dis", "P_grid", "P_contract_excess", "SOC_after_actual"]
            st.dataframe(
                month_df[[c for c in show_cols if c in month_df.columns]],
                width="stretch", hide_index=True,
            )


# ── Risk ──────────────────────────────────────────────────────────────────────

def render_risk(month_df: pd.DataFrame, ems_output: Path) -> None:
    summary = risk_summary(month_df)
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.metric("月峰值",        f"{summary.get('peak_grid_kw', 0):,.1f} kW")
    r2.metric("最大超約",      f"{summary.get('max_contract_excess_kw', 0):,.1f} kW")
    r3.metric("超約 tick 數",  f"{summary.get('excess_ticks', 0):,.0f}")
    r4.metric("SOC 接近下限",  f"{summary.get('soc_near_min_pct', 0):.1f}%")
    r5.metric("負載預測 MAE",  f"{summary.get('mean_abs_load_forecast_error_kw', 0):.1f} kW")

    st.divider()
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("預測 vs 實際")
        st.plotly_chart(charts.forecast_actual(month_df), width="stretch")
    with col_r:
        st.subheader("月峰值追蹤")
        st.plotly_chart(charts.peak_tracking(month_df), width="stretch")

    diagnostics = load_diagnostics(ems_output)
    if diagnostics:
        with st.expander("診斷 JSON"):
            st.json(diagnostics)


# ── Rerun ─────────────────────────────────────────────────────────────────────

def render_rerun(engine_root: Path) -> None:
    st.divider()
    st.subheader("🔄 場景重跑")
    st.caption("調整 MILP 參數重新執行 EMS 求解器，結果將出現在左側資料來源選單。")
    with st.form("scenario_form"):
        c1, c2, c3 = st.columns(3)
        year       = c1.number_input("年份", min_value=2010, max_value=2030, value=2018, step=1)
        months_sel = c2.multiselect("月份", options=list(range(1, 13)), default=[7])
        days       = c3.number_input("模擬天數", min_value=1, max_value=31, value=2, step=1,
                                     help="每個月實際跑幾天（快速測試用）")
        c4, c5, c6 = st.columns(3)
        fast        = c4.checkbox("快速模式 (--fast)", value=True)
        q_kwh       = c5.number_input("電池容量 Q (kWh)", min_value=1.0, value=2000.0, step=100.0,
                                      help="電池最大儲能容量")
        contract_kw = c6.number_input("契約容量 (kW)", min_value=1.0, value=400.0, step=10.0,
                                      help="與台電簽訂的用電契約容量")
        c7, c8, c9 = st.columns(3)
        lambda_excess = c7.number_input("超約懲罰 λ_excess", min_value=0.0, value=300.0, step=25.0,
                                        help="超過契約容量的每 kW 懲罰係數")
        w_soc         = c8.number_input("SOC 追蹤權重 w_soc", min_value=0.0, value=1500.0, step=100.0,
                                        help="偏離目標 SOC 的懲罰強度")
        lambda_store  = c9.number_input("儲能獎勵 λ_store", min_value=0.0, value=0.0, step=0.05,
                                        help="鼓勵電池儲能的獎勵係數")
        submitted = st.form_submit_button("▶ 執行場景", width="stretch")

    if submitted:
        if not months_sel:
            st.warning("至少選一個月份")
            return
        params = ScenarioParams(
            year=int(year),
            months=tuple(int(m) for m in months_sel),
            days=int(days),
            fast=bool(fast),
            q_kwh=float(q_kwh),
            contract_kw=float(contract_kw),
            lambda_excess=float(lambda_excess),
            w_soc=float(w_soc),
            lambda_store=float(lambda_store),
            diag_days=1,
        )
        with st.spinner("Running EMS scenario..."):
            try:
                result = run_scenario(params, engine_root=engine_root)
            except Exception as exc:
                st.error(f"場景啟動失敗: {exc}")
                return
        st.code(" ".join(result.command), language="bash")
        if result.returncode == 0:
            st.success(f"✅ 場景完成：{result.run_id}")
            st.cache_data.clear()
        else:
            st.error(f"❌ 場景失敗（return code {result.returncode}）")
        with st.expander("stdout"):
            st.text(result.stdout[-12000:] if result.stdout else "")
        with st.expander("stderr"):
            st.text(result.stderr[-12000:] if result.stderr else "")


if __name__ == "__main__":
    main()
