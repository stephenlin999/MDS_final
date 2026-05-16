"""
Phase 2 MILP: single-day battery dispatch using PuLP + CBC.

Unit convention (all time-based quantities use Δt = 1 h):
  Power   : Wh/h  — numerically equal to W for a 1-hour step
  Energy  : Wh    — stored in SOC, transferred per interval
  The hourly solar CSV is a sum of 4 × 15-min Wh values, so it is already
  in Wh-per-hour units and requires no further scaling.

Mathematical model
------------------
Variables (per hour t = 0..23):
  P_c[t]       >= 0               charge power    [Wh/h]
  P_d[t]       >= 0               discharge power [Wh/h]
  b[t]         in {0,1}           1 = charging mode (Big-M mutex)
  SOC[t]       in [SOC_MIN, SOC_MAX]  state-of-charge at END of hour t [Wh]
  dp_normal[t] in [0, P_CONTRACT]  grid draw within contract  [Wh/h]
  dp_excess[t] >= 0               grid draw above contract   [Wh/h]

Derived (not a PuLP variable — used inline):
  P_grid[t] = P_load[t] + P_c[t] - P_d[t] - P_solar[t]   (may be < 0 = export)

Constraints
-----------
Big-M charge/discharge mutual exclusion:
  P_c[t] <= P_MAX * b[t]
  P_d[t] <= P_MAX * (1 - b[t])

SOC dynamics (Δt = 1 h, so power [Wh/h] × 1 h = energy [Wh]):
  SOC[t] = SOC[t-1] + eta_c * P_c[t] - P_d[t] / eta_d

Over-contract piecewise split (buying only; export → aux vars stay at 0):
  dp_normal[t] + dp_excess[t] >= P_grid[t]
  dp_normal[t] <= P_CONTRACT
  Minimisation drives dp_normal + dp_excess = max(P_grid[t], 0)

Terminal SOC hard constraint (combines end-of-day continuity + UPS reserve):
  SOC[23] >= SOC_TERMINAL   where SOC_TERMINAL = max(SOC_INIT, UPS_RESERVE_WH)
  Using >= (not ==) so the model can end higher on a surplus day without
  being forced to buy expensive grid power just to hit an exact target.

Objective:
  minimize  C_E  * sum_t(dp_normal[t] + dp_excess[t])   <- grid energy cost
          + C_OC * sum_t(dp_excess[t])                   <- over-contract penalty
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOCAL_PACKAGE_DIR = PROJECT_DIR / ".python_packages"
sys.path.insert(0, str(LOCAL_PACKAGE_DIR))

import numpy as np
import pandas as pd
import pulp

RESULTS_DIR = PROJECT_DIR / "model_results"
MILP_HOURLY_PATH = RESULTS_DIR / "milp_solar_forecast_hourly.csv"

# ── Battery parameters ───────────────────────────────────────────────────────
E_CAP_WH        = 30_000.0   # total capacity [Wh]
SOC_MIN_FRAC    = 0.10        # hard lower bound fraction
SOC_MAX_FRAC    = 0.90        # hard upper bound fraction
SOC_INIT_FRAC   = 0.50        # initial SOC fraction (= start of each day)
UPS_RESERVE_FRAC = 0.20       # minimum UPS buffer required by end of day
P_MAX_WH        = 8_000.0    # max charge OR discharge power [Wh/h]
ETA_C           = 0.95        # charge one-way efficiency
ETA_D           = 0.95        # discharge one-way efficiency

SOC_MIN      = E_CAP_WH * SOC_MIN_FRAC
SOC_MAX      = E_CAP_WH * SOC_MAX_FRAC
SOC_INIT     = E_CAP_WH * SOC_INIT_FRAC
UPS_RESERVE  = E_CAP_WH * UPS_RESERVE_FRAC
# Hard terminal lower bound: battery must not end the day below where it started,
# and also must hold the UPS reserve. >= (not ==) keeps flexibility on surplus days.
SOC_TERMINAL = max(SOC_INIT, UPS_RESERVE)

# ── Tariff / penalty parameters ──────────────────────────────────────────────
P_CONTRACT_WH = 8_000.0     # contracted demand level [Wh/h]
C_E           = 1.0          # energy price per Wh
C_OC          = 3.0          # additional penalty per Wh above contract (total = 4× C_E)

# ── Synthetic 24-hour load profile [Wh/h] ────────────────────────────────────
LOAD_PROFILE_WH: list[float] = [
    3_000, 2_500, 2_500, 2_800,     # 00-03
    3_500, 5_000, 7_000, 9_000,     # 04-07
   10_000,11_000,12_000,12_000,     # 08-11
   11_000,10_000, 9_000, 8_000,     # 12-15
    9_000,11_000,12_000,11_000,     # 16-19
    9_000, 7_000, 5_000, 4_000,     # 20-23
]


def load_solar_day(target_date: str) -> np.ndarray:
    """Return 24-element array of hourly solar point forecast [Wh] for target_date."""
    df = pd.read_csv(MILP_HOURLY_PATH, parse_dates=["timestamp"])
    day = df[df["timestamp"].dt.date.astype(str) == target_date].copy()
    if len(day) != 24:
        raise ValueError(
            f"Expected 24 hours for {target_date}, got {len(day)}."
        )
    return day["solar_point_wh"].to_numpy(dtype=float)


def build_and_solve(solar_wh: np.ndarray, load_wh: np.ndarray) -> dict:
    T = 24
    prob = pulp.LpProblem("battery_dispatch", pulp.LpMinimize)

    # ── Decision variables ────────────────────────────────────────────────────
    P_c = [pulp.LpVariable(f"P_c_{t}", lowBound=0, upBound=P_MAX_WH) for t in range(T)]
    P_d = [pulp.LpVariable(f"P_d_{t}", lowBound=0, upBound=P_MAX_WH) for t in range(T)]
    b   = [pulp.LpVariable(f"b_{t}",   cat="Binary")                   for t in range(T)]
    SOC = [pulp.LpVariable(f"SOC_{t}", lowBound=SOC_MIN, upBound=SOC_MAX) for t in range(T)]

    dp_normal = [
        pulp.LpVariable(f"dpN_{t}", lowBound=0, upBound=P_CONTRACT_WH)
        for t in range(T)
    ]
    dp_excess = [pulp.LpVariable(f"dpX_{t}", lowBound=0) for t in range(T)]

    # ── Objective (no soft SOC term — terminal SOC is a hard constraint) ──────
    prob += (
        C_E  * pulp.lpSum(dp_normal[t] + dp_excess[t] for t in range(T))
      + C_OC * pulp.lpSum(dp_excess[t]                for t in range(T))
    )

    # ── Per-hour constraints ──────────────────────────────────────────────────
    for t in range(T):
        # P_grid inline [Wh/h]: positive = buying, negative = exporting
        P_grid_t = load_wh[t] + P_c[t] - P_d[t] - solar_wh[t]

        # Big-M charge/discharge mutex (M = P_MAX_WH)
        prob += P_c[t] <= P_MAX_WH * b[t],        f"mutex_c_{t}"
        prob += P_d[t] <= P_MAX_WH * (1 - b[t]),  f"mutex_d_{t}"

        # SOC dynamics (Δt = 1 h → power [Wh/h] × 1 h = energy [Wh])
        soc_prev = SOC_INIT if t == 0 else SOC[t - 1]
        prob += SOC[t] == soc_prev + ETA_C * P_c[t] - P_d[t] / ETA_D, f"soc_dyn_{t}"

        # Over-contract piecewise split
        # Minimisation drives: dp_normal + dp_excess = max(P_grid[t], 0)
        # Export (P_grid < 0): constraint satisfied with both aux vars at 0
        prob += dp_normal[t] + dp_excess[t] >= P_grid_t, f"grid_cover_{t}"

    # ── Terminal SOC hard constraint ──────────────────────────────────────────
    # SOC[23] >= SOC_TERMINAL = max(SOC_INIT, UPS_RESERVE)
    # Inequality (not ==): on a surplus day the model can end above SOC_INIT
    # without being forced to dump energy. On a deficit day it must buy grid
    # power to refill — this is the correct cost to account for in scheduling.
    prob += SOC[T - 1] >= SOC_TERMINAL, "terminal_soc"

    # ── Solve ─────────────────────────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)

    return {
        "status":       pulp.LpStatus[prob.status],
        "objective":    pulp.value(prob.objective),
        "P_c_wh":       [pulp.value(P_c[t])              for t in range(T)],
        "P_d_wh":       [pulp.value(P_d[t])              for t in range(T)],
        "b":            [int(round(pulp.value(b[t])))     for t in range(T)],
        "SOC_wh":       [pulp.value(SOC[t])              for t in range(T)],
        "dp_normal_wh": [pulp.value(dp_normal[t])        for t in range(T)],
        "dp_excess_wh": [pulp.value(dp_excess[t])        for t in range(T)],
    }


def validate(result: dict, solar_wh: np.ndarray, load_wh: np.ndarray) -> dict:
    T = 24
    checks: dict = {}

    checks["solver_optimal"] = result["status"] == "Optimal"

    # No simultaneous charge+discharge (tolerance 1 Wh)
    simultaneous = [
        t for t in range(T)
        if (result["P_c_wh"][t] or 0) > 1.0 and (result["P_d_wh"][t] or 0) > 1.0
    ]
    checks["no_simultaneous_cd"] = len(simultaneous) == 0
    if simultaneous:
        checks["simultaneous_cd_hours"] = str(simultaneous)

    # SOC within hard bounds at every hour
    soc = [v or 0.0 for v in result["SOC_wh"]]
    checks["soc_within_bounds"] = all(SOC_MIN - 1 <= s <= SOC_MAX + 1 for s in soc)

    # SOC dynamics internally consistent (tolerance 10 Wh)
    soc_prev = SOC_INIT
    soc_ok = True
    for t in range(T):
        expected = (soc_prev
                    + ETA_C * (result["P_c_wh"][t] or 0)
                    - (result["P_d_wh"][t] or 0) / ETA_D)
        if abs(expected - soc[t]) > 10:
            soc_ok = False
        soc_prev = soc[t]
    checks["soc_dynamics_consistent"] = soc_ok

    # Terminal SOC hard constraint satisfied
    checks["terminal_soc_satisfied"] = soc[T - 1] >= SOC_TERMINAL - 1
    checks["end_soc_wh"]      = round(soc[T - 1], 1)
    checks["soc_terminal_wh"] = SOC_TERMINAL

    # Surplus-handling: any export hours?
    p_grid = [
        load_wh[t] + (result["P_c_wh"][t] or 0) - (result["P_d_wh"][t] or 0) - solar_wh[t]
        for t in range(T)
    ]
    export_hours = [t for t in range(T) if p_grid[t] < -1]
    checks["export_hours"] = export_hours   # informational

    return checks


def save_schedule(
    result: dict,
    solar_wh: np.ndarray,
    load_wh: np.ndarray,
    target_date: str,
) -> Path:
    T = 24
    hours = pd.date_range(target_date, periods=T, freq="1h")
    p_grid = [
        load_wh[t] + (result["P_c_wh"][t] or 0) - (result["P_d_wh"][t] or 0) - solar_wh[t]
        for t in range(T)
    ]
    schedule = pd.DataFrame(
        {
            "timestamp":    hours,
            "solar_wh":     np.round(solar_wh, 1),
            "load_wh":      np.round(load_wh, 1),
            "P_c_wh":       np.round(result["P_c_wh"], 1),
            "P_d_wh":       np.round(result["P_d_wh"], 1),
            "charging":     result["b"],
            "SOC_wh":       np.round(result["SOC_wh"], 1),
            "P_grid_wh":    np.round(p_grid, 1),
            "dp_normal_wh": np.round(result["dp_normal_wh"], 1),
            "dp_excess_wh": np.round(result["dp_excess_wh"], 1),
        }
    )
    out_path = RESULTS_DIR / f"milp_schedule_{target_date}.csv"
    schedule.to_csv(out_path, index=False)
    return out_path


def run_day(target_date: str) -> tuple[dict, dict]:
    """Solve and validate one day. Returns (summary, raw_result)."""
    solar_wh = load_solar_day(target_date)
    load_wh  = np.array(LOAD_PROFILE_WH, dtype=float)

    result = build_and_solve(solar_wh, load_wh)
    checks = validate(result, solar_wh, load_wh)
    out_path = save_schedule(result, solar_wh, load_wh, target_date)

    all_pass = all(
        v is True for k, v in checks.items()
        if isinstance(v, bool)
    )

    p_grid = [
        load_wh[t] + (result["P_c_wh"][t] or 0) - (result["P_d_wh"][t] or 0) - solar_wh[t]
        for t in range(24)
    ]

    summary = {
        "target_date":            target_date,
        "solver_status":          result["status"],
        "objective":              round(result["objective"] or 0, 2),
        "solar_total_wh":         round(float(solar_wh.sum()), 1),
        "load_total_wh":          round(float(load_wh.sum()), 1),
        "grid_bought_total_wh":   round(sum(max(v, 0) for v in p_grid), 1),
        "grid_export_total_wh":   round(sum(abs(min(v, 0)) for v in p_grid), 1),
        "over_contract_total_wh": round(sum(result["dp_excess_wh"] or [0]), 1),
        "end_soc_wh":             checks["end_soc_wh"],
        "terminal_soc_wh":        checks["soc_terminal_wh"],
        "export_hours":           checks["export_hours"],
        "all_checks_pass":        all_pass,
        "validation":             {k: v for k, v in checks.items()},
        "battery_params": {
            "E_cap_wh":         E_CAP_WH,
            "P_max_wh":         P_MAX_WH,
            "eta_c":            ETA_C,
            "eta_d":            ETA_D,
            "SOC_min_wh":       SOC_MIN,
            "SOC_max_wh":       SOC_MAX,
            "SOC_init_wh":      SOC_INIT,
            "SOC_terminal_wh":  SOC_TERMINAL,
            "UPS_reserve_wh":   UPS_RESERVE,
            "P_contract_wh":    P_CONTRACT_WH,
        },
    }
    summary_path = RESULTS_DIR / f"milp_summary_{target_date}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary, result


def print_day_report(target_date: str, summary: dict, result: dict) -> None:
    solar_wh = load_solar_day(target_date)
    load_wh  = np.array(LOAD_PROFILE_WH, dtype=float)

    print(f"\n{'='*60}")
    print(f"  {target_date}  |  status: {summary['solver_status']}"
          f"  |  {'ALL OK' if summary['all_checks_pass'] else 'CHECKS FAILED'}")
    print(f"{'='*60}")
    print(f"  Solar total    : {summary['solar_total_wh']:>10,.0f} Wh")
    print(f"  Load total     : {summary['load_total_wh']:>10,.0f} Wh")
    print(f"  Grid bought    : {summary['grid_bought_total_wh']:>10,.0f} Wh")
    print(f"  Grid exported  : {summary['grid_export_total_wh']:>10,.0f} Wh")
    print(f"  Over-contract  : {summary['over_contract_total_wh']:>10,.0f} Wh")
    print(f"  End SOC        : {summary['end_soc_wh']:>10,.0f} Wh  "
          f"(terminal >= {summary['terminal_soc_wh']:,.0f})")
    print(f"  Export hours   : {summary['export_hours']}")

    checks = summary["validation"]
    for k, v in checks.items():
        if isinstance(v, bool):
            icon = "OK  " if v else "FAIL"
            print(f"  [{icon}] {k}")

    print()
    print("  h   SOC(Wh)  Pc(Wh)  Pd(Wh) mode  solar(Wh) load(Wh)  P_grid(Wh)  excess")
    p_grid_list = [
        load_wh[t] + (result["P_c_wh"][t] or 0) - (result["P_d_wh"][t] or 0) - solar_wh[t]
        for t in range(24)
    ]
    for t in range(24):
        soc   = result["SOC_wh"][t] or 0
        pc    = result["P_c_wh"][t] or 0
        pd_   = result["P_d_wh"][t] or 0
        mode  = "CHG" if result["b"][t] else "DCH"
        pg    = p_grid_list[t]
        exc   = result["dp_excess_wh"][t] or 0
        exc_s = f"  !OVER+{exc:,.0f}" if exc > 1 else ""
        exp_s = "  EXPORT" if pg < -1 else ""
        print(f"  {t:02d} {soc:8,.0f} {pc:7,.0f} {pd_:7,.0f} [{mode}]"
              f" {solar_wh[t]:9,.0f} {load_wh[t]:8,.0f} {pg:10,.0f}{exc_s}{exp_s}")


def main() -> None:
    import sys
    RESULTS_DIR.mkdir(exist_ok=True)

    test_days = [
        ("2022-06-03", "sunny — nominal case"),
        ("2021-12-04", "cloudy — 661 Wh solar, terminal SOC must be bought from grid"),
        ("2022-03-14", "surplus — peak solar 17,193 Wh/h > max load 12,000 Wh/h"),
    ]

    if len(sys.argv) > 1:
        test_days = [(sys.argv[1], "user-specified")]

    all_results = {}
    for target_date, label in test_days:
        print(f"\nSolving {target_date} ({label})...")
        summary, result = run_day(target_date)
        print_day_report(target_date, summary, result)
        all_results[target_date] = summary

    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for d, s in all_results.items():
        status = "PASS" if s["all_checks_pass"] else "FAIL"
        print(f"  {d}  [{status}]  obj={s['objective']:,.0f}"
              f"  end_SOC={s['end_soc_wh']:,.0f}Wh"
              f"  overcontract={s['over_contract_total_wh']:.0f}Wh"
              f"  export={s['grid_export_total_wh']:.0f}Wh")


if __name__ == "__main__":
    main()
