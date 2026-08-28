from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from robust_ems import BatteryConfig, ScenarioSet, SolverConfig, TariffConfig, build_joint_scenarios
from robust_ems.model import excess_charge, solve_oracles, solve_p_robust


class ScenarioTests(unittest.TestCase):
    def test_joint_scenarios_never_use_future_days(self) -> None:
        rows = []
        for day in pd.date_range("2026-01-01", "2026-01-20", freq="D"):
            future = day >= pd.Timestamp("2026-01-15")
            for timestamp in pd.date_range(day, periods=96, freq="15min"):
                hour = timestamp.hour + timestamp.minute / 60
                pv = max(0.0, 80.0 * np.sin(np.pi * (hour - 6) / 12))
                rows.append(
                    {
                        "as_of": timestamp,
                        "P_load_fcst": 100.0,
                        "P_pv_fcst": pv,
                        "P_load_actual": 10_000.0 if future else 100.0 + day.day,
                        "P_pv_actual": pv,
                    }
                )
        history = pd.DataFrame(rows)
        target = pd.date_range("2026-01-15", periods=96, freq="15min")
        scenarios = build_joint_scenarios(
            history,
            target,
            np.full(96, 100.0),
            np.maximum(0.0, 80.0 * np.sin(np.pi * ((target.hour + target.minute / 60) - 6) / 12)),
            as_of=target[0],
            n_scenarios=5,
        )

        self.assertTrue(all(date < "2026-01-15" for date in scenarios.source_dates))
        self.assertLess(float(scenarios.load_kw.max()), 200.0)
        self.assertAlmostEqual(float(scenarios.probabilities.sum()), 1.0)


class RobustModelTests(unittest.TestCase):
    solver = SolverConfig(time_limit_seconds=20, mip_gap=1e-8, threads=1)
    battery = BatteryConfig(
        capacity_kwh=100.0,
        soc_min=0.20,
        soc_max=0.90,
        soc_target=0.50,
        charge_max_kw=50.0,
        discharge_max_kw=50.0,
        degradation_yuan_per_kwh=0.0,
    )
    tariff = TariffConfig(contract_kw=1_000.0, regular_basic_rate_yuan_per_kw_month=100.0)

    def test_conflicting_first_stage_has_positive_minimum_p(self) -> None:
        scenarios = ScenarioSet(
            timestamps=pd.date_range("2026-07-01", periods=2, freq="15min"),
            load_kw=np.array([[100.0, 0.0], [0.0, 100.0]]),
            pv_kw=np.zeros((2, 2)),
            probabilities=np.array([0.5, 0.5]),
            source_dates=("a", "b"),
            metadata={},
        )
        prices = np.array([10.0, 1.0])
        oracles = solve_oracles(
            scenarios,
            prices,
            battery=self.battery,
            tariff=self.tariff,
            solver=self.solver,
        )
        minimum = solve_p_robust(
            scenarios,
            prices,
            oracles,
            p_limit=None,
            lock_steps=1,
            battery=self.battery,
            tariff=self.tariff,
            solver=self.solver,
        )

        self.assertEqual(minimum.status, "optimal")
        self.assertIsNotNone(minimum.p)
        self.assertGreater(minimum.p or 0.0, 0.01)
        self.assertLessEqual(max(minimum.scenario_regrets), (minimum.p or 0.0) + 1e-5)
        self.assertGreaterEqual(min(minimum.scenario_regrets), -1e-6)
        self.assertAlmostEqual(minimum.charge_kw[0][0], minimum.charge_kw[1][0], places=5)
        self.assertAlmostEqual(minimum.discharge_kw[0][0], minimum.discharge_kw[1][0], places=5)

        infeasible = solve_p_robust(
            scenarios,
            prices,
            oracles,
            p_limit=0.0,
            lock_steps=1,
            battery=self.battery,
            tariff=self.tariff,
            solver=self.solver,
        )
        self.assertEqual(infeasible.status, "infeasible")

    def test_identical_scenarios_have_zero_minimum_p(self) -> None:
        load = np.array([[80.0, 60.0], [80.0, 60.0]])
        scenarios = ScenarioSet(
            timestamps=pd.date_range("2026-07-01", periods=2, freq="15min"),
            load_kw=load,
            pv_kw=np.zeros_like(load),
            probabilities=np.array([0.4, 0.6]),
            source_dates=("a", "b"),
            metadata={},
        )
        prices = np.array([5.0, 2.0])
        oracles = solve_oracles(
            scenarios,
            prices,
            battery=self.battery,
            tariff=self.tariff,
            solver=self.solver,
        )
        minimum = solve_p_robust(
            scenarios,
            prices,
            oracles,
            p_limit=None,
            lock_steps=1,
            battery=self.battery,
            tariff=self.tariff,
            solver=self.solver,
        )
        self.assertAlmostEqual(minimum.p or 0.0, 0.0, places=6)

    def test_excess_charge_uses_two_bands(self) -> None:
        tariff = TariffConfig(contract_kw=400.0, regular_basic_rate_yuan_per_kw_month=100.0)
        self.assertEqual(excess_charge(400.0, tariff), 0.0)
        self.assertEqual(excess_charge(440.0, tariff), 8_000.0)
        self.assertEqual(excess_charge(460.0, tariff), 14_000.0)


if __name__ == "__main__":
    unittest.main()
