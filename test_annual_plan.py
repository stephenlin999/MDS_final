from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from robust_ems.annual_plan import (
    AnnualPlanConfig,
    Contracts,
    _dispatch,
    _scenario_paths,
)
from robust_ems.model import BatteryConfig, SolverConfig


ROOT = Path(__file__).resolve().parent


class AnnualScenarioTests(unittest.TestCase):
    def test_short_scenario_set_is_normalized_and_covers_actual_net_load(self) -> None:
        days = 365
        slots = np.arange(96)
        load = np.stack([120 + 20 * np.sin(2 * np.pi * slots / 96) + day % 7 for day in range(days)])
        daylight = np.maximum(0, np.sin(np.pi * (slots - 24) / 48))
        pv = np.stack([80 * daylight * (0.8 + 0.2 * np.sin(day / 20)) for day in range(days)])
        dates = pd.date_range("2026-01-01", periods=7, freq="D")

        scenario_load, scenario_pv, probabilities, metadata = _scenario_paths(
            load,
            pv,
            dates,
            AnnualPlanConfig(draws=30, scenarios=5, days=7),
        )

        self.assertEqual(scenario_load.shape, (5, 7, 96))
        self.assertEqual(scenario_pv.shape, (5, 7, 96))
        self.assertAlmostEqual(float(probabilities.sum()), 1.0)
        self.assertTrue(metadata["coverage_passed"])

    def test_daily_dispatch_locks_first_hour_across_scenarios(self) -> None:
        timestamps = pd.date_range("2026-07-15", periods=8, freq="15min")
        load = np.asarray([[180.0] * 8, [260.0] * 8])
        pv = np.asarray([[20.0] * 8, [5.0] * 8])
        result = _dispatch(
            load,
            pv,
            np.asarray([0.5, 0.5]),
            timestamps,
            np.zeros((2, 4)),
            0.50,
            BatteryConfig(
                capacity_kwh=400,
                soc_min=0.10,
                soc_max=0.90,
                soc_target=0.50,
                charge_max_kw=200,
                discharge_max_kw=200,
                degradation_yuan_per_kwh=1.0,
            ),
            Contracts(),
            AnnualPlanConfig(lock_steps=4),
            SolverConfig(time_limit_seconds=20, mip_gap=1e-6, threads=1),
        )

        self.assertNotEqual(result["status"], "infeasible")
        np.testing.assert_allclose(result["charge"][0, :4], result["charge"][1, :4], atol=1e-6)
        np.testing.assert_allclose(result["discharge"][0, :4], result["discharge"][1, :4], atol=1e-6)


class PresentationContractTests(unittest.TestCase):
    def test_formal_presentation_contract_is_complete(self) -> None:
        path = ROOT / "model_results" / "robust" / "annual_planning" / "presentation.json"
        payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["meta"]["status"], "valid")
        self.assertEqual(len(payload["monthlyComparison"]), 12)
        self.assertEqual(len(payload["strategyComparison"]), 4)
        for month in range(1, 13):
            days = payload["dailyDispatch"][str(month)]
            self.assertEqual(len(days), 3)
            self.assertTrue(all(len(day["rows"]) == 96 for day in days))
        for key in (
            "exPostRegretP50",
            "exPostRegretP90",
            "exPostRegretP95",
            "exPostRegretCoverage",
            "exPostRegretPassed",
        ):
            self.assertIn(key, payload["scenarioCoverage"])


if __name__ == "__main__":
    unittest.main()
