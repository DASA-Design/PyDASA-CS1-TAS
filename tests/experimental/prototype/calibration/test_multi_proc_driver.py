"""Tests for `src.experimental.prototype.calibration.multi_proc_driver`.

Logic-only checks: factory routing, raw-latency aggregation, percentile recomputation. Real spawning is exercised by the notebook end-to-end (the test patches `ProcessPoolExecutor` so no child processes start).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.experimental.prototype.calibration import multi_proc_driver as mpd
from src.experimental.prototype.calibration.multi_proc_driver import (
    _MultiProcDriver,
    _merge_results,
    make_multi_proc_driver,
)
from src.experimental.prototype.calibration.rate import _drive_at_rate


class _FakeFuture:
    """Stand-in for `concurrent.futures.Future`; just wraps a fixed result."""

    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result

    def result(self) -> dict[str, Any]:
        """Return the canned result."""
        return self._result


class _FakeExecutor:
    """Stand-in for `ProcessPoolExecutor`; runs `_drive_at_rate_raw` in-process via a fake function.

    Tests inject canned per-call results so the executor's `submit` returns a `_FakeFuture` without real spawning. Implements the context-manager + `submit` protocol that `_MultiProcDriver` calls.
    """

    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = list(results)
        self.submitted_args: list[tuple[Any, ...]] = []

    def __enter__(self) -> "_FakeExecutor":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> None:
        return None

    def submit(self, _fn: Any, *args: Any) -> _FakeFuture:
        """Pop the next canned result; record args so tests can assert the rate split."""
        self.submitted_args.append(args)
        return _FakeFuture(self._results.pop(0))


class TestMakeMultiProcDriver:
    """`make_multi_proc_driver`: factory routing."""

    def test_n_one_returns_single_proc(self) -> None:
        """With `n_clients <= 1`, the factory returns the existing single-process driver."""
        assert make_multi_proc_driver(1) is _drive_at_rate
        assert make_multi_proc_driver(0) is _drive_at_rate

    def test_n_many_returns_multi_proc(self) -> None:
        """With `n_clients >= 2`, the factory returns a `_MultiProcDriver` instance."""
        _d = make_multi_proc_driver(4)
        assert isinstance(_d, _MultiProcDriver)


class TestMergeResults:
    """`_merge_results`: aggregate raw latencies + counts across child processes."""

    def test_totals_summed(self) -> None:
        """Total + errors are summed across sub-results; loss_pct is recomputed."""
        _subs = [
            {"total": 100, "errors": 5, "latencies_us": [100.0] * 95 + [200.0] * 5},
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
        ]
        _ans = _merge_results(target_rate=400, sub_results=_subs)
        assert _ans["rate"] == 400
        assert _ans["total"] == 200
        assert _ans["errors"] == 5
        assert _ans["loss_pct"] == pytest.approx(2.5)

    def test_percentiles_from_raw(self) -> None:
        """Aggregate percentiles come from the merged raw list, not from sub-aggregates."""
        _subs = [
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
            {"total": 100, "errors": 0, "latencies_us": [200.0] * 100},
        ]
        _ans = _merge_results(target_rate=200, sub_results=_subs)
        # The merged list is [100]*100 + [200]*100; median falls in the 200 half (index 100).
        assert _ans["min_us"] == 100.0
        assert _ans["max_us"] == 200.0

    def test_empty_sub_results(self) -> None:
        """Zero sub-results yield zero total + zero loss without raising."""
        _ans = _merge_results(target_rate=100, sub_results=[])
        assert _ans["total"] == 0
        assert _ans["errors"] == 0
        assert _ans["loss_pct"] == 0.0


class TestMultiProcDriverCall:
    """`_MultiProcDriver.__call__`: rate split + result aggregation (executor patched)."""

    def test_rate_split_evenly(self) -> None:
        """The aggregate rate is divided evenly across child processes."""
        _stub_results = [
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
            {"total": 100, "errors": 0, "latencies_us": [100.0] * 100},
        ]
        _fake_exe = _FakeExecutor(_stub_results)
        with patch.object(mpd, "ProcessPoolExecutor", return_value=_fake_exe):
            _d = _MultiProcDriver(n_clients=4)
            _ans = _d(["http://t/0"], 800, 1.0)
        assert _ans["rate"] == 800
        assert _ans["total"] == 400
        # Each submission should have asked for 200 req/s (800 / 4).
        for _args in _fake_exe.submitted_args:
            assert _args[1] == 200

    def test_aggregate_stats_computed(self) -> None:
        """The aggregated dict carries `_stats_us` keys derived from the merged latency list."""
        _stub_results = [
            {"total": 50, "errors": 0, "latencies_us": [100.0] * 50},
            {"total": 50, "errors": 0, "latencies_us": [200.0] * 50},
        ]
        _fake_exe = _FakeExecutor(_stub_results)
        with patch.object(mpd, "ProcessPoolExecutor", return_value=_fake_exe):
            _d = _MultiProcDriver(n_clients=2)
            _ans = _d(["http://t/0"], 200, 1.0)
        for _key in ("min_us", "max_us", "median_us", "p95_us", "p99_us"):
            assert _key in _ans
