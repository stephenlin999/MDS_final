from __future__ import annotations

from typing import Iterable

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots


_PALETTE = {
    "load":     "#34495e",
    "pv":       "#27ae60",
    "grid":     "#8e44ad",
    "contract": "#c0392b",
    "charge":   "#2ecc71",
    "discharge":"#e74c3c",
    "soc":      "#2980b9",
    "energy":   "#4a9b8a",
    "basic":    "#7ec8b5",
    "excess":   "#e07b5f",
    "advanced": "#2a7a5e",
}

TOU_COLORS = {
    "off":     "rgba(46, 204, 113, 0.08)",
    "semi":    "rgba(241, 196, 15, 0.11)",
    "peak":    "rgba(231, 76, 60, 0.12)",
    "sat_semi":"rgba(241, 196, 15, 0.11)",
}

_LAYOUT_BASE = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(255,255,255,0.85)",
    font=dict(family="sans-serif", size=13),
)

_MODEBAR = dict(
    remove=["zoom2d","pan2d","select2d","lasso2d","autoScale2d","resetScale2d",
            "hoverClosestCartesian","hoverCompareCartesian","toggleSpikelines"],
)


def empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message, x=0.5, y=0.5, xref="paper", yref="paper",
        showarrow=False, font={"size": 15, "color": "#6b8c7f"},
    )
    fig.update_layout(**_LAYOUT_BASE, height=320)
    return fig


def savings_hero(metrics: pd.DataFrame) -> go.Figure:
    """Horizontal bar showing total cost per strategy, sorted ascending."""
    if metrics.empty or "total_cost" not in metrics.columns:
        return empty_figure("沒有成本資料")

    work = metrics[["label", "total_cost", "baseline_id"]].dropna(subset=["total_cost"]).copy()
    work = work.sort_values("total_cost", ascending=True).reset_index(drop=True)

    colors = [
        _PALETTE["advanced"] if bid == "advanced_ems" else "#a0c4b8"
        for bid in work["baseline_id"]
    ]

    fig = go.Figure(go.Bar(
        x=work["total_cost"],
        y=work["label"],
        orientation="h",
        marker_color=colors,
        text=[f"NT$ {v:,.0f}" for v in work["total_cost"]],
        textposition="outside",
        textfont=dict(size=12),
        cliponaxis=False,
    ))
    fig.update_layout(
        **_LAYOUT_BASE,
        height=max(280, len(work) * 52 + 60),
        xaxis=dict(title="總電費（元）", showgrid=True, gridcolor="rgba(0,0,0,0.06)"),
        yaxis=dict(title=""),
        margin=dict(l=10, r=120, t=30, b=40),
        showlegend=False,
        modebar=_MODEBAR,
    )
    return fig


def cost_stack(metrics: pd.DataFrame) -> go.Figure:
    if metrics.empty:
        return empty_figure("沒有成本資料")

    cost_cols = [c for c in ["energy_cost", "basic_cost", "excess_cost"] if c in metrics.columns]
    labels_map = {"energy_cost": "流動電費", "basic_cost": "基本電費", "excess_cost": "超約電費"}
    color_map  = {"流動電費": _PALETTE["energy"], "基本電費": _PALETTE["basic"], "超約電費": _PALETTE["excess"]}

    work = metrics[["label", *cost_cols]].melt(id_vars="label", var_name="cost_type", value_name="cost")
    work["cost_type"] = work["cost_type"].map(labels_map).fillna(work["cost_type"])

    # sort by total_cost so Advanced EMS appears last (highest bar = leftmost if sorted)
    order = metrics.sort_values("total_cost", ascending=False)["label"].tolist()

    fig = px.bar(
        work, x="label", y="cost", color="cost_type",
        color_discrete_map=color_map,
        category_orders={"label": order},
        labels={"label": "", "cost": "元", "cost_type": ""},
    )
    # add total annotation
    totals = metrics.set_index("label")["total_cost"]
    for label, total in totals.items():
        fig.add_annotation(
            x=label, y=total,
            text=f"<b>{total/10000:.1f}萬</b>",
            showarrow=False,
            yanchor="bottom",
            font=dict(size=11, color="#333"),
            yshift=4,
        )
    fig.update_layout(
        **_LAYOUT_BASE,
        height=460,
        barmode="stack",
        xaxis=dict(tickangle=-20),
        margin=dict(l=20, r=20, t=40, b=120),
        legend=dict(orientation="h", y=1.06, x=0),
        modebar=_MODEBAR,
    )
    return fig


def metric_bar(metrics: pd.DataFrame, metric: str, title: str, unit: str = "") -> go.Figure:
    if metrics.empty or metric not in metrics.columns:
        return empty_figure(f"沒有 {title} 資料")
    work = metrics[["label", metric, "baseline_id"]].dropna(subset=[metric]).copy()
    colors = [_PALETTE["advanced"] if bid == "advanced_ems" else "#a0c4b8" for bid in work["baseline_id"]]
    fig = go.Figure(go.Bar(
        x=work["label"], y=work[metric],
        marker_color=colors,
        text=[f"{v:.2f}" if isinstance(v, float) and v < 10 else f"{v:,.0f}" for v in work[metric]],
        textposition="outside",
        cliponaxis=False,
    ))
    fig.update_layout(
        **_LAYOUT_BASE,
        title=dict(text=title, font=dict(size=14)),
        height=360,
        showlegend=False,
        xaxis=dict(tickangle=-20),
        margin=dict(l=20, r=20, t=60, b=100),
        modebar=_MODEBAR,
    )
    if unit:
        fig.update_yaxes(title_text=unit)
    return fig


def dispatch_timeseries(month_df: pd.DataFrame) -> go.Figure:
    if month_df.empty:
        return empty_figure("沒有本月短期調度資料")

    x = month_df["as_of"]
    load = _first_available(month_df, ["P_load_actual", "P_load_fcst"])
    pv   = _first_available(month_df, ["P_pv_actual", "P_pv_fcst"])
    soc  = _first_available(month_df, ["SOC_after_actual", "SOC_after"])

    n_days = int((x.max() - x.min()).days) + 1 if len(x) > 1 else 1
    monthly = n_days > 5

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.45, 0.25, 0.30],
    )

    # ── Row 1: power flows ──────────────────────────────────────────────────
    fig.add_trace(go.Scatter(x=x, y=load, name="負載",     line=dict(color=_PALETTE["load"],  width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=pv,   name="PV 發電",  line=dict(color=_PALETTE["pv"],    width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=month_df["P_grid"], name="購電 P_grid", line=dict(color=_PALETTE["grid"], width=1.5)), row=1, col=1)
    if "P_contract_available" in month_df.columns:
        fig.add_trace(go.Scatter(
            x=x, y=month_df["P_contract_available"],
            name="契約容量", line=dict(color=_PALETTE["contract"], width=1.2, dash="dash"),
        ), row=1, col=1)

    # ── Row 2: charge / discharge ───────────────────────────────────────────
    if monthly:
        # Filled area is ~100× faster than go.Bar for 2000+ points
        fig.add_trace(go.Scatter(
            x=x, y=month_df["P_ch"],
            name="充電", mode="lines",
            line=dict(color=_PALETTE["charge"],    width=0.8),
            fill="tozeroy", fillcolor="rgba(46,204,113,0.35)",
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=x, y=-month_df["P_dis"],
            name="放電", mode="lines",
            line=dict(color=_PALETTE["discharge"], width=0.8),
            fill="tozeroy", fillcolor="rgba(231,76,60,0.35)",
        ), row=2, col=1)
    else:
        fig.add_trace(go.Bar(x=x, y=month_df["P_ch"],    name="充電", marker_color=_PALETTE["charge"]),    row=2, col=1)
        fig.add_trace(go.Bar(x=x, y=-month_df["P_dis"],  name="放電", marker_color=_PALETTE["discharge"]), row=2, col=1)

    # ── Row 3: SOC ──────────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(x=x, y=soc, name="SOC", line=dict(color=_PALETTE["soc"], width=1.5)), row=3, col=1)

    # TOU background only for single-day / short window (< 5 days)
    if not monthly:
        _add_tou_background(fig, month_df, rows=[1, 2, 3])

    fig.update_yaxes(title_text="kW",  row=1, col=1, showgrid=True, gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="kW",  row=2, col=1, showgrid=True, gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="SOC", row=3, col=1, range=[0, 1], showgrid=True, gridcolor="rgba(0,0,0,0.05)")

    fig.update_layout(
        **_LAYOUT_BASE,
        height=740,
        barmode="relative",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=12)),
        margin=dict(l=20, r=20, t=50, b=40),
        modebar=_MODEBAR,
        # Range slider on bottom x-axis for monthly view
        xaxis3=dict(
            rangeslider=dict(visible=monthly, thickness=0.04, bgcolor="rgba(220,232,227,0.6)"),
        ),
    )
    return fig


def objective_terms(month_df: pd.DataFrame) -> go.Figure:
    if month_df.empty:
        return empty_figure("沒有 objective term 資料")
    terms = {
        "obj_purchase":     "購電成本",
        "obj_peak":         "尖峰懲罰",
        "obj_excess":       "超約懲罰",
        "obj_soc":          "SOC 追蹤",
        "obj_reserve":      "備用容量",
        "obj_deg":          "電池損耗",
        "obj_curt":         "棄光懲罰",
        "obj_store":        "儲能獎勵",
        "obj_monthly_peak": "月峰值懲罰",
    }
    rows = []
    for col, label in terms.items():
        if col in month_df.columns:
            val = float(pd.to_numeric(month_df[col], errors="coerce").fillna(0).median())
            rows.append({"term": label, "value": val})
    if not rows:
        return empty_figure("沒有 objective term 欄位")
    work = pd.DataFrame(rows).sort_values("value", ascending=True)
    fig = px.bar(
        work, x="value", y="term", orientation="h",
        color_discrete_sequence=[_PALETTE["energy"]],
        labels={"value": "rolling horizon median", "term": ""},
    )
    fig.update_layout(**_LAYOUT_BASE, height=400, margin=dict(l=20, r=20, t=40, b=40), modebar=_MODEBAR)
    return fig


def energy_flow(month_df: pd.DataFrame, dt_hours: float = 0.25) -> go.Figure:
    if month_df.empty:
        return empty_figure("沒有能源流資料")
    flow_cols = {
        "Ppv_to_load":  "PV → 負載",
        "Ppv_to_batt":  "PV → 電池",
        "Ppv_curt":     "PV 棄光",
        "Pgrid_to_load":"電網 → 負載",
        "Pgrid_to_batt":"電網 → 電池",
        "Pbat_to_load": "電池 → 負載",
    }
    rows = []
    for col, label in flow_cols.items():
        if col in month_df.columns:
            kwh = float(pd.to_numeric(month_df[col], errors="coerce").fillna(0).sum() * dt_hours)
            rows.append({"flow": label, "kwh": kwh})
    if not rows:
        return empty_figure("沒有能源流欄位")
    flow_colors = [
        "#27ae60","#7dcea0","#e74c3c",
        "#8e44ad","#bb8fce","#2980b9",
    ]
    work = pd.DataFrame(rows)
    fig = px.bar(
        work, x="flow", y="kwh",
        color="flow",
        color_discrete_sequence=flow_colors,
        labels={"flow": "", "kwh": "kWh"},
        text=[f"{v:,.0f}" for v in work["kwh"]],
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        **_LAYOUT_BASE,
        showlegend=False,
        height=400,
        xaxis_tickangle=-15,
        margin=dict(l=20, r=20, t=40, b=100),
        modebar=_MODEBAR,
    )
    return fig


def forecast_actual(month_df: pd.DataFrame) -> go.Figure:
    if month_df.empty:
        return empty_figure("沒有預測 vs 實際資料")
    x = month_df["as_of"]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        subplot_titles=["負載預測 vs 實際", "PV 預測 vs 實際"],
    )
    if {"P_load_fcst", "P_load_actual"}.issubset(month_df.columns):
        fig.add_trace(go.Scatter(x=x, y=month_df["P_load_fcst"],    name="負載 預測", line=dict(color="#a9b7c0", width=1.2, dash="dot")),  row=1, col=1)
        fig.add_trace(go.Scatter(x=x, y=month_df["P_load_actual"],  name="負載 實際", line=dict(color=_PALETTE["load"], width=1.5)),        row=1, col=1)
    if {"P_pv_fcst", "P_pv_actual"}.issubset(month_df.columns):
        fig.add_trace(go.Scatter(x=x, y=month_df["P_pv_fcst"],      name="PV 預測",   line=dict(color="#82e0aa", width=1.2, dash="dot")), row=2, col=1)
        fig.add_trace(go.Scatter(x=x, y=month_df["P_pv_actual"],    name="PV 實際",   line=dict(color=_PALETTE["pv"], width=1.5)),         row=2, col=1)
    fig.update_yaxes(title_text="kW", row=1, col=1, showgrid=True, gridcolor="rgba(0,0,0,0.05)")
    fig.update_yaxes(title_text="kW", row=2, col=1, showgrid=True, gridcolor="rgba(0,0,0,0.05)")
    fig.update_layout(
        **_LAYOUT_BASE,
        height=540,
        legend=dict(orientation="h", y=1.04, font=dict(size=12)),
        margin=dict(l=20, r=20, t=55, b=40),
        modebar=_MODEBAR,
    )
    return fig


def peak_tracking(month_df: pd.DataFrame) -> go.Figure:
    if month_df.empty:
        return empty_figure("沒有月峰值追蹤資料")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=month_df["as_of"], y=month_df["P_grid"],
        name="實際購電 P_grid",
        line=dict(color=_PALETTE["grid"], width=1.2),
        fill="tozeroy", fillcolor="rgba(142,68,173,0.12)",
    ))
    if "monthly_peak_kw_after" in month_df.columns:
        fig.add_trace(go.Scatter(
            x=month_df["as_of"], y=month_df["monthly_peak_kw_after"],
            name="累積月峰值", line=dict(color="#d35400", width=2),
        ))
    if "P_contract_available" in month_df.columns:
        fig.add_trace(go.Scatter(
            x=month_df["as_of"], y=month_df["P_contract_available"],
            name="契約容量上限", line=dict(color=_PALETTE["contract"], width=1.5, dash="dash"),
        ))
    fig.update_layout(
        **_LAYOUT_BASE,
        height=420,
        yaxis_title="kW",
        legend=dict(orientation="h", y=1.04, font=dict(size=12)),
        margin=dict(l=20, r=20, t=40, b=40),
        modebar=_MODEBAR,
    )
    return fig


def _first_available(df: pd.DataFrame, columns: Iterable[str]) -> pd.Series:
    result = pd.Series(index=df.index, dtype=float)
    for col in columns:
        if col in df.columns:
            result = result.fillna(pd.to_numeric(df[col], errors="coerce"))
    return result


def _add_tou_background(fig: go.Figure, df: pd.DataFrame, rows: list[int]) -> None:
    if "tou" not in df.columns or "as_of" not in df.columns or df.empty:
        return
    work = df[["as_of", "tou"]].dropna().copy()
    if work.empty:
        return
    work["group"] = (work["tou"] != work["tou"].shift()).cumsum()
    for _, grp in work.groupby("group"):
        start = grp["as_of"].iloc[0]
        end   = grp["as_of"].iloc[-1] + pd.Timedelta(minutes=15)
        color = TOU_COLORS.get(str(grp["tou"].iloc[0]), "rgba(149,165,166,0.08)")
        for row in rows:
            fig.add_vrect(x0=start, x1=end, fillcolor=color, line_width=0, layer="below", row=row, col=1)
