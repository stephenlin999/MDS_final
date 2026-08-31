"""Generate the formal annual P-robust planning simulation and UI data."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Iterable

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition
from sklearn.cluster import KMeans

from .model import BatteryConfig, SolverConfig


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EMS_ROOT = Path("/Users/stephenlin/Downloads/mds-final")
PERIODS = ("peak", "semi", "sat_semi", "off")
PERIOD_LABELS = {
    "peak": "尖峰",
    "semi": "半尖峰",
    "sat_semi": "週六半尖峰",
    "off": "離峰",
}
ENERGY_RATES = {
    (True, "weekday", "off"): 2.53,
    (True, "weekday", "semi"): 5.85,
    (True, "weekday", "peak"): 9.39,
    (True, "saturday", "off"): 2.53,
    (True, "saturday", "semi"): 2.60,
    (True, "sunday", "off"): 2.53,
    (False, "weekday", "off"): 2.32,
    (False, "weekday", "semi"): 5.47,
    (False, "saturday", "off"): 2.32,
    (False, "saturday", "semi"): 2.41,
    (False, "sunday", "off"): 2.32,
}
BASIC_RATES = {
    (True, "peak"): 223.60,
    (True, "semi"): 166.90,
    (True, "sat_semi"): 44.70,
    (True, "off"): 44.70,
    (False, "peak"): 166.90,
    (False, "semi"): 166.90,
    (False, "sat_semi"): 33.30,
    (False, "off"): 33.30,
}


@dataclass(frozen=True)
class Contracts:
    regular_kw: float = 400.0
    semi_peak_kw: float = 50.0
    saturday_semi_peak_kw: float = 0.0
    off_peak_kw: float = 50.0

    def capacities(self) -> np.ndarray:
        return np.asarray(
            [
                self.regular_kw,
                self.regular_kw + self.semi_peak_kw,
                self.regular_kw + self.semi_peak_kw + self.saturday_semi_peak_kw,
                self.regular_kw
                + self.semi_peak_kw
                + self.saturday_semi_peak_kw
                + self.off_peak_kw,
            ],
            dtype=float,
        )


@dataclass(frozen=True)
class AnnualPlanConfig:
    planning_year: int = 2026
    draws: int = 1000
    scenarios: int = 10
    seed: int = 42
    p_grid: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.30)
    timestep_hours: float = 0.25
    lock_steps: int = 4
    days: int = 365


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _json_dump(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _is_summer(ts: pd.Timestamp) -> bool:
    return (5 < ts.month < 10) or (ts.month == 5 and ts.day >= 16) or (ts.month == 10 and ts.day <= 15)


def _tou_period(ts: pd.Timestamp) -> str:
    if ts.weekday() == 6:
        return "off"
    hour = ts.hour
    if _is_summer(ts):
        if ts.weekday() < 5:
            if 16 <= hour < 22:
                return "peak"
            if (9 <= hour < 16) or 22 <= hour < 24:
                return "semi"
            return "off"
        return "sat_semi" if 9 <= hour < 24 else "off"
    if ts.weekday() < 5:
        return "semi" if (6 <= hour < 11) or (14 <= hour < 24) else "off"
    return "sat_semi" if (6 <= hour < 11) or (14 <= hour < 24) else "off"


def _day_kind(ts: pd.Timestamp) -> str:
    if ts.weekday() == 6:
        return "sunday"
    if ts.weekday() == 5:
        return "saturday"
    return "weekday"


def _energy_rate(ts: pd.Timestamp) -> float:
    period = _tou_period(ts)
    lookup_period = "semi" if period == "sat_semi" else period
    return ENERGY_RATES[(_is_summer(ts), _day_kind(ts), lookup_period)]


def _basic_charge(ts: pd.Timestamp, contracts: Contracts) -> float:
    summer = _is_summer(ts)
    return (
        contracts.regular_kw * BASIC_RATES[(summer, "peak")]
        + contracts.semi_peak_kw * BASIC_RATES[(summer, "semi")]
        + contracts.saturday_semi_peak_kw * BASIC_RATES[(summer, "sat_semi")]
        + contracts.off_peak_kw * BASIC_RATES[(summer, "off")]
    )


def _period_rates(ts: pd.Timestamp) -> np.ndarray:
    summer = _is_summer(ts)
    return np.asarray([BASIC_RATES[(summer, period)] for period in PERIODS], dtype=float)


def _excess_charge_from_peaks(peaks: Iterable[float], ts: pd.Timestamp, contracts: Contracts) -> float:
    capacities = contracts.capacities()
    rates = _period_rates(ts)
    previous = 0.0
    charge = 0.0
    for peak, capacity, rate in zip(peaks, capacities, rates, strict=True):
        raw = max(0.0, float(peak) - float(capacity))
        billed = max(0.0, raw - previous)
        previous = max(previous, raw)
        first = min(billed, 0.1 * float(capacity))
        charge += first * float(rate) * 2.0 + (billed - first) * float(rate) * 3.0
    return charge


def _complete_profile_map(frame: pd.DataFrame, timestamp: str, value: str, planning_dates: pd.DatetimeIndex) -> np.ndarray:
    work = frame[[timestamp, value]].copy()
    work[timestamp] = pd.to_datetime(work[timestamp])
    work["date"] = work[timestamp].dt.date
    work["slot"] = work[timestamp].dt.hour * 4 + work[timestamp].dt.minute // 15
    profiles: dict[tuple[int, int], np.ndarray] = {}
    for date, day in work.groupby("date", sort=True):
        day = day.drop_duplicates("slot").set_index("slot").reindex(range(96))
        if not day[value].isna().any():
            profiles[(date.month, date.day)] = day[value].to_numpy(dtype=float)
    if not profiles:
        raise ValueError(f"no complete daily profiles found for {value}")

    keys = list(profiles)
    result = []
    for target in planning_dates:
        key = (target.month, target.day)
        if key not in profiles:
            candidates = [candidate for candidate in keys if candidate[0] == target.month]
            if not candidates:
                candidates = keys
            key = min(candidates, key=lambda candidate: abs(candidate[1] - target.day))
        result.append(profiles[key])
    return np.stack(result)


def _load_base_profiles(ems_root: Path, planning_dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    load_frames = []
    for name in ("Steel_industry_data.csv", "Steel_industry_data_predict.csv"):
        path = ems_root / name
        frame = pd.read_csv(path)
        frame["timestamp"] = pd.to_datetime(frame["date"], dayfirst=True, format="%d/%m/%Y %H:%M")
        frame["load_kw"] = pd.to_numeric(frame["Usage_kWh"], errors="raise") / 0.25
        load_frames.append(frame[["timestamp", "load_kw"]])
    load_rows = pd.concat(load_frames, ignore_index=True).drop_duplicates("timestamp", keep="last")

    pv_rows = pd.read_csv(ems_root / "Renewable.csv")
    pv_rows["source_timestamp"] = pd.to_datetime(pv_rows["Time"], format="%Y-%m-%d %H:%M:%S")
    pv_rows = pv_rows[pv_rows["source_timestamp"].dt.year == 2017].copy()
    pv_rows["timestamp"] = pv_rows["source_timestamp"].map(
        lambda ts: ts.replace(year=planning_dates[0].year)
    )
    pv_rows["pv_kw"] = pd.to_numeric(pv_rows["Energy delta[Wh]"], errors="raise") * 17.0 / 1000.0 / 0.25

    load = _complete_profile_map(load_rows, "timestamp", "load_kw", planning_dates)
    pv = _complete_profile_map(pv_rows, "timestamp", "pv_kw", planning_dates)
    return load, pv, {
        "load_source": "Steel_industry_data.csv + Steel_industry_data_predict.csv",
        "pv_source": "Renewable.csv calendar-aligned 2017 profiles",
        "pv_scale_factor": 17.0,
        "joint_data_limitation": "Load and PV are calendar-aligned cross-year analogues because same-year PV records are unavailable.",
    }


def _circular_distance(a: int, b: int) -> int:
    distance = abs(a - b)
    return min(distance, 365 - distance)


def _bootstrap_indices(draws: int, days: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    result = np.empty((draws, days), dtype=np.int16)
    for draw in range(draws):
        for start in range(0, days, 7):
            target = start % 365
            candidates = [i for i in range(365) if _circular_distance(i, target) <= 45]
            source = int(rng.choice(candidates))
            width = min(7, days - start)
            result[draw, start : start + width] = [(source + offset) % 365 for offset in range(width)]
    return result


def _path_features(indices: np.ndarray, load: np.ndarray, pv: np.ndarray, dates: pd.DatetimeIndex) -> np.ndarray:
    features = np.empty((len(indices), 48), dtype=float)
    for row_index, path in enumerate(indices):
        path_load = load[path]
        path_pv = pv[path]
        values = []
        for month in range(1, 13):
            mask = dates.month == month
            if not mask.any():
                values.extend([0.0, 0.0, 0.0, 0.0])
                continue
            net = path_load[mask] - path_pv[mask]
            values.extend(
                [
                    float(path_load[mask].sum() * 0.25),
                    float(path_pv[mask].sum() * 0.25),
                    float(net.max()),
                    float(np.quantile(net, 0.95)),
                ]
            )
        features[row_index] = values
    mean = features.mean(axis=0)
    scale = features.std(axis=0)
    return (features - mean) / np.where(scale > 1e-8, scale, 1.0)


def _scenario_paths(
    load: np.ndarray,
    pv: np.ndarray,
    dates: pd.DatetimeIndex,
    config: AnnualPlanConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    indices = _bootstrap_indices(config.draws, len(dates), config.seed)
    features = _path_features(indices, load, pv, dates)
    cluster_count = max(1, config.scenarios - 2)
    fitted = KMeans(n_clusters=cluster_count, random_state=config.seed, n_init=20).fit(features)
    selected = []
    for center in fitted.cluster_centers_:
        index = int(np.argmin(np.sum((features - center) ** 2, axis=1)))
        if index not in selected:
            selected.append(index)
    while len(selected) < cluster_count:
        distance = np.min(
            np.stack([np.sum((features - features[index]) ** 2, axis=1) for index in selected]),
            axis=0,
        )
        distance[selected] = -1.0
        selected.append(int(np.argmax(distance)))
    selected = selected[:cluster_count]

    selected_features = features[selected]
    assignments = np.argmin(
        np.sum((features[:, None, :] - selected_features[None, :, :]) ** 2, axis=2),
        axis=1,
    )
    counts = np.bincount(assignments, minlength=len(selected)).astype(float)
    medoid_probabilities = counts / counts.sum() * 0.98
    scenario_load = [load[indices[index]] for index in selected]
    scenario_pv = [pv[indices[index]] for index in selected]

    high_load = np.empty((len(dates), 96), dtype=float)
    high_pv = np.empty_like(high_load)
    low_load = np.empty_like(high_load)
    low_pv = np.empty_like(high_load)
    slots = np.arange(96)
    for day in range(len(dates)):
        candidate_load = load[indices[:, day]]
        candidate_pv = pv[indices[:, day]]
        candidate_net = candidate_load - candidate_pv
        high_index = np.argmax(candidate_net, axis=0)
        low_index = np.argmin(candidate_net, axis=0)
        high_load[day] = candidate_load[high_index, slots]
        high_pv[day] = candidate_pv[high_index, slots]
        low_load[day] = candidate_load[low_index, slots]
        low_pv[day] = candidate_pv[low_index, slots]
    scenario_load.extend((high_load, low_load))
    scenario_pv.extend((high_pv, low_pv))
    scenario_load = np.stack(scenario_load)
    scenario_pv = np.stack(scenario_pv)
    probabilities = np.concatenate([medoid_probabilities, np.asarray([0.01, 0.01])])
    actual_net = load[: len(dates)] - pv[: len(dates)]
    coverage = np.mean(
        (actual_net >= (scenario_load - scenario_pv).min(axis=0))
        & (actual_net <= (scenario_load - scenario_pv).max(axis=0))
    )
    return scenario_load, scenario_pv, probabilities, {
        "method": (
            f"paired_7_day_block_bootstrap_with_{cluster_count}_medoids_"
            "and_2_paired_stress_envelopes"
        ),
        "draws": config.draws,
        "selected_draws": selected,
        "stress_scenarios": ["high_net_load_envelope", "low_net_load_envelope"],
        "probabilities": probabilities.tolist(),
        "net_load_pointwise_envelope_coverage": float(coverage),
        "coverage_target": 0.90,
        "coverage_passed": bool(coverage >= 0.90),
        "seed": config.seed,
    }


def _solve(model: pyo.ConcreteModel, config: SolverConfig) -> tuple[object, float]:
    solver = pyo.SolverFactory(config.name)
    if not solver.available(exception_flag=False):
        raise RuntimeError(f"solver {config.name!r} is not available")
    solver.options["time_limit"] = config.time_limit_seconds
    solver.options["mip_rel_gap"] = config.mip_gap
    solver.options["threads"] = config.threads
    solver.options["random_seed"] = config.random_seed
    started = perf_counter()
    result = solver.solve(model, tee=False, load_solutions=False)
    if len(result.solution) > 0:
        model.solutions.load_from(result)
    return result, perf_counter() - started


def _feasible(result: object) -> bool:
    return len(result.solution) > 0 and result.solver.termination_condition in {
        TerminationCondition.optimal,
        TerminationCondition.feasible,
        TerminationCondition.maxTimeLimit,
    }


def _build_dispatch_model(
    load: np.ndarray,
    pv: np.ndarray,
    probabilities: np.ndarray,
    timestamps: pd.DatetimeIndex,
    prior_peaks: np.ndarray,
    *,
    initial_soc: float,
    battery: BatteryConfig,
    contracts: Contracts,
    solver_config: AnnualPlanConfig,
    oracle_costs: np.ndarray | None = None,
    p_limit: float | None = None,
    minimize_p: bool = False,
) -> pyo.ConcreteModel:
    scenario_count, horizon = load.shape
    prices = np.asarray([_energy_rate(ts) for ts in timestamps], dtype=float)
    period_names = [_tou_period(ts) for ts in timestamps]
    period_index = np.asarray([PERIODS.index(name) for name in period_names], dtype=int)
    capacities = contracts.capacities()
    rates = _period_rates(timestamps[0])
    existing_charge = np.asarray(
        [_excess_charge_from_peaks(prior_peaks[s], timestamps[0], contracts) for s in range(scenario_count)]
    )

    model = pyo.ConcreteModel("annual_daily_p_robust")
    model.S = pyo.RangeSet(0, scenario_count - 1)
    model.T = pyo.RangeSet(0, horizon - 1)
    model.TSOC = pyo.RangeSet(0, horizon)
    model.P = pyo.RangeSet(0, len(PERIODS) - 1)
    model.charge = pyo.Var(model.S, model.T, bounds=(0.0, battery.charge_max_kw))
    model.discharge = pyo.Var(model.S, model.T, bounds=(0.0, battery.discharge_max_kw))
    model.mode = pyo.Var(model.S, model.T, domain=pyo.Binary)
    model.soc = pyo.Var(model.S, model.TSOC, bounds=(battery.soc_min, battery.soc_max))
    model.grid = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.curtail = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.period_peak = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.raw_excess = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.running_excess = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.billed_excess = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.first_band = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.second_band = pyo.Var(model.S, model.P, domain=pyo.NonNegativeReals)
    model.constraints = pyo.ConstraintList()
    for s in range(scenario_count):
        model.soc[s, 0].fix(initial_soc)
        model.constraints.add(model.soc[s, horizon] >= battery.soc_target)
        for t in range(horizon):
            model.constraints.add(model.charge[s, t] <= battery.charge_max_kw * model.mode[s, t])
            model.constraints.add(
                model.discharge[s, t] <= battery.discharge_max_kw * (1.0 - model.mode[s, t])
            )
            model.constraints.add(model.discharge[s, t] <= max(0.0, float(load[s, t] - pv[s, t])))
            model.constraints.add(
                model.soc[s, t + 1]
                == model.soc[s, t]
                + battery.eta_charge
                * model.charge[s, t]
                * solver_config.timestep_hours
                / battery.capacity_kwh
                - model.discharge[s, t]
                * solver_config.timestep_hours
                / (battery.eta_discharge * battery.capacity_kwh)
            )
            model.constraints.add(
                model.grid[s, t]
                + model.discharge[s, t]
                + float(pv[s, t])
                - model.curtail[s, t]
                == float(load[s, t]) + model.charge[s, t]
            )
            model.constraints.add(model.curtail[s, t] <= float(pv[s, t]))
            model.constraints.add(model.period_peak[s, int(period_index[t])] >= model.grid[s, t])

    for s in range(1, scenario_count):
        for t in range(min(solver_config.lock_steps, horizon)):
            model.constraints.add(model.charge[s, t] == model.charge[0, t])
            model.constraints.add(model.discharge[s, t] == model.discharge[0, t])
            model.constraints.add(model.mode[s, t] == model.mode[0, t])

    for s in range(scenario_count):
        for period in range(len(PERIODS)):
            model.constraints.add(model.period_peak[s, period] >= float(prior_peaks[s, period]))
            model.constraints.add(
                model.raw_excess[s, period] >= model.period_peak[s, period] - float(capacities[period])
            )
            if period == 0:
                model.constraints.add(model.running_excess[s, period] >= model.raw_excess[s, period])
                model.constraints.add(model.billed_excess[s, period] >= model.running_excess[s, period])
            else:
                model.constraints.add(model.running_excess[s, period] >= model.raw_excess[s, period])
                model.constraints.add(model.running_excess[s, period] >= model.running_excess[s, period - 1])
                model.constraints.add(
                    model.billed_excess[s, period]
                    >= model.running_excess[s, period] - model.running_excess[s, period - 1]
                )
            model.constraints.add(model.first_band[s, period] <= 0.1 * float(capacities[period]))
            model.constraints.add(
                model.first_band[s, period] + model.second_band[s, period]
                >= model.billed_excess[s, period]
            )

    model.scenario_cost = pyo.Expression(
        model.S,
        rule=lambda m, s: sum(
            m.grid[s, t] * float(prices[t]) * solver_config.timestep_hours
            + battery.degradation_yuan_per_kwh
            * (m.charge[s, t] + m.discharge[s, t])
            * solver_config.timestep_hours
            for t in m.T
        )
        + sum(
            2.0 * float(rates[p]) * m.first_band[s, p]
            + 3.0 * float(rates[p]) * m.second_band[s, p]
            for p in m.P
        )
        - float(existing_charge[s]),
    )
    model.expected_cost = pyo.Expression(
        expr=sum(float(probabilities[s]) * model.scenario_cost[s] for s in model.S)
    )
    if oracle_costs is None:
        model.objective = pyo.Objective(expr=model.expected_cost, sense=pyo.minimize)
    elif minimize_p:
        model.rho = pyo.Var(domain=pyo.NonNegativeReals)
        model.regret = pyo.Constraint(
            model.S,
            rule=lambda m, s: m.scenario_cost[s] <= (1.0 + m.rho) * float(oracle_costs[s]),
        )
        model.objective = pyo.Objective(expr=model.rho, sense=pyo.minimize)
    else:
        if p_limit is None:
            raise ValueError("p_limit is required for fixed-p dispatch")
        model.regret = pyo.Constraint(
            model.S,
            rule=lambda m, s: m.scenario_cost[s] <= (1.0 + p_limit) * float(oracle_costs[s]),
        )
        model.objective = pyo.Objective(expr=model.expected_cost, sense=pyo.minimize)
    return model


def _extract_dispatch(model: pyo.ConcreteModel, result: object, seconds: float, oracle_costs: np.ndarray | None) -> dict[str, object]:
    if not _feasible(result):
        return {
            "status": "infeasible",
            "termination": str(result.solver.termination_condition),
            "solveSeconds": seconds,
        }
    costs = np.asarray([pyo.value(model.scenario_cost[s]) for s in model.S], dtype=float)
    return {
        "status": "optimal" if result.solver.termination_condition == TerminationCondition.optimal else "feasible",
        "termination": str(result.solver.termination_condition),
        "solveSeconds": seconds,
        "p": float(pyo.value(model.rho)) if hasattr(model, "rho") else None,
        "objective": float(pyo.value(model.expected_cost)),
        "scenarioCosts": costs,
        "regrets": None if oracle_costs is None else costs / oracle_costs - 1.0,
        "charge": np.asarray(
            [[pyo.value(model.charge[s, t]) for t in model.T] for s in model.S], dtype=float
        ),
        "discharge": np.asarray(
            [[pyo.value(model.discharge[s, t]) for t in model.T] for s in model.S], dtype=float
        ),
        "soc": np.asarray(
            [[pyo.value(model.soc[s, t]) for t in model.TSOC] for s in model.S], dtype=float
        ),
        "grid": np.asarray(
            [[pyo.value(model.grid[s, t]) for t in model.T] for s in model.S], dtype=float
        ),
        "curtail": np.asarray(
            [[pyo.value(model.curtail[s, t]) for t in model.T] for s in model.S], dtype=float
        ),
        "periodPeaks": np.asarray(
            [[pyo.value(model.period_peak[s, p]) for p in model.P] for s in model.S], dtype=float
        ),
    }


def _dispatch(
    load: np.ndarray,
    pv: np.ndarray,
    probabilities: np.ndarray,
    timestamps: pd.DatetimeIndex,
    prior_peaks: np.ndarray,
    initial_soc: float,
    battery: BatteryConfig,
    contracts: Contracts,
    plan: AnnualPlanConfig,
    solver: SolverConfig,
    *,
    p_limit: float | None = None,
    minimize_p: bool = False,
) -> dict[str, object]:
    oracle_costs = None
    if p_limit is not None or minimize_p:
        oracle_costs = []
        for scenario in range(len(load)):
            model = _build_dispatch_model(
                load[scenario : scenario + 1],
                pv[scenario : scenario + 1],
                np.asarray([1.0]),
                timestamps,
                prior_peaks[scenario : scenario + 1],
                initial_soc=initial_soc,
                battery=battery,
                contracts=contracts,
                solver_config=plan,
            )
            result, _ = _solve(model, solver)
            if not _feasible(result):
                raise RuntimeError(f"oracle scenario {scenario} failed: {result.solver.termination_condition}")
            oracle_costs.append(float(pyo.value(model.scenario_cost[0])))
        oracle_costs = np.asarray(oracle_costs, dtype=float)
        if np.any(oracle_costs <= 1e-8):
            raise RuntimeError("oracle costs must remain positive")

    model = _build_dispatch_model(
        load,
        pv,
        probabilities,
        timestamps,
        prior_peaks,
        initial_soc=initial_soc,
        battery=battery,
        contracts=contracts,
        solver_config=plan,
        oracle_costs=oracle_costs,
        p_limit=p_limit,
        minimize_p=minimize_p,
    )
    result, seconds = _solve(model, solver)
    return _extract_dispatch(model, result, seconds, oracle_costs)


def _weighted_quantile(values: np.ndarray, probabilities: np.ndarray, quantile: float) -> float:
    order = np.argsort(values)
    cumulative = np.cumsum(probabilities[order])
    return float(values[order[np.searchsorted(cumulative, quantile, side="left")]])


def _point_forecast(paths: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    order = np.argsort(paths, axis=0)
    sorted_values = np.take_along_axis(paths, order, axis=0)
    sorted_weights = np.take_along_axis(
        np.broadcast_to(probabilities[:, None], paths.shape), order, axis=0
    )
    positions = np.argmax(np.cumsum(sorted_weights, axis=0) >= 0.5, axis=0)
    return sorted_values[positions, np.arange(paths.shape[1])]


def _select_policy_branch(
    actual_load: np.ndarray,
    actual_pv: np.ndarray,
    scenario_load: np.ndarray,
    scenario_pv: np.ndarray,
    lock_steps: int,
) -> int:
    observed = max(1, min(lock_steps, actual_load.shape[0]))
    load_scale = max(float(np.mean(actual_load[:observed])), 1.0)
    pv_scale = max(float(np.max(actual_pv[:observed])), 1.0)
    distance = np.mean(
        ((scenario_load[:, :observed] - actual_load[None, :observed]) / load_scale) ** 2
        + ((scenario_pv[:, :observed] - actual_pv[None, :observed]) / pv_scale) ** 2,
        axis=1,
    )
    return int(np.argmin(distance))


def _settle(
    load: np.ndarray,
    pv: np.ndarray,
    charge: np.ndarray,
    discharge: np.ndarray,
    timestamps: pd.DatetimeIndex,
    initial_soc: float,
    battery: BatteryConfig,
    contracts: Contracts,
) -> dict[str, object]:
    soc = initial_soc
    actual_charge = []
    actual_discharge = []
    grid = []
    curtail = []
    soc_rows = [soc]
    projections = 0
    for t in range(len(timestamps)):
        max_charge = max(0.0, (battery.soc_max - soc) * battery.capacity_kwh / (battery.eta_charge * 0.25))
        max_discharge = max(0.0, (soc - battery.soc_min) * battery.capacity_kwh * battery.eta_discharge / 0.25)
        ch = min(float(charge[t]), max_charge)
        dis = min(float(discharge[t]), max(0.0, float(load[t] - pv[t])), max_discharge)
        projections += int(abs(ch - charge[t]) > 1e-6 or abs(dis - discharge[t]) > 1e-6)
        grid_value = max(0.0, float(load[t] + ch - dis - pv[t]))
        curtail_value = max(0.0, float(pv[t] + dis - load[t] - ch))
        soc += battery.eta_charge * ch * 0.25 / battery.capacity_kwh
        soc -= dis * 0.25 / (battery.eta_discharge * battery.capacity_kwh)
        actual_charge.append(ch)
        actual_discharge.append(dis)
        grid.append(grid_value)
        curtail.append(curtail_value)
        soc_rows.append(soc)
    prices = np.asarray([_energy_rate(ts) for ts in timestamps])
    capacities = contracts.capacities()
    periods = np.asarray([PERIODS.index(_tou_period(ts)) for ts in timestamps])
    return {
        "charge": np.asarray(actual_charge),
        "discharge": np.asarray(actual_discharge),
        "grid": np.asarray(grid),
        "curtail": np.asarray(curtail),
        "soc": np.asarray(soc_rows),
        "finalSoc": soc,
        "energyCost": float(np.sum(np.asarray(grid) * prices * 0.25)),
        "degradationCost": float(
            np.sum((np.asarray(actual_charge) + np.asarray(actual_discharge)) * 0.25)
            * battery.degradation_yuan_per_kwh
        ),
        "overContractEvents": int(
            np.sum(np.asarray(grid) > capacities[periods] + 1e-6)
        ),
        "projectionCount": projections,
    }


def _update_peaks(peaks: np.ndarray, grid: np.ndarray, timestamps: pd.DatetimeIndex) -> np.ndarray:
    updated = np.asarray(peaks, dtype=float).copy()
    for period, name in enumerate(PERIODS):
        mask = np.asarray([_tou_period(ts) == name for ts in timestamps])
        if mask.any():
            updated[period] = max(updated[period], float(grid[mask].max()))
    return updated


def _new_month_accumulator() -> dict[str, float | np.ndarray]:
    return {
        "energyCost": 0.0,
        "degradationCost": 0.0,
        "gridEnergyKwh": 0.0,
        "pvEnergyKwh": 0.0,
        "pvUsedKwh": 0.0,
        "curtailmentKwh": 0.0,
        "overContractEvents": 0.0,
        "periodPeaks": np.zeros(4),
    }


def _accumulate(
    accumulator: dict[str, float | np.ndarray],
    settlement: dict[str, object],
    load: np.ndarray,
    pv: np.ndarray,
    timestamps: pd.DatetimeIndex,
) -> None:
    accumulator["energyCost"] = float(accumulator["energyCost"]) + float(settlement["energyCost"])
    accumulator["degradationCost"] = float(accumulator["degradationCost"]) + float(settlement["degradationCost"])
    accumulator["gridEnergyKwh"] = float(accumulator["gridEnergyKwh"]) + float(np.sum(settlement["grid"]) * 0.25)
    accumulator["pvEnergyKwh"] = float(accumulator["pvEnergyKwh"]) + float(np.sum(pv) * 0.25)
    accumulator["curtailmentKwh"] = float(accumulator["curtailmentKwh"]) + float(np.sum(settlement["curtail"]) * 0.25)
    accumulator["pvUsedKwh"] = float(accumulator["pvUsedKwh"]) + float(
        np.sum(pv - settlement["curtail"]) * 0.25
    )
    accumulator["overContractEvents"] = float(accumulator["overContractEvents"]) + int(
        settlement["overContractEvents"]
    )
    accumulator["periodPeaks"] = _update_peaks(
        np.asarray(accumulator["periodPeaks"]), np.asarray(settlement["grid"]), timestamps
    )


def _finalize_month(
    month: int,
    accumulator: dict[str, float | np.ndarray],
    reference: pd.Timestamp,
    contracts: Contracts,
) -> dict[str, object]:
    basic = _basic_charge(reference, contracts)
    excess = _excess_charge_from_peaks(accumulator["periodPeaks"], reference, contracts)
    total = float(accumulator["energyCost"]) + float(accumulator["degradationCost"]) + basic + excess
    pv_energy = float(accumulator["pvEnergyKwh"])
    return {
        "month": month,
        "label": f"{month}月",
        "totalCost": _round(total, 0),
        "energyCost": _round(accumulator["energyCost"], 0),
        "basicCost": _round(basic, 0),
        "excessCost": _round(excess, 0),
        "degradationCost": _round(accumulator["degradationCost"], 0),
        "gridEnergyKwh": _round(accumulator["gridEnergyKwh"], 1),
        "peakGridKw": _round(np.max(accumulator["periodPeaks"]), 1),
        "overContractEvents": int(accumulator["overContractEvents"]),
        "pvUtilization": _round(100.0 * float(accumulator["pvUsedKwh"]) / pv_energy, 1) if pv_energy else 0.0,
        "curtailmentKwh": _round(accumulator["curtailmentKwh"], 1),
    }


def _calibrate_p(
    scenario_load: np.ndarray,
    scenario_pv: np.ndarray,
    probabilities: np.ndarray,
    dates: pd.DatetimeIndex,
    battery: BatteryConfig,
    contracts: Contracts,
    plan: AnnualPlanConfig,
    solver: SolverConfig,
) -> dict[str, object]:
    cases = []
    capacities = contracts.capacities()
    for month in range(1, 13):
        month_days = np.flatnonzero(dates.month == month)
        if not len(month_days):
            continue
        positions = sorted({min(7, len(month_days) - 1), min(21, len(month_days) - 1)})
        for position in positions:
            day_index = int(month_days[position])
            timestamps = pd.date_range(dates[day_index], periods=96, freq="15min")
            for state_name, peaks in (("month_start", np.zeros(4)), ("near_contract", capacities)):
                result = _dispatch(
                    scenario_load[:, day_index],
                    scenario_pv[:, day_index],
                    probabilities,
                    timestamps,
                    np.broadcast_to(peaks, (len(probabilities), 4)).copy(),
                    0.50,
                    battery,
                    contracts,
                    plan,
                    solver,
                    minimize_p=True,
                )
                if result["status"] == "infeasible":
                    raise RuntimeError(f"p calibration failed for month {month} {state_name}")
                cases.append(
                    {
                        "month": month,
                        "day": int(position + 1),
                        "state": state_name,
                        "pMin": _round(result["p"], 6),
                        "solveSeconds": _round(result["solveSeconds"], 3),
                    }
                )
    p95 = float(np.quantile([case["pMin"] for case in cases], 0.95))
    selected = next((value for value in plan.p_grid if value + 1e-8 >= p95), None)
    if selected is None:
        raise RuntimeError(f"minimum calibrated p={p95:.4f} exceeds the allowed grid")
    return {"cases": cases, "p95Minimum": p95, "selectedP": selected, "grid": list(plan.p_grid)}


def _solve_frontier(
    scenario_load: np.ndarray,
    scenario_pv: np.ndarray,
    probabilities: np.ndarray,
    dates: pd.DatetimeIndex,
    battery: BatteryConfig,
    contracts: Contracts,
    plan: AnnualPlanConfig,
    solver: SolverConfig,
    selected_p: float,
) -> list[dict[str, object]]:
    preferred = np.flatnonzero((dates.month == 7) & (dates.day == 15))
    day_index = int(preferred[0]) if len(preferred) else len(dates) // 2
    timestamps = pd.date_range(dates[day_index], periods=96, freq="15min")
    prior_peaks = np.zeros((len(probabilities), 4))
    capacities = contracts.capacities()
    periods = np.asarray([PERIODS.index(_tou_period(ts)) for ts in timestamps])
    rows = []
    for value in plan.p_grid:
        result = _dispatch(
            scenario_load[:, day_index],
            scenario_pv[:, day_index],
            probabilities,
            timestamps,
            prior_peaks,
            0.50,
            battery,
            contracts,
            plan,
            solver,
            p_limit=value,
        )
        if result["status"] == "infeasible":
            rows.append(
                {
                    "p": value,
                    "status": "infeasible",
                    "selected": abs(value - selected_p) < 1e-8,
                }
            )
            continue
        grid = np.asarray(result["grid"])
        event_counts = np.sum(grid > capacities[periods][None, :] + 1e-6, axis=1)
        rows.append(
            {
                "p": value,
                "status": "solved",
                "scope": "representative_day",
                "month": int(dates[day_index].month),
                "day": int(dates[day_index].day),
                "expectedCost": _round(result["objective"], 0),
                "worstCost": _round(np.max(result["scenarioCosts"]), 0),
                "overContractEvents": _round(np.sum(event_counts * probabilities), 1),
                "regretCoverage": _round(
                    np.mean(np.asarray(result["regrets"]) <= value + 1e-6) * 100, 1
                ),
                "selected": abs(value - selected_p) < 1e-8,
            }
        )
    return rows


def _strategy_summary(
    key: str,
    label: str,
    monthly: list[dict[str, object]],
    scenario_costs: np.ndarray,
    probabilities: np.ndarray,
) -> dict[str, object]:
    total = sum(float(row["totalCost"]) for row in monthly)
    return {
        "key": key,
        "label": label,
        "annualCost": _round(total, 0),
        "p50Cost": _round(_weighted_quantile(scenario_costs, probabilities, 0.50), 0),
        "p90Cost": _round(_weighted_quantile(scenario_costs, probabilities, 0.90), 0),
        "worstCost": _round(np.max(scenario_costs), 0),
        "overContractEvents": int(sum(int(row["overContractEvents"]) for row in monthly)),
        "peakGridKw": _round(max(float(row["peakGridKw"]) for row in monthly), 1),
        "pvUtilization": _round(np.mean([float(row["pvUtilization"]) for row in monthly]), 1),
    }


def run_annual_plan(
    config: AnnualPlanConfig,
    *,
    ems_root: Path = DEFAULT_EMS_ROOT,
    output_dir: Path = PROJECT_DIR / "model_results" / "robust" / "annual_planning",
) -> dict[str, object]:
    if config.scenarios < 3 or config.draws < config.scenarios:
        raise ValueError("draws and scenarios are inconsistent")
    planning_dates = pd.date_range(f"{config.planning_year}-01-01", periods=config.days, freq="D")
    full_dates = pd.date_range(f"{config.planning_year}-01-01", periods=365, freq="D")
    full_load, full_pv, source_metadata = _load_base_profiles(ems_root, full_dates)
    scenario_load, scenario_pv, probabilities, scenario_metadata = _scenario_paths(
        full_load, full_pv, planning_dates, config
    )
    optimization_load = scenario_load[:-2]
    optimization_pv = scenario_pv[:-2]
    optimization_probabilities = probabilities[:-2] / probabilities[:-2].sum()
    optimization_count = len(optimization_probabilities)
    load = full_load[: config.days]
    pv = full_pv[: config.days]
    battery = BatteryConfig(
        capacity_kwh=400.0,
        soc_min=0.10,
        soc_max=0.90,
        soc_target=0.50,
        charge_max_kw=200.0,
        discharge_max_kw=200.0,
        eta_charge=0.95,
        eta_discharge=0.95,
        degradation_yuan_per_kwh=1.0,
    )
    contracts = Contracts()
    solver = SolverConfig(time_limit_seconds=30.0, mip_gap=1e-3, threads=1, random_seed=config.seed)
    calibration = _calibrate_p(
        optimization_load,
        optimization_pv,
        optimization_probabilities,
        planning_dates,
        battery,
        contracts,
        config,
        solver,
    )
    p_limit = float(calibration["selectedP"])
    frontier = _solve_frontier(
        optimization_load,
        optimization_pv,
        optimization_probabilities,
        planning_dates,
        battery,
        contracts,
        config,
        solver,
        p_limit,
    )

    monthly = {key: [] for key in ("allGrid", "pvOnly", "deterministic", "robust")}
    accumulators = {key: _new_month_accumulator() for key in monthly}
    actual_peaks = {"deterministic": np.zeros(4), "robust": np.zeros(4)}
    robust_scenario_peaks = np.zeros((optimization_count, 4))
    deterministic_scenario_peaks = np.zeros((optimization_count, 4))
    robust_scenario_costs = np.zeros(optimization_count)
    deterministic_scenario_costs = np.zeros(optimization_count)
    robust_soc = 0.50
    deterministic_soc = 0.50
    dispatch_rows = []
    presentation_days: dict[str, list[dict[str, object]]] = {str(month): [] for month in range(1, 13)}
    daily_solve_seconds = []
    daily_ex_post_regrets = []
    run_valid = True
    invalid_days = []

    for day_index, day in enumerate(planning_dates):
        timestamps = pd.date_range(day, periods=96, freq="15min")
        day_load = optimization_load[:, day_index]
        day_pv = optimization_pv[:, day_index]
        point_load = _point_forecast(day_load, optimization_probabilities)[None, :]
        point_pv = _point_forecast(day_pv, optimization_probabilities)[None, :]
        deterministic_day_start_soc = deterministic_soc
        robust_day_start_soc = robust_soc
        robust_actual_peaks_before = actual_peaks["robust"].copy()

        deterministic = _dispatch(
            point_load,
            point_pv,
            np.asarray([1.0]),
            timestamps,
            actual_peaks["deterministic"][None, :],
            deterministic_soc,
            battery,
            contracts,
            config,
            solver,
        )
        robust = _dispatch(
            day_load,
            day_pv,
            optimization_probabilities,
            timestamps,
            robust_scenario_peaks,
            robust_soc,
            battery,
            contracts,
            config,
            solver,
            p_limit=p_limit,
        )
        actual_oracle = _dispatch(
            load[day_index : day_index + 1],
            pv[day_index : day_index + 1],
            np.asarray([1.0]),
            timestamps,
            robust_actual_peaks_before[None, :],
            robust_day_start_soc,
            battery,
            contracts,
            config,
            solver,
        )
        if robust["status"] == "infeasible":
            diagnosis = _dispatch(
                day_load,
                day_pv,
                optimization_probabilities,
                timestamps,
                robust_scenario_peaks,
                robust_soc,
                battery,
                contracts,
                config,
                solver,
                minimize_p=True,
            )
            run_valid = False
            invalid_days.append({"month": day.month, "day": day.day, "pMin": diagnosis.get("p")})
            robust = diagnosis
        if deterministic["status"] == "infeasible" or robust["status"] == "infeasible":
            raise RuntimeError(f"dispatch failed on planning day {day_index + 1}")
        daily_solve_seconds.append(float(robust["solveSeconds"]))
        policy_branch = _select_policy_branch(
            load[day_index],
            pv[day_index],
            day_load,
            day_pv,
            config.lock_steps,
        )

        all_grid = _settle(load[day_index], np.zeros(96), np.zeros(96), np.zeros(96), timestamps, 0.50, battery, contracts)
        pv_only = _settle(load[day_index], pv[day_index], np.zeros(96), np.zeros(96), timestamps, 0.50, battery, contracts)
        deterministic_actual = _settle(
            load[day_index],
            pv[day_index],
            deterministic["charge"][0],
            deterministic["discharge"][0],
            timestamps,
            deterministic_day_start_soc,
            battery,
            contracts,
        )
        robust_actual = _settle(
            load[day_index],
            pv[day_index],
            robust["charge"][policy_branch],
            robust["discharge"][policy_branch],
            timestamps,
            robust_day_start_soc,
            battery,
            contracts,
        )
        deterministic_soc = float(deterministic_actual["finalSoc"])
        robust_soc = float(robust_actual["finalSoc"])
        actual_peaks["deterministic"] = _update_peaks(
            actual_peaks["deterministic"], deterministic_actual["grid"], timestamps
        )
        actual_peaks["robust"] = _update_peaks(actual_peaks["robust"], robust_actual["grid"], timestamps)
        robust_actual_cost = (
            float(robust_actual["energyCost"])
            + float(robust_actual["degradationCost"])
            + _excess_charge_from_peaks(actual_peaks["robust"], day, contracts)
            - _excess_charge_from_peaks(robust_actual_peaks_before, day, contracts)
        )
        actual_oracle_cost = float(actual_oracle["scenarioCosts"][0])
        daily_ex_post_regrets.append(max(0.0, robust_actual_cost / actual_oracle_cost - 1.0))
        robust_scenario_peaks = np.asarray(robust["periodPeaks"])
        robust_scenario_costs += np.asarray(robust["scenarioCosts"])

        for scenario in range(optimization_count):
            settlement = _settle(
                day_load[scenario],
                day_pv[scenario],
                deterministic["charge"][0],
                deterministic["discharge"][0],
                timestamps,
                deterministic_day_start_soc,
                battery,
                contracts,
            )
            deterministic_scenario_costs[scenario] += float(settlement["energyCost"]) + float(
                settlement["degradationCost"]
            )
            deterministic_scenario_peaks[scenario] = _update_peaks(
                deterministic_scenario_peaks[scenario], settlement["grid"], timestamps
            )

        for key, settlement, source_pv in (
            ("allGrid", all_grid, np.zeros(96)),
            ("pvOnly", pv_only, pv[day_index]),
            ("deterministic", deterministic_actual, pv[day_index]),
            ("robust", robust_actual, pv[day_index]),
        ):
            _accumulate(accumulators[key], settlement, load[day_index], source_pv, timestamps)

        selected_day = day.day in (8, 15, 22)
        net_paths = scenario_load[:, day_index] - scenario_pv[:, day_index]
        p10 = np.quantile(net_paths, 0.10, axis=0)
        p50 = np.quantile(net_paths, 0.50, axis=0)
        p90 = np.quantile(net_paths, 0.90, axis=0)
        day_rows = []
        for t, timestamp in enumerate(timestamps):
            row = {
                "month": day.month,
                "day": day.day,
                "time": timestamp.strftime("%H:%M"),
                "tou": _tou_period(timestamp),
                "contractKw": float(contracts.capacities()[PERIODS.index(_tou_period(timestamp))]),
                "loadKw": _round(load[day_index, t], 2),
                "pvKw": _round(pv[day_index, t], 2),
                "netP10Kw": _round(p10[t], 2),
                "netP50Kw": _round(p50[t], 2),
                "netP90Kw": _round(p90[t], 2),
                "deterministicGridKw": _round(deterministic_actual["grid"][t], 2),
                "deterministicChargeKw": _round(deterministic_actual["charge"][t], 2),
                "deterministicDischargeKw": _round(deterministic_actual["discharge"][t], 2),
                "deterministicSoc": _round(deterministic_actual["soc"][t + 1] * 100, 2),
                "robustGridKw": _round(robust_actual["grid"][t], 2),
                "robustChargeKw": _round(robust_actual["charge"][t], 2),
                "robustDischargeKw": _round(robust_actual["discharge"][t], 2),
                "robustSoc": _round(robust_actual["soc"][t + 1] * 100, 2),
            }
            dispatch_rows.append(row)
            if selected_day:
                day_rows.append(row)
        if selected_day:
            presentation_days[str(day.month)].append(
                {"day": day.day, "label": f"{day.day}日", "rows": day_rows}
            )

        next_day = planning_dates[day_index + 1] if day_index + 1 < len(planning_dates) else None
        if next_day is None or next_day.month != day.month:
            reference = day
            for key in monthly:
                if key in actual_peaks:
                    accumulators[key]["periodPeaks"] = actual_peaks[key].copy()
                monthly[key].append(_finalize_month(day.month, accumulators[key], reference, contracts))
                accumulators[key] = _new_month_accumulator()
            basic = _basic_charge(reference, contracts)
            robust_scenario_costs += basic
            for scenario in range(optimization_count):
                deterministic_scenario_costs[scenario] += basic + _excess_charge_from_peaks(
                    deterministic_scenario_peaks[scenario], reference, contracts
                )
            actual_peaks = {"deterministic": np.zeros(4), "robust": np.zeros(4)}
            robust_scenario_peaks = np.zeros((optimization_count, 4))
            deterministic_scenario_peaks = np.zeros((optimization_count, 4))

    def simple_scenario_costs(strategy: str) -> np.ndarray:
        costs = np.zeros(optimization_count)
        for scenario in range(optimization_count):
            for month in range(1, planning_dates[-1].month + 1):
                mask = planning_dates.month == month
                if not mask.any():
                    continue
                month_load = optimization_load[scenario, mask].reshape(-1)
                month_pv = optimization_pv[scenario, mask].reshape(-1)
                month_dates = planning_dates[mask]
                timestamps = pd.DatetimeIndex(
                    [date + pd.Timedelta(minutes=15 * slot) for date in month_dates for slot in range(96)]
                )
                grid = month_load if strategy == "allGrid" else np.maximum(0.0, month_load - month_pv)
                prices = np.asarray([_energy_rate(ts) for ts in timestamps])
                peaks = _update_peaks(np.zeros(4), grid, timestamps)
                costs[scenario] += float(np.sum(grid * prices * 0.25))
                costs[scenario] += _basic_charge(month_dates[0], contracts)
                costs[scenario] += _excess_charge_from_peaks(peaks, month_dates[0], contracts)
        return costs

    strategy_rows = [
        _strategy_summary("allGrid", "完全向台電買電", monthly["allGrid"], simple_scenario_costs("allGrid"), optimization_probabilities),
        _strategy_summary("pvOnly", "PV 自發自用", monthly["pvOnly"], simple_scenario_costs("pvOnly"), optimization_probabilities),
        _strategy_summary("deterministic", "確定性 MILP", monthly["deterministic"], deterministic_scenario_costs, optimization_probabilities),
        _strategy_summary("robust", "P-Robust MILP", monthly["robust"], robust_scenario_costs, optimization_probabilities),
    ]
    by_key = {row["key"]: row for row in strategy_rows}
    all_grid_cost = float(by_key["allGrid"]["annualCost"])
    robust_cost = float(by_key["robust"]["annualCost"])
    deterministic_cost = float(by_key["deterministic"]["annualCost"])
    downside_reduction = float(by_key["deterministic"]["p90Cost"]) - float(by_key["robust"]["p90Cost"])

    monthly_comparison = []
    for month in range(1, len(monthly["robust"]) + 1):
        rows = {key: monthly[key][month - 1] for key in monthly}
        monthly_comparison.append(
            {
                "month": month,
                "label": f"{month}月",
                "allGridCost": rows["allGrid"]["totalCost"],
                "pvOnlyCost": rows["pvOnly"]["totalCost"],
                "deterministicCost": rows["deterministic"]["totalCost"],
                "robustCost": rows["robust"]["totalCost"],
                "savingsVsGrid": _round(rows["allGrid"]["totalCost"] - rows["robust"]["totalCost"], 0),
                "deterministicPeakKw": rows["deterministic"]["peakGridKw"],
                "robustPeakKw": rows["robust"]["peakGridKw"],
                "deterministicOverEvents": rows["deterministic"]["overContractEvents"],
                "robustOverEvents": rows["robust"]["overContractEvents"],
                "pvUtilization": rows["robust"]["pvUtilization"],
            }
        )

    valid = run_valid and bool(scenario_metadata["coverage_passed"])
    ex_post_regrets = np.asarray(daily_ex_post_regrets, dtype=float)
    ex_post_coverage = float(np.mean(ex_post_regrets <= p_limit + 1e-8))
    ex_post_passed = ex_post_coverage >= 0.90
    run_id = f"annual-p-robust-s{config.scenarios}-seed{config.seed}"
    payload = {
        "meta": {
            "runId": run_id,
            "generatedAt": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
            "status": "valid" if valid else "invalid",
            "simulationLabel": "全年規劃模擬，非未來節費保證",
            "tariffVersion": "Taipower high-voltage three-period project profile, effective 2025-10-01",
            "seed": config.seed,
            "scenarioCount": config.scenarios,
            "optimizationScenarioCount": optimization_count,
            "stressScenarioCount": 2,
            "drawCount": config.draws,
            "solver": "HiGHS",
            "source": source_metadata,
            "invalidDays": invalid_days,
        },
        "executiveSummary": {
            "allGridAnnualCost": by_key["allGrid"]["annualCost"],
            "deterministicAnnualCost": by_key["deterministic"]["annualCost"],
            "robustAnnualCost": by_key["robust"]["annualCost"],
            "robustSavings": _round(all_grid_cost - robust_cost, 0),
            "robustSavingsRate": _round((all_grid_cost - robust_cost) / all_grid_cost * 100, 1),
            "robustPremium": _round(robust_cost - deterministic_cost, 0),
            "downsideReduction": _round(downside_reduction, 0),
            "selectedP": p_limit,
            "pvUtilization": by_key["robust"]["pvUtilization"],
            "businessConclusion": "以有限的穩健成本換取不利情境下更可控的電費與超約風險。",
        },
        "strategyComparison": strategy_rows,
        "monthlyComparison": monthly_comparison,
        "robustnessFrontier": frontier,
        "scenarioCoverage": {
            **scenario_metadata,
            "pCalibrationCases": len(calibration["cases"]),
            "p95Minimum": calibration["p95Minimum"],
            "selectedP": p_limit,
            "dailyMedianSolveSeconds": _round(np.median(daily_solve_seconds), 3),
            "dailyP95SolveSeconds": _round(np.quantile(daily_solve_seconds, 0.95), 3),
            "coverageEvaluation": (
                "The net-load envelope metric is an in-sample planning-path check. "
                "Independent daily ex-post regret is reported separately."
            ),
            "exPostRegretP50": _round(np.quantile(ex_post_regrets, 0.50), 4),
            "exPostRegretP90": _round(np.quantile(ex_post_regrets, 0.90), 4),
            "exPostRegretP95": _round(np.quantile(ex_post_regrets, 0.95), 4),
            "exPostRegretCoverage": _round(ex_post_coverage * 100.0, 1),
            "exPostRegretTarget": 90.0,
            "exPostRegretPassed": ex_post_passed,
        },
        "dailyDispatch": presentation_days,
        "billingBreakdown": {
            key: {
                "energyCost": _round(sum(float(row["energyCost"]) for row in monthly[key]), 0),
                "basicCost": _round(sum(float(row["basicCost"]) for row in monthly[key]), 0),
                "excessCost": _round(sum(float(row["excessCost"]) for row in monthly[key]), 0),
                "degradationCost": _round(sum(float(row["degradationCost"]) for row in monthly[key]), 0),
            }
            for key in monthly
        },
        "modelAssumptions": {
            "battery": asdict(battery),
            "contracts": asdict(contracts),
            "timestepMinutes": 15,
            "scenarioMethod": scenario_metadata["method"],
            "decisionStructure": (
                f"The first {config.lock_steps * 15} minutes are non-anticipative. "
                "The remaining dispatch follows the closest paired scenario branch selected "
                "from the observed first-hour load and PV trajectory."
            ),
            "jointDataLimitation": source_metadata["joint_data_limitation"],
            "regretDefinition": "Daily controllable cost divided by same-state perfect-information oracle cost minus one.",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    _json_dump(output_dir / "presentation.json", payload)
    _json_dump(output_dir / "summary.json", {"meta": payload["meta"], "executiveSummary": payload["executiveSummary"]})
    _json_dump(output_dir / "comparison.json", {"strategies": strategy_rows, "monthly": monthly_comparison})
    _json_dump(output_dir / "scenario_metadata.json", scenario_metadata)
    _json_dump(output_dir / "p_calibration.json", calibration)
    pd.DataFrame(monthly_comparison).to_csv(output_dir / "monthly_metrics.csv", index=False)
    pd.DataFrame(dispatch_rows).to_csv(output_dir / "daily_dispatch.csv", index=False)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ems-root", type=Path, default=DEFAULT_EMS_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_DIR / "model_results" / "robust" / "annual_planning",
    )
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--scenarios", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    payload = run_annual_plan(
        AnnualPlanConfig(
            draws=args.draws,
            scenarios=args.scenarios,
            seed=args.seed,
            days=args.days,
        ),
        ems_root=args.ems_root,
        output_dir=args.output_dir,
    )
    print(args.output_dir / "presentation.json")
    print(payload["meta"]["status"])


if __name__ == "__main__":
    main()
