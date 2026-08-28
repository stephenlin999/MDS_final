from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_ENGINE_ROOT = Path("/Users/stephenlin/Downloads/mds-final")
DEFAULT_EMS_OUTPUT_NAME = "ems_2018"
DEFAULT_BASELINE_OUTPUT_NAME = "baselines_2018"
SCENARIO_RUNS_DIR = Path(__file__).resolve().parent / "scenario_runs"


class DashboardDataError(RuntimeError):
    """Raised when expected dashboard source data is missing or malformed."""


@dataclass(frozen=True)
class SourcePaths:
    engine_root: Path
    output_root: Path
    ems_output: Path
    baseline_comparison: Path
    scenario_runs: Path


def source_paths(
    engine_root: str | Path = DEFAULT_ENGINE_ROOT,
    *,
    ems_output: str = DEFAULT_EMS_OUTPUT_NAME,
    baseline_output: str = DEFAULT_BASELINE_OUTPUT_NAME,
) -> SourcePaths:
    root = Path(engine_root).expanduser()
    output = root / "output"
    return SourcePaths(
        engine_root=root,
        output_root=output,
        ems_output=output / ems_output,
        baseline_comparison=output / baseline_output / "comparison",
        scenario_runs=SCENARIO_RUNS_DIR,
    )


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise DashboardDataError(f"找不到 {label}: {path}")
    return path


def _read_json(path: Path, label: str) -> dict[str, Any]:
    require_file(path, label)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DashboardDataError(f"{label} JSON 格式錯誤: {path}") from exc


def _read_csv(path: Path, label: str, **kwargs: Any) -> pd.DataFrame:
    require_file(path, label)
    try:
        return pd.read_csv(path, **kwargs)
    except Exception as exc:  # pandas exposes several parser exception types.
        raise DashboardDataError(f"{label} CSV 讀取失敗: {path}") from exc


def load_baseline_metrics(paths: SourcePaths) -> pd.DataFrame:
    metrics_path = paths.baseline_comparison / "all_baselines_metrics.csv"
    df = _read_csv(metrics_path, "baseline comparison metrics")
    return normalize_metrics_frame(df)


def load_ems_report(ems_output_dir: Path) -> dict[str, Any]:
    return _read_json(ems_output_dir / "report_costs.json", "EMS report_costs")


def normalize_metrics_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "label" not in out.columns and "baseline_id" in out.columns:
        out["label"] = out["baseline_id"]
    if "baseline_id" not in out.columns and "label" in out.columns:
        out["baseline_id"] = out["label"]
    for col in METRIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


METRIC_COLUMNS = [
    "energy_cost",
    "basic_cost",
    "excess_cost",
    "total_cost",
    "peak_grid_kw",
    "par",
    "renewable_utilization_ratio",
    "curtailment_kwh",
    "battery_cycle_count",
    "battery_mode_switches",
    "grid_dependency_ratio",
    "soc_std",
]


def metrics_row_from_ems_report(
    report: dict[str, Any],
    *,
    label: str = "Advanced EMS (MILP)",
    baseline_id: str = "advanced_ems",
) -> pd.DataFrame:
    month_summary = (
        _aggregate_months(report["months"])
        if isinstance(report.get("months"), dict)
        else {}
    )
    row = {**month_summary, **dict(report.get("grand_total", {}))}
    row["label"] = label
    row["baseline_id"] = baseline_id
    return normalize_metrics_frame(pd.DataFrame([row]))


def _aggregate_months(months: dict[str, Any]) -> dict[str, float]:
    summed = {
        "energy_cost": 0.0,
        "basic_cost": 0.0,
        "excess_cost": 0.0,
        "total_cost": 0.0,
        "pv_generation_kwh": 0.0,
        "renewable_used_kwh": 0.0,
        "curtailment_kwh": 0.0,
        "battery_cycle_count": 0.0,
        "battery_mode_switches": 0.0,
    }
    peak = 0.0
    for month in months.values():
        for key in summed:
            summed[key] += float(month.get(key, 0.0) or 0.0)
        peak = max(peak, float(month.get("peak_grid_kw", 0.0) or 0.0))
    summed["peak_grid_kw"] = peak
    if summed["pv_generation_kwh"] > 0:
        summed["renewable_utilization_ratio"] = (
            summed["renewable_used_kwh"] / summed["pv_generation_kwh"]
        )
    return summed


def compose_comparison_metrics(
    baseline_metrics: pd.DataFrame,
    ems_report: dict[str, Any],
    *,
    ems_label: str = "Advanced EMS (MILP)",
) -> pd.DataFrame:
    base = baseline_metrics.copy()
    base = base[base.get("baseline_id", "") != "advanced_ems"]
    advanced = metrics_row_from_ems_report(ems_report, label=ems_label)
    return normalize_metrics_frame(pd.concat([base, advanced], ignore_index=True))


def load_month_short_term(ems_output_dir: Path, month: int) -> pd.DataFrame:
    path = ems_output_dir / f"month_{month:02d}" / "short_term_executed.csv"
    df = _read_csv(path, f"month {month:02d} short-term dispatch", parse_dates=["as_of", "day_start"])
    return normalize_short_term(df)


def load_month_long_term(ems_output_dir: Path, month: int) -> pd.DataFrame:
    path = ems_output_dir / f"month_{month:02d}" / "long_term_daily.csv"
    df = _read_csv(path, f"month {month:02d} long-term dispatch", parse_dates=["timestamp", "day_start"])
    return df


def normalize_short_term(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "as_of" in out.columns:
        out["as_of"] = pd.to_datetime(out["as_of"], errors="coerce")
        out["date"] = out["as_of"].dt.normalize()
    if "day_start" in out.columns:
        out["day_start"] = pd.to_datetime(out["day_start"], errors="coerce")
    numeric_cols = [
        "P_load_fcst",
        "P_pv_fcst",
        "P_load_actual",
        "P_pv_actual",
        "P_ch",
        "P_dis",
        "P_grid",
        "P_grid_fcst",
        "P_contract_available",
        "P_contract_excess",
        "SOC_after",
        "SOC_after_actual",
        "SOC_kWh_after",
        "SOC_kWh_after_actual",
        "energy_cost",
        "P_curt",
        "Ppv_curt",
        "Ppv_to_load",
        "Ppv_to_batt",
        "Pgrid_to_load",
        "Pgrid_to_batt",
        "Pbat_to_load",
        "monthly_peak_kw_after",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def available_months(ems_output_dir: Path) -> list[int]:
    months: list[int] = []
    if not ems_output_dir.is_dir():
        return months
    for child in ems_output_dir.iterdir():
        if child.is_dir() and child.name.startswith("month_"):
            try:
                months.append(int(child.name.split("_", 1)[1]))
            except ValueError:
                continue
    return sorted(set(months))


def available_days(short_df: pd.DataFrame) -> list[pd.Timestamp]:
    if short_df.empty or "date" not in short_df.columns:
        return []
    return [pd.Timestamp(day) for day in sorted(short_df["date"].dropna().unique())]


def filter_day(short_df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    if short_df.empty or "date" not in short_df.columns:
        return pd.DataFrame()
    day = pd.Timestamp(day).normalize()
    return short_df[short_df["date"] == day].copy()


def load_diagnostics(ems_output_dir: Path) -> dict[str, Any]:
    candidates = [
        ems_output_dir / "diagnostics_report" / "dispatch_diagnostics.json",
        ems_output_dir / "diagnostics_report_smoke" / "dispatch_diagnostics.json",
    ]
    for path in candidates:
        if path.is_file():
            return _read_json(path, "dispatch diagnostics")
    return {}


def risk_summary(short_df: pd.DataFrame) -> dict[str, float]:
    if short_df.empty:
        return {}
    p_grid = short_df.get("P_grid", pd.Series(dtype=float)).astype(float)
    contract = short_df.get("P_contract_available", pd.Series(dtype=float)).astype(float)
    soc = (
        short_df["SOC_after_actual"].fillna(short_df["SOC_after"])
        if {"SOC_after_actual", "SOC_after"}.issubset(short_df.columns)
        else short_df.get("SOC_after", pd.Series(dtype=float))
    )
    excess = (p_grid - contract).clip(lower=0.0) if len(contract) else pd.Series(dtype=float)
    return {
        "peak_grid_kw": float(p_grid.max()) if len(p_grid) else 0.0,
        "max_contract_excess_kw": float(excess.max()) if len(excess) else 0.0,
        "excess_ticks": float((excess > 1e-6).sum()) if len(excess) else 0.0,
        "soc_near_min_pct": float((soc <= 0.205).mean() * 100.0) if len(soc) else 0.0,
        "mean_abs_load_forecast_error_kw": _mean_abs_error(short_df, "P_load_actual", "P_load_fcst"),
        "mean_abs_pv_forecast_error_kw": _mean_abs_error(short_df, "P_pv_actual", "P_pv_fcst"),
    }


def _mean_abs_error(df: pd.DataFrame, actual_col: str, forecast_col: str) -> float:
    if actual_col not in df.columns or forecast_col not in df.columns:
        return 0.0
    sub = df[[actual_col, forecast_col]].dropna()
    if sub.empty:
        return 0.0
    return float((sub[actual_col] - sub[forecast_col]).abs().mean())


def list_scenario_runs(scenario_dir: Path = SCENARIO_RUNS_DIR) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not scenario_dir.is_dir():
        return pd.DataFrame(rows)
    for child in sorted(scenario_dir.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        meta_path = child / "run_meta.json"
        report_path = child / "report_costs.json"
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        rows.append(
            {
                "run_id": child.name,
                "path": str(child),
                "status": meta.get("status", "available" if report_path.is_file() else "unknown"),
                "report_exists": report_path.is_file(),
                "created_at": meta.get("created_at", child.name[:15]),
                "command": " ".join(meta.get("command", [])),
            }
        )
    return pd.DataFrame(rows)
