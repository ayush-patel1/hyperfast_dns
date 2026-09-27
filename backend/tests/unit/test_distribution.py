import random

import numpy as np

from app.contracts.model import DriftPolicy
from app.detection.distribution import (
    BaselineStore,
    ColumnBaseline,
    compare_to_baseline,
    ks_statistic,
    population_stability_index,
)

POLICY = DriftPolicy(columns=["age"], min_baseline=200)


def _baseline(values) -> ColumnBaseline:
    b = ColumnBaseline(column="age")
    b.absorb(values, random.Random(0))
    return b


def _ages(n, mu=38, sd=11, seed=1):
    rng = random.Random(seed)
    return [float(int(min(90, max(18, rng.gauss(mu, sd))))) for _ in range(n)]


def test_same_distribution_is_not_drift():
    report = compare_to_baseline(_baseline(_ages(1000)), _ages(500, seed=2), POLICY)
    assert report is not None and not report.drifted
    assert report.psi < 0.1


def test_unit_change_is_drift_with_multiple_signals():
    bands = [min(6, max(1, int(a // 10) - 1)) for a in _ages(500, seed=3)]
    report = compare_to_baseline(_baseline(_ages(1000)), bands, POLICY)
    assert report.drifted
    assert len(report.signals) >= 2


def test_single_signal_does_not_trigger_drift():
    # a modest shift trips PSI but not KS/mean-shift thresholds
    report = compare_to_baseline(_baseline(_ages(2000)), _ages(500, mu=42, seed=4),
                                 DriftPolicy(psi_threshold=0.05, ks_threshold=0.5, mean_shift_sigma=3))
    assert report.signals and not report.drifted


def test_insufficient_baseline_returns_none():
    assert compare_to_baseline(_baseline(_ages(50)), _ages(500), POLICY) is None


def test_psi_and_ks_bounds():
    a = np.array(_ages(1000))
    assert population_stability_index(a, a) < 1e-3
    assert ks_statistic(a, a) == 0.0
    assert ks_statistic(a, a + 1000) == 1.0


def test_reservoir_bounded_and_persisted(tmp_path):
    store = BaselineStore(tmp_path)
    for i in range(3):
        store.update("t", "p", [{"age": float(x)} for x in _ages(1000, seed=i)], ["age"])
    loaded = store.load("t", "p")["age"]
    assert loaded.count == 3000
    assert len(loaded.sample) == 2000
