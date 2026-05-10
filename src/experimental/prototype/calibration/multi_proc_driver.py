"""Multi-process load generator for the workers ramp.

Single-process httpx clients saturate around 1-1.5k req/s on Python; past that the client itself becomes the bottleneck and the workers ramp mis-attributes 'client busy' as 'workers saturated'. This module fans the load out across N driver processes so each one stays well below its own saturation. The aggregator merges the raw latency lists (NOT pre-computed percentiles) before recomputing one combined `_stats_us` block, so the percentiles stay statistically valid.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any

from src.experimental.prototype.calibration.hoststats import _stats_us
from src.experimental.prototype.calibration.rate import (
    RateDriver,
    _drive_at_rate,
    drive_at_rate_raw,
)


def make_multi_proc_driver(n_clients: int) -> RateDriver:
    """Build a `RateDriver` that fans the rate out across `n_clients` driver processes.

    With `n_clients <= 1` the function returns the existing single-process driver so callers can wire this in unconditionally and rely on the value to switch behaviour.

    Args:
        n_clients (int): number of driver processes to spawn per ramp step.

    Returns:
        RateDriver: callable `(urls, rate, duration_s) -> stats`. Identity-equal to `_drive_at_rate` when `n_clients <= 1`; an instance of `_MultiProcDriver` otherwise.
    """
    if n_clients <= 1:
        _ans: RateDriver = _drive_at_rate
    else:
        _ans = _MultiProcDriver(n_clients=n_clients)
    return _ans


class _MultiProcDriver:
    """Callable `RateDriver` that splits the requested rate across N child processes.

    Each child runs `drive_at_rate_raw`, returning its raw latency list. The parent merges the lists and recomputes a single aggregate stats block. Each child opens its own `httpx.AsyncClient`, so the IO bottleneck moves from "one event loop" to "N event loops".
    """

    def __init__(self, *, n_clients: int) -> None:
        self._n_clients = n_clients

    def __call__(self,
                 target_urls: list[str],
                 rate: int,
                 duration_s: float) -> dict[str, Any]:
        """Fan out the rate across processes; merge results.

        Args:
            target_urls (list[str]): vernier URLs to drive.
            rate (int): aggregate target rate (req/s); split evenly across processes.
            duration_s (float): drive window in seconds.

        Returns:
            dict[str, Any]: same shape as `_drive_at_rate`'s output (`rate`, `total`, `errors`, `loss_pct`, plus the `_stats_us` keys).
        """
        _per_client = max(1, rate // self._n_clients)
        _futures = []
        with ProcessPoolExecutor(max_workers=self._n_clients) as _exe:
            _i = 0
            while _i < self._n_clients:
                _futures.append(_exe.submit(drive_at_rate_raw,
                                            target_urls,
                                            _per_client,
                                            duration_s))
                _i += 1
            _results = [_f.result() for _f in _futures]
        return _merge_results(target_rate=rate, sub_results=_results)


def _merge_results(*,
                   target_rate: int,
                   sub_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-process raw-latency results into one aggregate stats block.

    Args:
        target_rate (int): the aggregate rate the caller asked for; recorded in the output `rate` field.
        sub_results (list[dict[str, Any]]): one entry per child process (output of `drive_at_rate_raw`).

    Returns:
        dict[str, Any]: aggregate stats. Keys: `rate`, `total`, `errors`, `loss_pct`, `min_us`, `max_us`, `mean_us`, `std_us`, `median_us`, `p95_us`, `p99_us`.
    """
    _total = 0
    _errors = 0
    _latencies: list[float] = []
    for _r in sub_results:
        _total += int(_r.get("total", 0))
        _errors += int(_r.get("errors", 0))
        _latencies.extend(_r.get("latencies_us", []))
    if _total > 0:
        _loss_pct = _errors / _total * 100.0
    else:
        _loss_pct = 0.0
    _ans: dict[str, Any] = {
        "rate": target_rate,
        "total": _total,
        "errors": _errors,
        "loss_pct": _loss_pct,
    }
    _ans.update(_stats_us(_latencies))
    return _ans


__all__ = [
    "make_multi_proc_driver",
]
