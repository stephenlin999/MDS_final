"""Pyomo implementation of scenario-based P-robust battery dispatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from time import perf_counter
from typing import Sequence

import numpy as np
import pyomo.environ as pyo
from pyomo.opt import TerminationCondition

from .scenarios import ScenarioSet


@dataclass(frozen=True)
class BatteryConfig:
    capacity_kwh: float = 2000.0
    soc_min: float = 0.20
    soc_max: float = 0.90
    soc_target: float = 0.40
    charge_max_kw: float = 800.0
    discharge_max_kw: float = 1000.0
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    degradation_yuan_per_kwh: float = 0.05


@dataclass(frozen=True)
class TariffConfig:
    contract_kw: float = 400.0
    regular_basic_rate_yuan_per_kw_month: float = 223.60


@dataclass(frozen=True)
class SolverConfig:
    name: str = "appsi_highs"
    time_limit_seconds: float = 60.0
    mip_gap: float = 1e-6
    threads: int = 1
    random_seed: int = 42


@dataclass(frozen=True)
class RobustResult:
    status: str
    p: float | None
    objective_yuan: float | None
    scenario_costs_yuan: tuple[float, ...]
    oracle_costs_yuan: tuple[float, ...]
    scenario_regrets: tuple[float, ...]
    charge_kw: tuple[tuple[float, ...], ...]
    discharge_kw: tuple[tuple[float, ...], ...]
    grid_kw: tuple[tuple[float, ...], ...]
    curtail_kw: tuple[tuple[float, ...], ...]
    soc: tuple[tuple[float, ...], ...]
    first_stage_charge_kw: tuple[float, ...]
    first_stage_discharge_kw: tuple[float, ...]
    cost_offset_yuan: float
    solve_seconds: float
    termination: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validate_configs(battery: BatteryConfig, tariff: TariffConfig, initial_soc: float) -> None:
    if battery.capacity_kwh <= 0 or battery.charge_max_kw < 0 or battery.discharge_max_kw < 0:
        raise ValueError("battery capacity and power limits must be valid")
    if not 0 < battery.eta_charge <= 1 or not 0 < battery.eta_discharge <= 1:
        raise ValueError("battery efficiencies must be in (0, 1]")
    if not 0 <= battery.soc_min <= initial_soc <= battery.soc_max <= 1:
        raise ValueError("initial SOC is outside battery bounds")
    if not battery.soc_min <= battery.soc_target <= battery.soc_max:
        raise ValueError("terminal SOC target is outside battery bounds")
    if tariff.contract_kw <= 0 or tariff.regular_basic_rate_yuan_per_kw_month < 0:
        raise ValueError("tariff parameters must be non-negative")


def excess_charge(peak_kw: float, tariff: TariffConfig) -> float:
    excess = max(0.0, peak_kw - tariff.contract_kw)
    first = min(excess, 0.1 * tariff.contract_kw)
    return 2.0 * tariff.regular_basic_rate_yuan_per_kw_month * first + 3.0 * tariff.regular_basic_rate_yuan_per_kw_month * (excess - first)


def _build_model(
    scenarios: ScenarioSet,
    prices: np.ndarray,
    *,
    initial_soc: float,
    existing_month_peak_kw: float,
    battery: BatteryConfig,
    tariff: TariffConfig,
    timestep_hours: float,
    lock_steps: int,
    oracle_costs: np.ndarray | None,
    p_limit: float | None,
    minimize_p: bool,
    cost_offset_yuan: float,
) -> pyo.ConcreteModel:
    s_count, horizon = scenarios.load_kw.shape
    model = pyo.ConcreteModel("p_robust_dispatch")
    model.S = pyo.RangeSet(0, s_count - 1)
    model.T = pyo.RangeSet(0, horizon - 1)
    model.TSOC = pyo.RangeSet(0, horizon)

    model.charge = pyo.Var(model.S, model.T, bounds=(0, battery.charge_max_kw))
    model.discharge = pyo.Var(model.S, model.T, bounds=(0, battery.discharge_max_kw))
    model.grid = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.curtail = pyo.Var(model.S, model.T, domain=pyo.NonNegativeReals)
    model.soc = pyo.Var(model.S, model.TSOC, bounds=(battery.soc_min, battery.soc_max))
    model.mode = pyo.Var(model.S, model.T, domain=pyo.Binary)
    model.month_peak = pyo.Var(model.S, bounds=(max(0.0, existing_month_peak_kw), None))
    model.excess_first = pyo.Var(model.S, bounds=(0, 0.1 * tariff.contract_kw))
    model.excess_second = pyo.Var(model.S, domain=pyo.NonNegativeReals)

    for s in model.S:
        model.soc[s, 0].fix(initial_soc)
        model.add_component(
            f"terminal_soc_{s}",
            pyo.Constraint(expr=model.soc[s, horizon] >= battery.soc_target),
        )
        model.add_component(
            f"excess_balance_{s}",
            pyo.Constraint(
                expr=model.excess_first[s] + model.excess_second[s]
                >= model.month_peak[s] - tariff.contract_kw
            ),
        )
        for t in model.T:
            model.add_component(
                f"balance_{s}_{t}",
                pyo.Constraint(
                    expr=model.grid[s, t]
                    + model.discharge[s, t]
                    + float(scenarios.pv_kw[s, t])
                    - model.curtail[s, t]
                    == float(scenarios.load_kw[s, t]) + model.charge[s, t]
                ),
            )
            model.add_component(
                f"curtail_limit_{s}_{t}",
                pyo.Constraint(expr=model.curtail[s, t] <= float(scenarios.pv_kw[s, t])),
            )
            model.add_component(
                f"charge_mode_{s}_{t}",
                pyo.Constraint(expr=model.charge[s, t] <= battery.charge_max_kw * model.mode[s, t]),
            )
            model.add_component(
                f"discharge_mode_{s}_{t}",
                pyo.Constraint(expr=model.discharge[s, t] <= battery.discharge_max_kw * (1 - model.mode[s, t])),
            )
            model.add_component(
                f"discharge_residual_load_{s}_{t}",
                pyo.Constraint(
                    expr=model.discharge[s, t]
                    <= max(0.0, float(scenarios.load_kw[s, t]) - float(scenarios.pv_kw[s, t]))
                ),
            )
            model.add_component(
                f"soc_balance_{s}_{t}",
                pyo.Constraint(
                    expr=model.soc[s, t + 1]
                    == model.soc[s, t]
                    + battery.eta_charge * model.charge[s, t] * timestep_hours / battery.capacity_kwh
                    - model.discharge[s, t] * timestep_hours / (battery.eta_discharge * battery.capacity_kwh)
                ),
            )
            model.add_component(
                f"month_peak_{s}_{t}",
                pyo.Constraint(expr=model.month_peak[s] >= model.grid[s, t]),
            )

    for s in range(1, s_count):
        for t in range(min(lock_steps, horizon)):
            model.add_component(
                f"nonant_charge_{s}_{t}",
                pyo.Constraint(expr=model.charge[s, t] == model.charge[0, t]),
            )
            model.add_component(
                f"nonant_discharge_{s}_{t}",
                pyo.Constraint(expr=model.discharge[s, t] == model.discharge[0, t]),
            )
            model.add_component(
                f"nonant_mode_{s}_{t}",
                pyo.Constraint(expr=model.mode[s, t] == model.mode[0, t]),
            )

    residual_floor = scenarios.metadata.get("residual_load_floor_kw")
    if isinstance(residual_floor, list) and len(residual_floor) == horizon:
        for t in range(min(lock_steps, horizon)):
            model.add_component(
                f"locked_discharge_safety_{t}",
                pyo.Constraint(expr=model.discharge[0, t] <= max(0.0, float(residual_floor[t]))),
            )

    previous_excess_charge = excess_charge(existing_month_peak_kw, tariff)
    model.scenario_cost = pyo.Expression(
        model.S,
        rule=lambda m, s: cost_offset_yuan
        + sum(
            m.grid[s, t] * float(prices[t]) * timestep_hours
            + battery.degradation_yuan_per_kwh
            * (m.charge[s, t] + m.discharge[s, t])
            * timestep_hours
            for t in m.T
        )
        + 2.0 * tariff.regular_basic_rate_yuan_per_kw_month * m.excess_first[s]
        + 3.0 * tariff.regular_basic_rate_yuan_per_kw_month * m.excess_second[s]
        - previous_excess_charge,
    )
    expected_cost = sum(float(scenarios.probabilities[s]) * model.scenario_cost[s] for s in model.S)

    if oracle_costs is not None:
        if len(oracle_costs) != s_count or np.any(oracle_costs <= 1e-8):
            raise ValueError("oracle costs must be positive and match the scenario count")
        if minimize_p:
            model.rho = pyo.Var(domain=pyo.NonNegativeReals)
            model.regret_limit = pyo.Constraint(
                model.S,
                rule=lambda m, s: m.scenario_cost[s] <= (1.0 + m.rho) * float(oracle_costs[s]),
            )
            model.objective = pyo.Objective(expr=model.rho, sense=pyo.minimize)
        else:
            if p_limit is None or p_limit < 0:
                raise ValueError("p_limit must be non-negative")
            model.regret_limit = pyo.Constraint(
                model.S,
                rule=lambda m, s: m.scenario_cost[s] <= (1.0 + p_limit) * float(oracle_costs[s]),
            )
            model.objective = pyo.Objective(expr=expected_cost, sense=pyo.minimize)
    else:
        model.objective = pyo.Objective(expr=expected_cost, sense=pyo.minimize)

    model.expected_cost = pyo.Expression(expr=expected_cost)
    return model


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


def _is_feasible(result: object) -> bool:
    condition = result.solver.termination_condition
    return len(result.solution) > 0 and condition in {
        TerminationCondition.optimal,
        TerminationCondition.feasible,
        TerminationCondition.maxTimeLimit,
    }


def solve_oracles(
    scenarios: ScenarioSet,
    prices_yuan_per_kwh: Sequence[float],
    *,
    initial_soc: float = 0.50,
    existing_month_peak_kw: float = 0.0,
    battery: BatteryConfig = BatteryConfig(),
    tariff: TariffConfig = TariffConfig(),
    solver: SolverConfig = SolverConfig(),
    timestep_hours: float = 0.25,
    cost_offset_yuan: float = 0.0,
) -> np.ndarray:
    """Solve one perfect-information deterministic MILP per scenario."""
    _validate_configs(battery, tariff, initial_soc)
    prices = np.asarray(prices_yuan_per_kwh, dtype=float)
    if len(prices) != scenarios.horizon or np.any(prices < 0):
        raise ValueError("prices must be non-negative and match the scenario horizon")
    if cost_offset_yuan < 0:
        raise ValueError("cost_offset_yuan must be non-negative")

    costs = []
    oracle_solver = replace(solver, mip_gap=min(solver.mip_gap, 1e-6))
    for index in range(scenarios.count):
        single = ScenarioSet(
            timestamps=scenarios.timestamps,
            load_kw=scenarios.load_kw[index : index + 1],
            pv_kw=scenarios.pv_kw[index : index + 1],
            probabilities=np.array([1.0]),
            source_dates=(scenarios.source_dates[index],),
            metadata=scenarios.metadata,
        )
        model = _build_model(
            single,
            prices,
            initial_soc=initial_soc,
            existing_month_peak_kw=existing_month_peak_kw,
            battery=battery,
            tariff=tariff,
            timestep_hours=timestep_hours,
            lock_steps=0,
            oracle_costs=None,
            p_limit=None,
            minimize_p=False,
            cost_offset_yuan=cost_offset_yuan,
        )
        result, _ = _solve(model, oracle_solver)
        if not _is_feasible(result):
            raise RuntimeError(f"oracle scenario {index} failed: {result.solver.termination_condition}")
        costs.append(float(pyo.value(model.scenario_cost[0])))
    return np.asarray(costs)


def solve_p_robust(
    scenarios: ScenarioSet,
    prices_yuan_per_kwh: Sequence[float],
    oracle_costs_yuan: Sequence[float],
    *,
    p_limit: float | None,
    lock_steps: int = 4,
    initial_soc: float = 0.50,
    existing_month_peak_kw: float = 0.0,
    battery: BatteryConfig = BatteryConfig(),
    tariff: TariffConfig = TariffConfig(),
    solver: SolverConfig = SolverConfig(),
    timestep_hours: float = 0.25,
    cost_offset_yuan: float = 0.0,
) -> RobustResult:
    """Solve fixed-p P-robust dispatch, or minimize p when ``p_limit`` is None."""
    _validate_configs(battery, tariff, initial_soc)
    prices = np.asarray(prices_yuan_per_kwh, dtype=float)
    oracle_costs = np.asarray(oracle_costs_yuan, dtype=float)
    if len(prices) != scenarios.horizon or np.any(prices < 0):
        raise ValueError("prices must be non-negative and match the scenario horizon")
    if not 0 <= lock_steps <= scenarios.horizon:
        raise ValueError("lock_steps must be within the scenario horizon")
    if cost_offset_yuan < 0:
        raise ValueError("cost_offset_yuan must be non-negative")

    minimize_p = p_limit is None
    model = _build_model(
        scenarios,
        prices,
        initial_soc=initial_soc,
        existing_month_peak_kw=existing_month_peak_kw,
        battery=battery,
        tariff=tariff,
        timestep_hours=timestep_hours,
        lock_steps=lock_steps,
        oracle_costs=oracle_costs,
        p_limit=p_limit,
        minimize_p=minimize_p,
        cost_offset_yuan=cost_offset_yuan,
    )
    solve_config = replace(solver, mip_gap=min(solver.mip_gap, 1e-6)) if minimize_p else solver
    result, seconds = _solve(model, solve_config)
    if not _is_feasible(result):
        return RobustResult(
            status="infeasible",
            p=p_limit,
            objective_yuan=None,
            scenario_costs_yuan=(),
            oracle_costs_yuan=tuple(float(x) for x in oracle_costs),
            scenario_regrets=(),
            charge_kw=(),
            discharge_kw=(),
            grid_kw=(),
            curtail_kw=(),
            soc=(),
            first_stage_charge_kw=(),
            first_stage_discharge_kw=(),
            cost_offset_yuan=cost_offset_yuan,
            solve_seconds=seconds,
            termination=str(result.solver.termination_condition),
        )

    solved_p = float(pyo.value(model.rho)) if minimize_p else float(p_limit)
    if minimize_p:
        model.objective.deactivate()
        model.rho_cap = pyo.Constraint(expr=model.rho <= solved_p + 1e-7)
        model.expected_objective = pyo.Objective(expr=model.expected_cost, sense=pyo.minimize)
        tie_result, tie_seconds = _solve(model, solve_config)
        seconds += tie_seconds
        if _is_feasible(tie_result):
            result = tie_result

    scenario_costs = tuple(float(pyo.value(model.scenario_cost[s])) for s in model.S)
    regrets = tuple(cost / float(oracle_costs[s]) - 1.0 for s, cost in enumerate(scenario_costs))
    charge = tuple(tuple(float(pyo.value(model.charge[s, t])) for t in model.T) for s in model.S)
    discharge = tuple(tuple(float(pyo.value(model.discharge[s, t])) for t in model.T) for s in model.S)
    grid = tuple(tuple(float(pyo.value(model.grid[s, t])) for t in model.T) for s in model.S)
    curtail = tuple(tuple(float(pyo.value(model.curtail[s, t])) for t in model.T) for s in model.S)
    soc = tuple(tuple(float(pyo.value(model.soc[s, t])) for t in model.TSOC) for s in model.S)

    return RobustResult(
        status="optimal" if result.solver.termination_condition == TerminationCondition.optimal else "feasible",
        p=solved_p,
        objective_yuan=float(pyo.value(model.expected_cost)),
        scenario_costs_yuan=scenario_costs,
        oracle_costs_yuan=tuple(float(x) for x in oracle_costs),
        scenario_regrets=regrets,
        charge_kw=charge,
        discharge_kw=discharge,
        grid_kw=grid,
        curtail_kw=curtail,
        soc=soc,
        first_stage_charge_kw=charge[0][:lock_steps],
        first_stage_discharge_kw=discharge[0][:lock_steps],
        cost_offset_yuan=cost_offset_yuan,
        solve_seconds=seconds,
        termination=str(result.solver.termination_condition),
    )
