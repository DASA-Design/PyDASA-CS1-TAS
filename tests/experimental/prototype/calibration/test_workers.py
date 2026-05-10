"""Tests for `src.experimental.prototype.calibration.workers`.

Logic-only checks: ramp shape, knee detection, probe orchestration with a fake `make_targets` and a deterministic driver. Real spawning is exercised by the notebook end-to-end.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest

from src.experimental.prototype.calibration.workers import (
    detect_efficiency_knee,
    make_workers_ramp,
    probe_workers_scaling,
)


@contextmanager
def _fake_targets(n: int):
    """Yield `n` fake URLs as a context manager (no real spawning)."""
    yield [f"http://test/{n}/{_i}" for _i in range(n)]


def _ideal_driver(urls: list[str],
                  rate: int,
                  duration_s: float) -> dict[str, Any]:
    """Return driver stats for an ideally-scaling apparatus (every request succeeds).

    Args:
        urls (list[str]): worker URLs (length = current n_workers).
        rate (int): target request rate (req/s).
        duration_s (float): drive window in seconds.

    Returns:
        dict[str, Any]: stats dict with `total = rate * duration_s`, zero errors, fixed latency percentiles.
    """
    _total = int(rate * duration_s)
    _ans: dict[str, Any] = {
        "rate": rate,
        "total": _total,
        "errors": 0,
        "loss_pct": 0.0,
        "min_us": 100.0,
        "max_us": 200.0,
        "mean_us": 120.0,
        "std_us": 10.0,
        "median_us": 110.0,
        "p95_us": 180.0,
        "p99_us": 195.0,
    }
    return _ans


class _FailingDriver:
    """Driver whose throughput collapses to 40 % once `n_workers >= threshold_n`.

    Usable as a `RateDriver` (instances are callable). Lets tests build a deterministic efficiency curve without nested closures.
    """

    def __init__(self, *, threshold_n: int) -> None:
        self._threshold_n = threshold_n

    def __call__(self,
                 urls: list[str],
                 rate: int,
                 duration_s: float) -> dict[str, Any]:
        """Stats for one ramp step; total scales with the threshold rule."""
        _n = len(urls)
        if _n >= self._threshold_n:
            _total = int(rate * duration_s * 0.4)
        else:
            _total = int(rate * duration_s)
        _ans: dict[str, Any] = {
            "rate": rate,
            "total": _total,
            "errors": 0,
            "loss_pct": 0.0,
            "min_us": 100.0,
            "max_us": 200.0,
            "mean_us": 120.0,
            "std_us": 10.0,
            "median_us": 110.0,
            "p95_us": 180.0,
            "p99_us": 195.0,
        }
        return _ans


class TestWorkersRamp:
    """`make_workers_ramp`: pure additive generator."""

    def test_shape(self) -> None:
        """A start/stop/step triple produces the expected inclusive ramp."""
        assert make_workers_ramp(start=1, stop=4, step=1) == [1, 2, 3, 4]
        assert make_workers_ramp(start=1, stop=8, step=2) == [1, 3, 5, 7]

    def test_step_zero_raises(self) -> None:
        """Non-positive step raises ValueError so misconfigurations fail loudly."""
        with pytest.raises(ValueError, match="step must be positive"):
            make_workers_ramp(start=1, stop=8, step=0)


class TestEfficiencyKnee:
    """`detect_efficiency_knee`: pure verdict over per-step rows."""

    def test_all_in_band(self) -> None:
        """When every row is at or above threshold, the highest n is the stable count."""
        _rows = [
            {"n_workers": 1, "efficiency_pct": 100.0},
            {"n_workers": 2, "efficiency_pct": 95.0},
            {"n_workers": 4, "efficiency_pct": 88.0},
        ]
        _v = detect_efficiency_knee(_rows, min_eff_pct=80.0)
        assert _v["stable_workers"] == 4

    def test_knee_found(self) -> None:
        """The first row below threshold ends the band; the previous row is the knee."""
        _rows = [
            {"n_workers": 1, "efficiency_pct": 100.0},
            {"n_workers": 2, "efficiency_pct": 95.0},
            {"n_workers": 4, "efficiency_pct": 50.0},
        ]
        _v = detect_efficiency_knee(_rows, min_eff_pct=80.0)
        assert _v["stable_workers"] == 2
        assert "knee at n=4" in _v["reason"]

    def test_no_headroom(self) -> None:
        """When even n=1 is below threshold, stable_workers is None."""
        _rows = [{"n_workers": 1, "efficiency_pct": 50.0}]
        _v = detect_efficiency_knee(_rows, min_eff_pct=80.0)
        assert _v["stable_workers"] is None
        assert "no parallel headroom" in _v["reason"]

    def test_empty(self) -> None:
        """Empty rows yield None + 'no steps recorded'."""
        _v = detect_efficiency_knee([], min_eff_pct=80.0)
        assert _v["stable_workers"] is None
        assert _v["reason"] == "no steps recorded"


class TestProbeWorkersScaling:
    """End-to-end probe with fake `make_targets` + deterministic drivers."""

    def test_ideal_ramp_full(self) -> None:
        """An ideal driver records every step in the ramp; stable_workers is the max."""
        _ans = probe_workers_scaling(start=1,
                                     stop=4,
                                     step=1,
                                     per_step_s=1.0,
                                     rate_per_worker=100,
                                     min_eff_pct=80.0,
                                     make_targets=_fake_targets,
                                     driver=_ideal_driver)
        assert _ans["ramp"] == [1, 2, 3, 4]
        assert len(_ans["per_step"]) == 4
        assert _ans["stable_workers"] == 4
        for _row in _ans["per_step"]:
            assert _row["efficiency_pct"] == pytest.approx(100.0)

    def test_halts_on_drop(self) -> None:
        """When efficiency drops below threshold, the probe halts at the first failing step."""
        _ans = probe_workers_scaling(start=1,
                                     stop=8,
                                     step=1,
                                     per_step_s=1.0,
                                     rate_per_worker=100,
                                     min_eff_pct=80.0,
                                     make_targets=_fake_targets,
                                     driver=_FailingDriver(threshold_n=3))
        assert _ans["stable_workers"] == 2
        assert len(_ans["per_step"]) == 3

    def test_per_step_keys(self) -> None:
        """Each per-step row carries all derived fields."""
        _ans = probe_workers_scaling(start=1,
                                     stop=2,
                                     step=1,
                                     per_step_s=1.0,
                                     rate_per_worker=100,
                                     min_eff_pct=80.0,
                                     make_targets=_fake_targets,
                                     driver=_ideal_driver)
        for _row in _ans["per_step"]:
            for _key in ("n_workers", "rate_target", "actual_rps",
                         "per_worker_rps", "efficiency_pct"):
                assert _key in _row
