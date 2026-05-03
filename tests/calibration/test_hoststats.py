# -*- coding: utf-8 -*-
"""
Module test_hoststats.py
========================

Pin the boundary contract of the host-floor probes and stats helpers. The pure (no-network) probes (`measure_timer`, `measure_jitter`) and the stats functions (`stats_from_us_array`, `stats_from_us_status_pairs`) run inline; the network probes (`measure_loopback`, `measure_handler_scaling`) are exercised end-to-end against a `UvicornThread`-backed gauge under `@pytest.mark.live_mesh`.

`snapshot_host_profile` is a smoke test: only structural keys + types are asserted (real values depend on the test host).

    - **TestHostStats** stats helpers (empty arrays, success-only filtering, per-status counts), pure-Python probes (timer, jitter), host-profile snapshot, and (live-mesh) loopback + handler-scaling against a real gauge on loopback.
"""
# native python modules
import asyncio
import socket

# testing framework
import pytest

# scientific stack
import numpy as np

# module under test
from src.calibration import (measure_handler_scaling,
                             measure_jitter,
                             measure_loopback,
                             measure_timer,
                             snapshot_host_profile,
                             stats_from_us_array,
                             stats_from_us_status_pairs)
from src.experiment.instances import build_gauge
from src.experiment.runtime import UvicornThread
from src.experiment.services import SvcSpec


def _free_port() -> int:
    """*_free_port()* return an ephemeral port; bind immediately, the kernel may reassign before the next call.

    Returns:
        int: ephemeral TCP port number.
    """
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    _port = int(_s.getsockname()[1])
    _s.close()
    return _port


def _vernier_spec(port: int) -> SvcSpec:
    """*_vernier_spec()* canonical calibration vernier spec: `c=1, K=10, mu=0, epsilon=0`.

    Args:
        port (int): TCP port for the spec.

    Returns:
        SvcSpec: vernier spec named `"CALIB"`, role `"atomic"`.
    """
    return SvcSpec(name="CALIB",
                   role="atomic",
                   port=int(port),
                   mu=0.0,
                   epsilon=0.0,
                   c=1,
                   K=10,
                   seed=0,
                   mem_per_buffer=0)


class TestHostStats:
    """**TestHostStats** stats helpers (empty arrays, success-only filter, per-status counts), pure-Python probes (timer, jitter), and host-profile snapshot. The live-mesh tests exercise `measure_loopback` and `measure_handler_scaling` end-to-end against a real `UvicornThread`-backed gauge."""

    def test_stats_empty(self) -> None:
        """*test_stats_empty()* `stats_from_us_array(np.array([]))` returns the zero-valued 6-key dict; `samples == 0`."""
        _s = stats_from_us_array(np.asarray([], dtype=np.float64))
        assert _s == {
            "min_us": 0.0, "median_us": 0.0, "p95_us": 0.0,
            "p99_us": 0.0, "std_us": 0.0, "samples": 0,
        }

    def test_stats_simple(self) -> None:
        """*test_stats_simple()* a 5-element array gives the expected min, median, samples; types are float for stats and int for `samples`."""
        _s = stats_from_us_array(np.asarray([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert _s["min_us"] == 1.0
        assert _s["median_us"] == 3.0
        assert _s["samples"] == 5
        assert isinstance(_s["samples"], int)

    def test_pairs_empty(self) -> None:
        """*test_pairs_empty()* `stats_from_us_status_pairs([])` returns the zero-valued dict with all per-status counts at zero."""
        _s = stats_from_us_status_pairs([])
        assert _s["samples"] == 0
        assert _s["total_count"] == 0
        assert _s["succ_count"] == 0
        assert _s["reject_count"] == 0
        assert _s["infra_fail_count"] == 0
        assert _s["reject_rate"] == 0.0

    def test_pairs_success_only(self) -> None:
        """*test_pairs_success_only()* with mixed statuses, latency stats are computed over `status == 200` only; the 503 and infra-fail rows do not contribute to `median_us`."""
        _pairs = [
            (1000, 200), (2000, 200), (3000, 200),
            (50, 503), (60, 503),
            (10, 0),
        ]
        _s = stats_from_us_status_pairs(_pairs)
        assert _s["total_count"] == 6
        assert _s["succ_count"] == 3
        assert _s["reject_count"] == 2
        assert _s["infra_fail_count"] == 1
        assert _s["reject_rate"] == pytest.approx(2 / 6)
        assert _s["median_us"] == pytest.approx(2.0)

    def test_pairs_all_rejected(self) -> None:
        """*test_pairs_all_rejected()* a row of all 503s gives `samples == 0`, `reject_rate == 1.0`, and zero latency stats."""
        _pairs = [(50, 503), (60, 503), (70, 503)]
        _s = stats_from_us_status_pairs(_pairs)
        assert _s["samples"] == 0
        assert _s["reject_count"] == 3
        assert _s["reject_rate"] == 1.0
        assert _s["median_us"] == 0.0

    def test_timer_shape(self) -> None:
        """*test_timer_shape()* `measure_timer(100)` returns the 5-key dict; `min_ns >= 0`; `zero_frac` in `[0, 1]`."""
        _t = measure_timer(100)
        assert set(_t.keys()) == {"min_ns", "median_ns", "mean_ns",
                                  "std_ns", "zero_frac"}
        assert _t["min_ns"] >= 0
        assert 0.0 <= _t["zero_frac"] <= 1.0

    def test_timer_zero_samples(self) -> None:
        """*test_timer_zero_samples()* `measure_timer(0)` returns the all-zero dict with `zero_frac == 1.0`."""
        _t = measure_timer(0)
        assert _t["min_ns"] == 0
        assert _t["median_ns"] == 0.0
        assert _t["zero_frac"] == 1.0

    def test_jitter_shape(self) -> None:
        """*test_jitter_shape()* `measure_jitter(5)` returns the 5-key dict; percentile ordering: `max_us >= p99_us >= p50_us`."""
        _j = measure_jitter(5)
        assert set(_j.keys()) == {"mean_us", "std_us", "p50_us",
                                  "p99_us", "max_us"}
        assert _j["max_us"] >= _j["p99_us"]
        assert _j["p99_us"] >= _j["p50_us"]

    def test_host_profile_keys(self) -> None:
        """*test_host_profile_keys()* `snapshot_host_profile()` returns the documented 8 keys; `hostname` is a non-empty string; `cpu_count` is a positive int."""
        _h = snapshot_host_profile()
        assert set(_h.keys()) == {"hostname", "os", "python", "python_impl",
                                  "cpu_count", "cpu_machine", "cpu_processor",
                                  "ram_total_gb"}
        assert isinstance(_h["hostname"], str)
        assert len(_h["hostname"]) > 0
        assert isinstance(_h["cpu_count"], int)
        assert _h["cpu_count"] > 0

    @pytest.mark.live_mesh
    def test_loopback_live(self) -> None:
        """*test_loopback_live()* spin up a real `UvicornThread`-backed gauge; `measure_loopback(port, samples=20, warmup=5)` returns 20 samples with `median_us > 0`."""
        _port = _free_port()
        _app = build_gauge(_vernier_spec(_port), payload_size_bytes=128)
        _t = UvicornThread(_app, port=_port)
        try:
            _t.start()
            _t.wait_ready(timeout_s=5.0)
            _stats = asyncio.run(measure_loopback(_port,
                                                  samples=20,
                                                  warmup=5,
                                                  payload_size_bytes=128))
        finally:
            _t.shutdown()
        assert _stats["samples"] == 20
        assert _stats["median_us"] > 0.0

    @pytest.mark.live_mesh
    def test_handler_scaling_live(self) -> None:
        """*test_handler_scaling_live()* spin up a real `UvicornThread`-backed gauge; `measure_handler_scaling(port, n_con_usr=(1, 4), warmup=2, samples_per_level=20, inter_level_delay_s=0.0)` returns one stats dict per level keyed by the n_con_usr value as str."""
        _port = _free_port()
        _app = build_gauge(_vernier_spec(_port), payload_size_bytes=128)
        _t = UvicornThread(_app, port=_port)
        try:
            _t.start()
            _t.wait_ready(timeout_s=5.0)
            _result = asyncio.run(measure_handler_scaling(
                _port,
                n_con_usr=(1, 4),
                warmup=2,
                samples_per_level=20,
                inter_level_delay_s=0.0,
                payload_size_bytes=128))
        finally:
            _t.shutdown()
        assert set(_result.keys()) == {"1", "4"}
        for _key in ("1", "4"):
            _stats = _result[_key]
            assert _stats["total_count"] > 0
            assert "median_us" in _stats
