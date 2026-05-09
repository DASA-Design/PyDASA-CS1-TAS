"""Tests for `src.experimental.prototype.calibration.hoststats`.

Logic-only checks at tiny shapes; the notebook validates the actual measurements.
"""

from __future__ import annotations

from src.experimental.prototype.calibration.hoststats import (
    _stats_us,
    probe_handler_scaling,
    probe_jitter,
    probe_loopback,
    probe_timer,
)


class TestHoststats:
    """Percentile helper + four host-floor probes."""

    def test_stats_us_empty(self) -> None:
        """Empty input returns zeros for every key so probes can ship a no-data sentinel without raising."""
        _ans = _stats_us([])
        for _key in ("min_us", "max_us", "mean_us", "std_us",
                     "median_us", "p95_us", "p99_us"):
            assert _ans[_key] == 0.0

    def test_stats_us_typical(self) -> None:
        """A typical sample input produces values inside the input range, with mean / median between min and max and percentiles in non-decreasing order."""
        _samples = [float(_v) for _v in range(10, 110, 10)]  # 10..100 us
        _ans = _stats_us(_samples)
        assert _ans["min_us"] == 10.0
        assert _ans["max_us"] == 100.0
        assert 10.0 <= _ans["median_us"] <= 100.0
        assert 10.0 <= _ans["mean_us"] <= 100.0
        assert _ans["std_us"] > 0.0
        assert _ans["median_us"] <= _ans["p95_us"]
        assert _ans["p95_us"] <= _ans["p99_us"]

    def test_timer_shape(self) -> None:
        """Probing the timer at a tiny sample size returns the documented stats dict."""
        _ans = probe_timer(samples_n=10)
        for _key in ("samples_n", "median_ns", "mean_ns", "std_ns",
                     "min_ns", "max_ns"):
            assert _key in _ans

    def test_timer_zero_samples(self) -> None:
        """Asking for zero samples returns the empty-shape sentinel instead of raising; every numeric field is zero."""
        _ans = probe_timer(samples_n=0)
        assert _ans == {"samples_n": 0,
                        "median_ns": 0,
                        "mean_ns": 0.0,
                        "std_ns": 0.0,
                        "min_ns": 0,
                        "max_ns": 0}

    def test_jitter_shape(self) -> None:
        """Probing jitter at a tiny shape returns the documented percentile dict."""
        _ans = probe_jitter(samples_n=3, target_us=100)
        assert _ans["samples_n"] == 3
        assert _ans["target_us"] == 100
        for _key in ("median_us", "p95_us", "p99_us"):
            assert _key in _ans

    def test_loopback_shape(self) -> None:
        """Probing loopback at a tiny shape stands up the daemon echo, runs the round-trips, and returns the documented dict."""
        _ans = probe_loopback(samples_n=3, payload_bytes=32)
        assert _ans["samples_n"] == 3
        assert _ans["payload_bytes"] == 32
        for _key in ("median_us", "p95_us", "p99_us"):
            assert _key in _ans

    def test_scaling_shape(self) -> None:
        """Probing handler scaling with start/stop/step returns one stats block per c walked, keyed by the concurrency value."""
        _ans = probe_handler_scaling(start=1,
                                     stop=2,
                                     step=1,
                                     samples_per_c=2,
                                     max_drift_pct=100.0)
        assert _ans["concurs"] == [1, 2]
        assert set(_ans["stats"].keys()) == {"1", "2"}
        for _key in ("samples_n", "median_us", "p95_us", "p99_us"):
            assert _key in _ans["stats"]["1"]

    def test_scaling_self_terminates_on_drift(self) -> None:
        """Setting `max_drift_pct=0.0` forces the probe to stop after the second concurrency (any drift breaks the band)."""
        _ans = probe_handler_scaling(start=1,
                                     stop=64,
                                     step=1,
                                     samples_per_c=1,
                                     max_drift_pct=0.0)
        # First c is recorded unconditionally; the drift check fires on the next.
        assert len(_ans["concurs"]) <= 2
        assert _ans["concurs"][0] == 1
