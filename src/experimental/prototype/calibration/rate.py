"""Rate-saturation discovery against the vernier.

Walks a linear lambda ramp, measures per-rate latency + loss, halts as soon as either band breaks. Output fills the envelope's `rate` block.

Three pieces, separated so the orchestration is testable without real HTTP:

- `make_lambda_ramp`: pure ramp generator.
- `detect_saturation`: pure verdict (`saturated`, `saturation_rate`, `reason`).
- `probe_rate`: orchestrator. Walks the ramp, calls a `driver` per rate, halts on breach. The default driver opens a real `httpx.AsyncClient`; tests inject a fake.

The driver round-robins requests across `target_urls`, so a multi-worker deployment can be driven aggregate-style by a single client ramp.

Defaults are runtime fallbacks for `data/config/method/prototype/calibration.json::rate.*`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx

from src.experimental.prototype.calibration.hoststats import _stats_us
from src.experimental.prototype.runtime.async_loop import run_async_safe
from src.experimental.prototype.runtime.os_timer import windows_timer_resolution

# Runtime fallbacks for data/config/method/prototype/calibration.json::rate.*.
_DFLT_LAMBDA_START = 50
_DFLT_LAMBDA_STOP = 1000
_DFLT_LAMBDA_STEP = 50
_DFLT_PER_RATE_S = 5.0
_DFLT_TARGET_LOSS_PCT = 5.0
_DFLT_MAX_P95_LATENCY_US = 100_000.0  # 100 ms
_DFLT_REQ_TIMEOUT_S = 2.0

RateDriver = Callable[[list[str], int, float], dict[str, Any]]


def make_lambda_ramp(*,
                     start: int,
                     stop: int,
                     step: int) -> list[int]:
    """Build a linear rate ramp from `start` to `stop` (inclusive) by `step`.

    Args:
        start (int): first rate in the ramp (req/s).
        stop (int): last rate in the ramp (req/s); inclusive when `(stop - start)` is a multiple of `step`.
        step (int): increment between consecutive rates; must be positive.

    Returns:
        list[int]: ordered list of integer rates.

    Raises:
        ValueError: if `step <= 0`.
    """
    if step <= 0:
        _msg = f"step must be positive; got {step}"
        raise ValueError(_msg)
    _ans: list[int] = []
    _r = start
    while _r <= stop:
        _ans.append(_r)
        _r += step
    return _ans


def detect_saturation(per_rate_stats: list[dict[str, Any]],
                      *,
                      target_loss_pct: float,
                      max_p95_latency_us: float) -> dict[str, Any]:
    """Scan per-rate stats for the first row that breaches either band.

    Loss is checked before latency, so when both breach the loss reason wins (loss is the more direct symptom).

    Args:
        per_rate_stats (list[dict[str, Any]]): per-rate stats blocks; each must carry `rate`, `loss_pct`, and `p95_us`.
        target_loss_pct (float): max acceptable loss fraction in percent.
        max_p95_latency_us (float): max acceptable p95 latency in microseconds.

    Returns:
        dict[str, Any]: keys `saturated` (bool), `saturation_rate` (int | None), `reason` (str). When no breach is found, `saturated=False`, `saturation_rate=None`, `reason="below all thresholds"`.
    """
    _ans: dict[str, Any] = {
        "saturated": False,
        "saturation_rate": None,
        "reason": "below all thresholds",
    }
    for _row in per_rate_stats:
        _loss = _row.get("loss_pct", 0.0)
        _p95 = _row.get("p95_us", 0.0)
        if _loss > target_loss_pct:
            _ans["saturated"] = True
            _ans["saturation_rate"] = _row["rate"]
            _ans["reason"] = f"loss {_loss:.2f}% > {target_loss_pct:.2f}%"
            return _ans
        if _p95 > max_p95_latency_us:
            _ans["saturated"] = True
            _ans["saturation_rate"] = _row["rate"]
            _ans["reason"] = f"p95 {_p95:.0f} us > {max_p95_latency_us:.0f} us"
            return _ans
    return _ans


async def drive_at_rate(client: httpx.AsyncClient,
                        target_urls: list[str],
                        rate: int,
                        duration_s: float) -> dict[str, Any]:
    """Drive `rate` req/s round-robined across `target_urls` for `duration_s`; return aggregate stats.

    Pure async core; the caller wraps in `windows_timer_resolution(1)` if sub-15 ms pacing is needed on Windows. Each request body is `{"req_id": "calib", "submitted_ts": <time.time()>}`.

    Args:
        client (httpx.AsyncClient): pre-built client. Tests pass an in-memory transport; production passes a real-TCP client.
        target_urls (list[str]): full URLs (or relative paths if the client has a base_url). Requests round-robin across them so a multi-worker deployment can be driven aggregate-style by a single client.
        rate (int): target requests per second.
        duration_s (float): wall-clock window to sustain the rate.

    Returns:
        dict[str, Any]: keys `rate`, `total`, `errors`, `loss_pct`, `median_us`, `p95_us`, `p99_us`.
    """
    _interval_s = 1.0 / rate if rate > 0 else 0.0
    _deadline = time.perf_counter() + duration_s
    _tasks: list[asyncio.Task[tuple[float, bool]]] = []
    _next = time.perf_counter()
    _idx = 0
    _n_urls = len(target_urls)
    while time.perf_counter() < _deadline:
        _url = target_urls[_idx % _n_urls]
        _idx += 1
        _tasks.append(asyncio.create_task(_send_one(client, _url)))
        _next += _interval_s
        _wait = _next - time.perf_counter()
        if _wait > 0:
            await asyncio.sleep(_wait)
    if _tasks:
        _results = await asyncio.gather(*_tasks)
    else:
        _results = []
    _latencies = [_lat for _lat, _ in _results]
    _errors = sum(1 for _, _ok in _results if not _ok)
    _total = len(_results)
    if _total > 0:
        _loss_pct = _errors / _total * 100.0
    else:
        _loss_pct = 0.0
    _ans: dict[str, Any] = {
        "rate": rate,
        "total": _total,
        "errors": _errors,
        "loss_pct": _loss_pct,
    }
    _ans.update(_stats_us(_latencies))
    return _ans


async def _send_one(client: httpx.AsyncClient,
                    target_url: str) -> tuple[float, bool]:
    """Send one POST; return (latency_us, ok).

    `ok` is True iff status < 500 and no transport error fired.

    Args:
        client (httpx.AsyncClient): the open client to use.
        target_url (str): full URL or relative path.

    Returns:
        tuple[float, bool]: (round-trip in microseconds, ok flag).
    """
    _t0 = time.perf_counter()
    _ok = False
    try:
        _resp = await client.post(target_url,
                                  json={"req_id": "calib", "submitted_ts": time.time()})
        if _resp.status_code < 500:
            _ok = True
    except (httpx.HTTPError, OSError):
        _ok = False
    _latency_us = (time.perf_counter() - _t0) * 1_000_000.0
    return _latency_us, _ok


def _drive_at_rate(target_urls: list[str],
                   rate: int,
                   duration_s: float) -> dict[str, Any]:
    """Default `RateDriver`: real httpx client over real TCP, wrapped in `windows_timer_resolution(1)` so Windows' coarse clock doesn't break pacing.

    Args:
        target_urls (list[str]): URLs the requests are POSTed to (round-robined).
        rate (int): target req/s.
        duration_s (float): seconds to sustain the rate.

    Returns:
        dict[str, Any]: same shape as `drive_at_rate`'s return.
    """
    async def _coro() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_DFLT_REQ_TIMEOUT_S) as _client:
            return await drive_at_rate(_client, target_urls, rate, duration_s)
    with windows_timer_resolution(1):
        _ans = run_async_safe(_coro)
    return _ans


def _drive_at_rate_raw(target_urls: list[str],
                       rate: int,
                       duration_s: float) -> dict[str, Any]:
    """Driver variant returning raw latencies (`latencies_us` list) instead of pre-aggregated stats.

    Used by the multi-process driver to merge sample arrays across processes before computing percentiles. Aggregate percentiles cannot be derived from sub-aggregates without bias.

    Args:
        target_urls (list[str]): URLs the requests are POSTed to (round-robined).
        rate (int): target req/s.
        duration_s (float): seconds to sustain the rate.

    Returns:
        dict[str, Any]: keys `rate`, `total`, `errors`, `latencies_us` (list[float]).
    """
    async def _coro() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_DFLT_REQ_TIMEOUT_S) as _client:
            return await _drive_at_rate_raw_async(_client, target_urls, rate, duration_s)
    with windows_timer_resolution(1):
        _ans = run_async_safe(_coro)
    return _ans


async def _drive_at_rate_raw_async(client: httpx.AsyncClient,
                                   target_urls: list[str],
                                   rate: int,
                                   duration_s: float) -> dict[str, Any]:
    """Async core of `_drive_at_rate_raw`: drive the rate, return raw per-request latencies + counts."""
    _interval_s = 1.0 / rate if rate > 0 else 0.0
    _deadline = time.perf_counter() + duration_s
    _tasks: list[asyncio.Task[tuple[float, bool]]] = []
    _next = time.perf_counter()
    _idx = 0
    _n_urls = len(target_urls)
    while time.perf_counter() < _deadline:
        _url = target_urls[_idx % _n_urls]
        _idx += 1
        _tasks.append(asyncio.create_task(_send_one(client, _url)))
        _next += _interval_s
        _wait = _next - time.perf_counter()
        if _wait > 0:
            await asyncio.sleep(_wait)
    if _tasks:
        _results = await asyncio.gather(*_tasks)
    else:
        _results = []
    _latencies = [_lat for _lat, _ in _results]
    _errors = sum(1 for _, _ok in _results if not _ok)
    _ans: dict[str, Any] = {
        "rate": rate,
        "total": len(_results),
        "errors": _errors,
        "latencies_us": _latencies,
    }
    return _ans


def probe_rate(*,
               target_urls: list[str],
               start: int = _DFLT_LAMBDA_START,
               stop: int = _DFLT_LAMBDA_STOP,
               step: int = _DFLT_LAMBDA_STEP,
               per_rate_s: float = _DFLT_PER_RATE_S,
               target_loss_pct: float = _DFLT_TARGET_LOSS_PCT,
               max_p95_latency_us: float = _DFLT_MAX_P95_LATENCY_US,
               driver: RateDriver | None = None) -> dict[str, Any]:
    """Walk the rate ramp against `target_urls`; early-stop on saturation; return the envelope `rate` block.

    Args:
        target_urls (list[str]): URLs the driver POSTs to (round-robined). One element for `localhost`, N elements for `multiprocess`.
        start (int, optional): first rate. Defaults to the runtime fallback.
        stop (int, optional): last rate (inclusive). Defaults to the runtime fallback.
        step (int, optional): rate increment. Defaults to the runtime fallback.
        per_rate_s (float, optional): seconds per rate. Defaults to the runtime fallback.
        target_loss_pct (float, optional): saturation threshold on loss. Defaults to the runtime fallback.
        max_p95_latency_us (float, optional): saturation threshold on p95 latency. Defaults to the runtime fallback.
        driver (RateDriver | None, optional): callable `(urls, rate, duration_s) -> stats_dict`. Defaults to None, which uses the real httpx-based driver. Tests inject a fake.

    Returns:
        dict[str, Any]: envelope-ready block. Keys: `ramp`, `per_rate`, `target_urls`, `target_loss_pct`, `max_p95_latency_us`, plus the `saturated` / `saturation_rate` / `reason` triple from `detect_saturation`.
    """
    if driver is None:
        _driver: RateDriver = _drive_at_rate
    else:
        _driver = driver
    _ramp = make_lambda_ramp(start=start, stop=stop, step=step)
    _per_rate: list[dict[str, Any]] = []
    for _r in _ramp:
        _stats = _driver(target_urls, _r, per_rate_s)
        _per_rate.append(_stats)
        _verdict = detect_saturation(_per_rate,
                                     target_loss_pct=target_loss_pct,
                                     max_p95_latency_us=max_p95_latency_us)
        if _verdict["saturated"]:
            break
    _verdict = detect_saturation(_per_rate,
                                 target_loss_pct=target_loss_pct,
                                 max_p95_latency_us=max_p95_latency_us)
    _ans: dict[str, Any] = {
        "ramp": _ramp,
        "per_rate": _per_rate,
        "target_urls": list(target_urls),
        "target_loss_pct": target_loss_pct,
        "max_p95_latency_us": max_p95_latency_us,
    }
    _ans.update(_verdict)
    return _ans


__all__ = [
    "RateDriver",
    "detect_saturation",
    "drive_at_rate",
    "make_lambda_ramp",
    "probe_rate",
]
