"""Semantic drift: the schema is unchanged but the meaning of the numbers moved.

Compares the current batch against a rolling baseline sample using three
independent signals so a single noisy statistic cannot trip the detector:
  * PSI over baseline quantile bins
  * two-sample Kolmogorov-Smirnov statistic
  * mean shift measured in baseline standard deviations
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from app.contracts.model import DriftPolicy

BASELINE_SAMPLE_SIZE = 2000
PSI_BINS = 10
_EPS = 1e-6


class ColumnBaseline(BaseModel):
    column: str
    count: int = 0
    sample: list[float] = Field(default_factory=list)

    @property
    def mean(self) -> float:
        return float(np.mean(self.sample)) if self.sample else 0.0

    @property
    def std(self) -> float:
        return float(np.std(self.sample)) if self.sample else 0.0

    def absorb(self, values: list[float], rng: random.Random) -> None:
        """Reservoir sampling keeps the baseline bounded and unbiased over many runs."""
        for v in values:
            self.count += 1
            if len(self.sample) < BASELINE_SAMPLE_SIZE:
                self.sample.append(v)
            else:
                j = rng.randrange(self.count)
                if j < BASELINE_SAMPLE_SIZE:
                    self.sample[j] = v


class DriftReport(BaseModel):
    column: str
    baseline_count: int
    current_count: int
    baseline_mean: float
    baseline_std: float
    current_mean: float
    current_std: float
    psi: float
    ks_statistic: float
    mean_shift_sigma: float
    signals: list[str]
    drifted: bool


def population_stability_index(baseline: np.ndarray, current: np.ndarray, bins: int = PSI_BINS) -> float:
    edges = np.unique(np.quantile(baseline, np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0 if np.allclose(current, baseline[0]) else float("inf")
    edges[0], edges[-1] = -np.inf, np.inf
    b = np.histogram(baseline, edges)[0] / len(baseline) + _EPS
    c = np.histogram(current, edges)[0] / len(current) + _EPS
    return float(np.sum((c - b) * np.log(c / b)))


def ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.sort(a), np.sort(b)
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / len(a)
    cdf_b = np.searchsorted(b, grid, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


def compare_to_baseline(baseline: ColumnBaseline, current: list[float], policy: DriftPolicy) -> DriftReport | None:
    if len(baseline.sample) < policy.min_baseline or len(current) < 10:
        return None
    base = np.asarray(baseline.sample, dtype=float)
    cur = np.asarray(current, dtype=float)
    psi = population_stability_index(base, cur)
    ks = ks_statistic(base, cur)
    std = float(base.std())
    shift = abs(float(cur.mean()) - float(base.mean())) / (std if std > _EPS else 1.0)

    signals = []
    if psi > policy.psi_threshold:
        signals.append(f"PSI {psi:.3f} > {policy.psi_threshold}")
    if ks > policy.ks_threshold:
        signals.append(f"KS {ks:.3f} > {policy.ks_threshold}")
    if shift > policy.mean_shift_sigma:
        signals.append(f"mean shift {shift:.1f} sd > {policy.mean_shift_sigma} sd")

    return DriftReport(
        column=baseline.column, baseline_count=len(base), current_count=len(cur),
        baseline_mean=float(base.mean()), baseline_std=std,
        current_mean=float(cur.mean()), current_std=float(cur.std()),
        psi=round(psi, 4), ks_statistic=round(ks, 4), mean_shift_sigma=round(shift, 2),
        signals=signals, drifted=len(signals) >= 2,
    )


def numeric_values(rows: list[dict[str, Any]], column: str) -> list[float]:
    out = []
    for r in rows:
        v = r.get(column)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


class BaselineStore:
    def __init__(self, root: Path, seed: int = 7) -> None:
        self._root = root
        self._rng = random.Random(seed)

    def _path(self, tenant_id: str, pipeline_id: str) -> Path:
        return self._root / tenant_id / f"{pipeline_id}.baseline.json"

    def load(self, tenant_id: str, pipeline_id: str) -> dict[str, ColumnBaseline]:
        path = self._path(tenant_id, pipeline_id)
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: ColumnBaseline.model_validate(v) for k, v in raw.items()}

    def update(self, tenant_id: str, pipeline_id: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
        baselines = self.load(tenant_id, pipeline_id)
        for col in columns:
            baselines.setdefault(col, ColumnBaseline(column=col)).absorb(numeric_values(rows, col), self._rng)
        path = self._path(tenant_id, pipeline_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({k: v.model_dump() for k, v in baselines.items()}), encoding="utf-8")
