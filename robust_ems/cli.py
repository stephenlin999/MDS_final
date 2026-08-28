"""Command-line study runner for existing EMS dispatch output."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .model import (
    BatteryConfig,
    SolverConfig,
    TariffConfig,
    excess_charge,
    solve_oracles,
    solve_p_robust,
)
from .scenarios import ScenarioSet, build_joint_scenarios

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EMS_ROOT = Path("/Users/stephenlin/Downloads/mds-final")


def _load_ems_rows(ems_root: Path) -> pd.DataFrame:
    paths = sorted((ems_root / "output" / "ems_2018").glob("month_*/short_term_executed.csv"))
    if not paths:
        raise FileNotFoundError(f"no EMS short-term output found below {ems_root}")
    frame = pd.concat((pd.read_csv(path) for path in paths), ignore_index=True)
    frame["as_of"] = pd.to_datetime(frame["as_of"], errors="raise")
    return frame.sort_values("as_of").drop_duplicates("as_of", keep="last").reset_index(drop=True)


def _regular_rate(day: pd.Timestamp) -> float:
    summer = (day.month in (6, 7, 8, 9)) or (day.month == 5 and day.day >= 16) or (day.month == 10 and day.day <= 15)
    return 223.60 if summer else 166.90


def _point_scenario(day: pd.DataFrame) -> ScenarioSet:
    timestamps = pd.DatetimeIndex(day["as_of"])
    return ScenarioSet(
        timestamps=timestamps,
        load_kw=day[["P_load_fcst"]].to_numpy(dtype=float).T,
        pv_kw=day[["P_pv_fcst"]].to_numpy(dtype=float).T,
        probabilities=np.array([1.0]),
        source_dates=("point-forecast",),
        metadata={"method": "point_forecast"},
    )


def _build_day_scenarios(rows: pd.DataFrame, day: pd.DataFrame, *, as_of: pd.Timestamp, count: int) -> ScenarioSet:
    return build_joint_scenarios(
        rows,
        pd.DatetimeIndex(day["as_of"]),
        day["P_load_fcst"].to_numpy(dtype=float),
        day["P_pv_fcst"].to_numpy(dtype=float),
        as_of=as_of,
        n_scenarios=count,
    )


def _scenario_coverage(scenarios: ScenarioSet, day: pd.DataFrame) -> dict[str, object]:
    load_actual = day["P_load_actual"].to_numpy(dtype=float)
    pv_actual = day["P_pv_actual"].to_numpy(dtype=float)
    net_actual = load_actual - pv_actual

    def pointwise(values: np.ndarray, paths: np.ndarray) -> float:
        return float(np.mean((values >= paths.min(axis=0)) & (values <= paths.max(axis=0))))

    net_paths = scenarios.load_kw - scenarios.pv_kw
    load_coverage = pointwise(load_actual, scenarios.load_kw)
    pv_coverage = pointwise(pv_actual, scenarios.pv_kw)
    net_coverage = pointwise(net_actual, net_paths)
    return {
        "load_pointwise_envelope_coverage": load_coverage,
        "pv_pointwise_envelope_coverage": pv_coverage,
        "net_load_pointwise_envelope_coverage": net_coverage,
        "validation_passed": min(load_coverage, pv_coverage, net_coverage) >= 0.90,
        "actual_net_load_peak_kw": float(net_actual.max()),
        "scenario_net_load_peak_min_kw": float(net_paths.max(axis=1).min()),
        "scenario_net_load_peak_max_kw": float(net_paths.max(axis=1).max()),
        "actual_load_energy_kwh": float(load_actual.sum() * 0.25),
        "actual_pv_energy_kwh": float(pv_actual.sum() * 0.25),
        "mean_net_load_envelope_width_kw": float(np.mean(net_paths.max(axis=0) - net_paths.min(axis=0))),
    }


def _study_day(
    rows: pd.DataFrame,
    day: pd.DataFrame,
    *,
    scenario_count: int,
    p_grid: list[float],
    existing_peak_kw: float,
    battery: BatteryConfig,
    tariff: TariffConfig,
    solver: SolverConfig,
) -> dict[str, object]:
    scenarios = _build_day_scenarios(rows, day, as_of=day["as_of"].iloc[0], count=scenario_count)
    prices = day["C_price"].to_numpy(dtype=float)
    oracles = solve_oracles(
        scenarios,
        prices,
        existing_month_peak_kw=existing_peak_kw,
        battery=battery,
        tariff=tariff,
        solver=solver,
    )
    minimum = solve_p_robust(
        scenarios,
        prices,
        oracles,
        p_limit=None,
        existing_month_peak_kw=existing_peak_kw,
        battery=battery,
        tariff=tariff,
        solver=solver,
    )
    scans = []
    for value in p_grid:
        if minimum.p is not None and value + 1e-7 < minimum.p:
            scans.append({"p": value, "status": "below_p_min"})
            continue
        scans.append(
            solve_p_robust(
                scenarios,
                prices,
                oracles,
                p_limit=value,
                existing_month_peak_kw=existing_peak_kw,
                battery=battery,
                tariff=tariff,
                solver=solver,
            ).to_dict()
        )
    return {
        "mode": "day_ahead_p_scan",
        "target_date": str(day["as_of"].iloc[0].date()),
        "scenario_set": scenarios.to_dict(),
        "scenario_validation": _scenario_coverage(scenarios, day),
        "p_min_result": minimum.to_dict(),
        "p_scan": scans,
        "battery": asdict(battery),
        "tariff": asdict(tariff),
        "solver": asdict(solver),
    }


def _rolling_day(
    rows: pd.DataFrame,
    day: pd.DataFrame,
    *,
    scenario_count: int,
    p_limit: float,
    existing_peak_kw: float,
    battery: BatteryConfig,
    tariff: TariffConfig,
    solver: SolverConfig,
) -> dict[str, object]:
    initial_soc = 0.50
    soc = initial_soc
    month_peak = existing_peak_kw
    flow_cost = 0.0
    projections = 0
    intervals: list[dict[str, object]] = []

    for start in range(0, len(day), 4):
        remaining = day.iloc[start:].copy()
        scenarios = _build_day_scenarios(
            rows,
            remaining,
            as_of=remaining["as_of"].iloc[0],
            count=scenario_count,
        )
        prices = remaining["C_price"].to_numpy(dtype=float)
        cost_offset = flow_cost + excess_charge(month_peak, tariff) - excess_charge(existing_peak_kw, tariff)
        oracles = solve_oracles(
            scenarios,
            prices,
            initial_soc=soc,
            existing_month_peak_kw=month_peak,
            battery=battery,
            tariff=tariff,
            solver=solver,
            cost_offset_yuan=cost_offset,
        )
        p_min_result = solve_p_robust(
            scenarios,
            prices,
            oracles,
            p_limit=None,
            lock_steps=min(4, len(remaining)),
            initial_soc=soc,
            existing_month_peak_kw=month_peak,
            battery=battery,
            tariff=tariff,
            solver=solver,
            cost_offset_yuan=cost_offset,
        )
        fallback = p_min_result.p is None or p_limit + 1e-7 < p_min_result.p
        if fallback:
            point = _point_scenario(remaining)
            point_oracle = solve_oracles(
                point,
                prices,
                initial_soc=soc,
                existing_month_peak_kw=month_peak,
                battery=battery,
                tariff=tariff,
                solver=solver,
                cost_offset_yuan=cost_offset,
            )
            dispatch = solve_p_robust(
                point,
                prices,
                point_oracle,
                p_limit=0.0,
                lock_steps=min(4, len(remaining)),
                initial_soc=soc,
                existing_month_peak_kw=month_peak,
                battery=battery,
                tariff=tariff,
                solver=solver,
                cost_offset_yuan=cost_offset,
            )
        else:
            dispatch = solve_p_robust(
                scenarios,
                prices,
                oracles,
                p_limit=p_limit,
                lock_steps=min(4, len(remaining)),
                initial_soc=soc,
                existing_month_peak_kw=month_peak,
                battery=battery,
                tariff=tariff,
                solver=solver,
                cost_offset_yuan=cost_offset,
            )

        for offset in range(min(4, len(remaining))):
            record = remaining.iloc[offset]
            command_charge = dispatch.first_stage_charge_kw[offset]
            command_discharge = dispatch.first_stage_discharge_kw[offset]
            load = float(record["P_load_actual"])
            pv = float(record["P_pv_actual"])
            max_charge_soc = (battery.soc_max - soc) * battery.capacity_kwh / (battery.eta_charge * 0.25)
            max_discharge_soc = (soc - battery.soc_min) * battery.capacity_kwh * battery.eta_discharge / 0.25
            charge = min(command_charge, max(0.0, max_charge_soc))
            discharge = min(command_discharge, max(0.0, load - pv), max(0.0, max_discharge_soc))
            projected = abs(charge - command_charge) > 1e-6 or abs(discharge - command_discharge) > 1e-6
            projections += int(projected)
            grid = max(0.0, load + charge - discharge - pv)
            curtail = max(0.0, pv + discharge - load - charge)
            soc_before = soc
            soc += battery.eta_charge * charge * 0.25 / battery.capacity_kwh
            soc -= discharge * 0.25 / (battery.eta_discharge * battery.capacity_kwh)
            flow_cost += grid * float(record["C_price"]) * 0.25
            flow_cost += battery.degradation_yuan_per_kwh * (charge + discharge) * 0.25
            month_peak = max(month_peak, grid)
            intervals.append(
                {
                    "timestamp": pd.Timestamp(record["as_of"]).isoformat(),
                    "load_actual_kw": load,
                    "pv_actual_kw": pv,
                    "command_charge_kw": command_charge,
                    "command_discharge_kw": command_discharge,
                    "charge_kw": charge,
                    "discharge_kw": discharge,
                    "grid_kw": grid,
                    "curtail_kw": curtail,
                    "soc_before": soc_before,
                    "soc_after": soc,
                    "p_min": p_min_result.p,
                    "fallback": fallback,
                    "safety_projection": projected,
                }
            )

    actual_cost = flow_cost + excess_charge(month_peak, tariff) - excess_charge(existing_peak_kw, tariff)
    actual = ScenarioSet(
        timestamps=pd.DatetimeIndex(day["as_of"]),
        load_kw=day[["P_load_actual"]].to_numpy(dtype=float).T,
        pv_kw=day[["P_pv_actual"]].to_numpy(dtype=float).T,
        probabilities=np.array([1.0]),
        source_dates=("actual",),
        metadata={"method": "perfect_information_actual"},
    )
    oracle_actual = float(
        solve_oracles(
            actual,
            day["C_price"].to_numpy(dtype=float),
            initial_soc=initial_soc,
            existing_month_peak_kw=existing_peak_kw,
            battery=battery,
            tariff=tariff,
            solver=solver,
        )[0]
    )
    return {
        "mode": "hourly_rolling_backtest",
        "target_date": str(day["as_of"].iloc[0].date()),
        "p": p_limit,
        "scenario_count": scenario_count,
        "actual_cost_yuan": actual_cost,
        "oracle_actual_cost_yuan": oracle_actual,
        "ex_post_regret": actual_cost / oracle_actual - 1.0,
        "final_soc": soc,
        "month_peak_kw": month_peak,
        "safety_projection_rate": projections / len(day),
        "regret_within_p_plus_2pp": actual_cost / oracle_actual - 1.0 <= p_limit + 0.02,
        "validation_passed": (
            projections / len(day) < 0.01
            and actual_cost / oracle_actual - 1.0 <= p_limit + 0.02
        ),
        "intervals": intervals,
        "battery": asdict(battery),
        "tariff": asdict(tariff),
        "solver": asdict(solver),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2018-12-15")
    parser.add_argument("--ems-root", type=Path, default=DEFAULT_EMS_ROOT)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "model_results" / "robust")
    parser.add_argument("--scenarios", type=int, default=10)
    parser.add_argument("--p", type=float, default=0.15)
    parser.add_argument("--p-grid", nargs="+", type=float, default=[0.05, 0.10, 0.15, 0.20, 0.30])
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--contract-kw", type=float, default=400.0)
    parser.add_argument("--existing-peak-kw", type=float, default=0.0)
    parser.add_argument("--time-limit", type=float, default=60.0)
    args = parser.parse_args()

    rows = _load_ems_rows(args.ems_root)
    target = pd.Timestamp(args.date)
    day = rows[rows["as_of"].dt.date == target.date()].copy()
    if len(day) != 96:
        raise ValueError(f"expected 96 target intervals for {args.date}, got {len(day)}")

    battery = BatteryConfig()
    tariff = TariffConfig(
        contract_kw=args.contract_kw,
        regular_basic_rate_yuan_per_kw_month=_regular_rate(target),
    )
    solver = SolverConfig(time_limit_seconds=args.time_limit)
    if args.rolling:
        report = _rolling_day(
            rows,
            day,
            scenario_count=args.scenarios,
            p_limit=args.p,
            existing_peak_kw=args.existing_peak_kw,
            battery=battery,
            tariff=tariff,
            solver=solver,
        )
        filename = f"rolling_{args.date}_s{args.scenarios}_p{args.p:.2f}.json"
    else:
        report = _study_day(
            rows,
            day,
            scenario_count=args.scenarios,
            p_grid=args.p_grid,
            existing_peak_kw=args.existing_peak_kw,
            battery=battery,
            tariff=tariff,
            solver=solver,
        )
        filename = f"p_scan_{args.date}_s{args.scenarios}.json"

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / filename
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
