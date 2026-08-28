from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from data_loader import DEFAULT_ENGINE_ROOT, SCENARIO_RUNS_DIR


@dataclass(frozen=True)
class ScenarioParams:
    year: int = 2018
    months: tuple[int, ...] = (7,)
    days: int | None = 2
    fast: bool = True
    q_kwh: float | None = 2000.0
    contract_kw: float | None = 400.0
    lambda_excess: float | None = 300.0
    w_soc: float | None = 1500.0
    lambda_store: float | None = 0.0
    diag_days: int = 1


@dataclass(frozen=True)
class ScenarioResult:
    run_id: str
    output_dir: Path
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    meta_path: Path


def make_run_id(params: ScenarioParams) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    digest = hashlib.sha1(json.dumps(asdict(params), sort_keys=True).encode("utf-8")).hexdigest()[:8]
    return f"{stamp}_{digest}"


def build_command(
    params: ScenarioParams,
    *,
    engine_root: str | Path = DEFAULT_ENGINE_ROOT,
    output_dir: str | Path,
    python_executable: str | None = None,
) -> list[str]:
    root = Path(engine_root).expanduser()
    cmd = [
        python_executable or default_python_executable(),
        str(root / "ems_run.py"),
        "--year",
        str(params.year),
        "--months",
        *[str(m) for m in params.months],
        "--out",
        str(Path(output_dir)),
        "--diag-days",
        str(params.diag_days),
    ]
    if params.fast:
        cmd.append("--fast")
    if params.days is not None:
        cmd.extend(["--days", str(params.days)])
    _append_float(cmd, "--Q", params.q_kwh)
    _append_float(cmd, "--contract-kw", params.contract_kw)
    _append_float(cmd, "--lambda-excess", params.lambda_excess)
    _append_float(cmd, "--w-soc", params.w_soc)
    _append_float(cmd, "--lambda-store", params.lambda_store)
    return cmd


def default_python_executable() -> str:
    return "python3"


def run_scenario(
    params: ScenarioParams,
    *,
    engine_root: str | Path = DEFAULT_ENGINE_ROOT,
    scenario_root: str | Path = SCENARIO_RUNS_DIR,
    python_executable: str | None = None,
    timeout_seconds: int | None = None,
) -> ScenarioResult:
    root = Path(engine_root).expanduser()
    scenario_root = Path(scenario_root).expanduser()
    run_id = make_run_id(params)
    output_dir = scenario_root / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    cmd = build_command(
        params,
        engine_root=root,
        output_dir=output_dir,
        python_executable=python_executable,
    )
    cache_dir = output_dir / ".cache"
    (cache_dir / "matplotlib").mkdir(parents=True, exist_ok=True)
    (cache_dir / "xdg").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", str(cache_dir / "matplotlib"))
    env.setdefault("XDG_CACHE_HOME", str(cache_dir / "xdg"))
    if python_executable is None and sys.executable:
        python_bin = str(Path(sys.executable).parent)
        env["PATH"] = python_bin + os.pathsep + env.get("PATH", "")
    started = time.time()
    completed = subprocess.run(
        cmd,
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = time.time() - started
    result = ScenarioResult(
        run_id=run_id,
        output_dir=output_dir,
        command=cmd,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=elapsed,
        meta_path=output_dir / "run_meta.json",
    )
    _write_meta(result, params)
    return result


def _append_float(cmd: list[str], flag: str, value: float | None) -> None:
    if value is not None:
        cmd.extend([flag, f"{float(value):g}"])


def _write_meta(result: ScenarioResult, params: ScenarioParams) -> None:
    meta: dict[str, Any] = {
        "run_id": result.run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": "success" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "elapsed_seconds": result.elapsed_seconds,
        "command": result.command,
        "params": asdict(params),
        "python": sys.version,
    }
    result.meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
