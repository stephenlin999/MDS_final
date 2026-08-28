"""Leakage-safe joint load/PV residual scenarios."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

from sklearn.cluster import KMeans


@dataclass(frozen=True)
class ScenarioSet:
    timestamps: pd.DatetimeIndex
    load_kw: np.ndarray
    pv_kw: np.ndarray
    probabilities: np.ndarray
    source_dates: tuple[str, ...]
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        load = np.asarray(self.load_kw, dtype=float)
        pv = np.asarray(self.pv_kw, dtype=float)
        probabilities = np.asarray(self.probabilities, dtype=float)
        if load.ndim != 2 or pv.shape != load.shape:
            raise ValueError("load_kw and pv_kw must have shape [scenario, time]")
        if load.shape[1] != len(self.timestamps):
            raise ValueError("scenario horizon does not match timestamps")
        if load.shape[0] != len(probabilities) or load.shape[0] != len(self.source_dates):
            raise ValueError("scenario metadata length mismatch")
        if load.shape[0] == 0 or np.any(load < 0) or np.any(pv < 0):
            raise ValueError("scenarios must be non-empty and non-negative")
        if np.any(probabilities <= 0) or not np.isclose(probabilities.sum(), 1.0):
            raise ValueError("scenario probabilities must be positive and sum to one")

    @property
    def count(self) -> int:
        return int(self.load_kw.shape[0])

    @property
    def horizon(self) -> int:
        return int(self.load_kw.shape[1])

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamps": [ts.isoformat() for ts in self.timestamps],
            "load_kw": np.asarray(self.load_kw).tolist(),
            "pv_kw": np.asarray(self.pv_kw).tolist(),
            "probabilities": np.asarray(self.probabilities).tolist(),
            "source_dates": list(self.source_dates),
            "metadata": self.metadata,
        }


def _day_kind(ts: pd.Timestamp) -> str:
    return "weekday" if ts.weekday() < 5 else "weekend"


def _circular_day_distance(a: int, b: int) -> int:
    distance = abs(a - b)
    return min(distance, 366 - distance)


def _standardized_features(load: np.ndarray, pv: np.ndarray) -> np.ndarray:
    net = load - pv
    combined = np.concatenate([load, pv, 2.0 * net], axis=1)
    scale = combined.std(axis=0)
    return (combined - combined.mean(axis=0)) / np.where(scale > 1e-8, scale, 1.0)


def _select_medoids(features: np.ndarray, load: np.ndarray, pv: np.ndarray, count: int, seed: int) -> list[int]:
    n = len(features)
    if n <= count:
        return list(range(n))

    selected: list[int] = []
    net = load - pv
    for index in (
        int(np.argmax(net.max(axis=1))),
        int(np.argmin(net.min(axis=1))),
        int(np.argmin(net[:, : min(4, net.shape[1])].mean(axis=1))),
        int(np.argmin(pv.sum(axis=1))),
    ):
        if index not in selected:
            selected.append(index)

    cluster_count = max(1, count - len(selected))
    centers = KMeans(n_clusters=cluster_count, random_state=seed, n_init=20).fit(features).cluster_centers_
    for center in centers:
        index = int(np.argmin(np.sum((features - center) ** 2, axis=1)))
        if index not in selected:
            selected.append(index)

    while len(selected) < count:
        distances = np.min(
            np.stack([np.sum((features - features[index]) ** 2, axis=1) for index in selected]),
            axis=0,
        )
        distances[selected] = -1.0
        selected.append(int(np.argmax(distances)))
    return selected[:count]


def build_joint_scenarios(
    history: pd.DataFrame,
    target_timestamps: Sequence[pd.Timestamp],
    load_forecast_kw: Sequence[float],
    pv_forecast_kw: Sequence[float],
    *,
    as_of: pd.Timestamp,
    n_scenarios: int = 10,
    seasonal_window_days: int = 45,
    random_state: int = 42,
) -> ScenarioSet:
    """Build paired residual-path scenarios using only complete days before ``as_of``."""
    if n_scenarios < 1:
        raise ValueError("n_scenarios must be positive")

    required = {"as_of", "P_load_fcst", "P_pv_fcst", "P_load_actual", "P_pv_actual"}
    missing = required.difference(history.columns)
    if missing:
        raise ValueError(f"history is missing columns: {sorted(missing)}")

    target_index = pd.DatetimeIndex(target_timestamps)
    if target_index.empty or not target_index.is_monotonic_increasing:
        raise ValueError("target_timestamps must be non-empty and sorted")
    load_point = np.asarray(load_forecast_kw, dtype=float)
    pv_point = np.asarray(pv_forecast_kw, dtype=float)
    if len(load_point) != len(target_index) or len(pv_point) != len(target_index):
        raise ValueError("forecast lengths must match target_timestamps")
    if np.any(load_point < 0) or np.any(pv_point < 0):
        raise ValueError("point forecasts must be non-negative")

    frame = history.loc[:, sorted(required)].copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"], errors="raise")
    cutoff = pd.Timestamp(as_of)
    frame = frame[frame["as_of"].dt.floor("D") < cutoff.floor("D")]
    frame["date"] = frame["as_of"].dt.floor("D")
    frame["slot"] = frame["as_of"].dt.hour * 4 + frame["as_of"].dt.minute // 15

    target_slots = (target_index.hour * 4 + target_index.minute // 15).to_numpy()
    target_kind = _day_kind(target_index[0])
    target_doy = int(target_index[0].dayofyear)
    candidates: list[tuple[pd.Timestamp, np.ndarray, np.ndarray]] = []

    for source_date, day in frame.groupby("date", sort=True):
        if _day_kind(source_date) != target_kind or day["slot"].duplicated().any():
            continue
        day = day.set_index("slot").reindex(target_slots)
        if day.isna().any().any():
            continue
        source_load_scale = max(float(day["P_load_fcst"].mean()), 1.0)
        target_load_scale = max(float(load_point.mean()), 1.0)
        source_pv_scale = max(float(day["P_pv_fcst"].max()), 1.0)
        target_pv_scale = max(float(pv_point.max()), 1.0)
        load_residual = (
            (day["P_load_actual"].to_numpy() - day["P_load_fcst"].to_numpy())
            * target_load_scale
            / source_load_scale
        )
        pv_residual = (
            (day["P_pv_actual"].to_numpy() - day["P_pv_fcst"].to_numpy())
            * target_pv_scale
            / source_pv_scale
        )
        candidates.append(
            (
                source_date,
                np.maximum(0.0, load_point + load_residual),
                np.maximum(0.0, pv_point + pv_residual),
            )
        )

    if not candidates:
        raise ValueError("no complete historical joint residual days exist before as_of")

    def eligible(window: int | None) -> list[int]:
        return [
            i
            for i, (date, _, _) in enumerate(candidates)
            if window is None or _circular_day_distance(int(date.dayofyear), target_doy) <= window
        ]

    minimum_pool = min(max(n_scenarios, 5), len(candidates))
    pool = eligible(seasonal_window_days)
    window_used: int | str = seasonal_window_days
    if len(pool) < minimum_pool:
        pool = eligible(90)
        window_used = 90
    if len(pool) < minimum_pool:
        pool = eligible(None)
        window_used = "all-past-same-day-kind"

    dates = [candidates[i][0] for i in pool]
    load = np.stack([candidates[i][1] for i in pool])
    pv = np.stack([candidates[i][2] for i in pool])
    features = _standardized_features(load, pv)
    medoids = _select_medoids(features, load, pv, min(n_scenarios, len(pool)), random_state)

    selected_features = features[medoids]
    assignments = np.argmin(
        np.sum((features[:, None, :] - selected_features[None, :, :]) ** 2, axis=2),
        axis=1,
    )
    counts = np.bincount(assignments, minlength=len(medoids)).astype(float)
    probabilities = counts / counts.sum()

    return ScenarioSet(
        timestamps=target_index,
        load_kw=load[medoids],
        pv_kw=pv[medoids],
        probabilities=probabilities,
        source_dates=tuple(dates[i].date().isoformat() for i in medoids),
        metadata={
            "as_of": cutoff.isoformat(),
            "candidate_days": len(pool),
            "seasonal_window_days": window_used,
            "method": "paired_residual_medoids",
            "random_state": random_state,
            "residual_load_floor_kw": np.maximum(0.0, (load - pv).min(axis=0)).tolist(),
        },
    )
