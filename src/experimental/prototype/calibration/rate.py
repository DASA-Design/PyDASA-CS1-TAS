"""Rate-saturation discovery against the vernier.

Drives a target URL through a linear lambda ramp, measures per-rate latency + error rate, and stops as soon as either band is breached. Output fills the envelope's `rate` block.

Three pieces, kept separate so the orchestration is testable without driving real HTTP:

- `make_lambda_ramp(start, stop, step)`: pure ramp generator.
- `detect_saturation(per_rate_stats, target_loss_pct, max_p95_latency_us)`: pure verdict (`saturated`, `saturation_rate`, `reason`).
- `probe_rate(*, target_url, ..., driver=None)`: orchestrator that walks the ramp and early-stops on breach. Tests inject a fake `driver`; the default driver opens a real `httpx.AsyncClient` inside `windows_timer_resolution(1)`.

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

RateDriver = Callable[[str, int, float], dict[str, Any]]


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

    Loss is checked before latency at each rate, so when both breach simultaneously the loss reason wins (which is what an operator wants to see — loss is the more direct symptom).

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
                        target_url: str,
                        rate: int,
                        duration_s: float) -> dict[str, Any]:
    """Drive `rate` req/s against `target_url` for `duration_s`; return aggregate stats.

    Pure async core, no `windows_timer_resolution` wrapping (caller's responsibility). Pace is enforced by `asyncio.sleep` between sends; on Windows precision below ~15 ms requires the caller to sit inside `windows_timer_resolution(1)`. The vernier echo body is `{"req_id": "calib", "submitted_ts": <time.time()>}` — minimal but accepted by the vernier handler.

    Args:
        client (httpx.AsyncClient): pre-built client. Tests pass an in-memory transport; production passes a real-TCP client.
        target_url (str): full URL or relative path (depending on the client's base_url).
        rate (int): target requests per second.
        duration_s (float): wall-clock window to sustain the rate.

    Returns:
        dict[str, Any]: keys `rate`, `total`, `errors`, `loss_pct`, `median_us`, `p95_us`, `p99_us`.
    """
    _interval_s = 1.0 / rate if rate > 0 else 0.0
    _deadline = time.perf_counter() + duration_s
    _tasks: list[asyncio.Task[tuple[float, bool]]] = []
    _next = time.perf_counter()
    while time.perf_counter() < _deadline:
        _tasks.append(asyncio.create_task(_send_one(client, target_url)))
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
    """Send one POST and report (latency_us, ok).

    `ok` is True for HTTP < 500 with no transport error; any HTTPError / OSError, or any 5xx response, counts as not-ok.

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


def _drive_at_rate(target_url: str,
                   rate: int,
                   duration_s: float) -> dict[str, Any]:
    """Default `RateDriver`: real httpx client + real TCP loopback (or whatever the URL resolves to).

    Wraps the async core in `windows_timer_resolution(1)` so Windows' clock floor doesn't blow up the inter-send pacing.

    Args:
        target_url (str): full URL the requests are POSTed to.
        rate (int): target req/s.
        duration_s (float): seconds to sustain the rate.

    Returns:
        dict[str, Any]: same shape as `drive_at_rate`'s return.
    """
    async def _coro() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_DFLT_REQ_TIMEOUT_S) as _client:
            return await drive_at_rate(_client, target_url, rate, duration_s)
    with windows_timer_resolution(1):
        _ans = run_async_safe(_coro)
    return _ans


def probe_rate(*,
               target_url: str,
               start: int = _DFLT_LAMBDA_START,
               stop: int = _DFLT_LAMBDA_STOP,
               step: int = _DFLT_LAMBDA_STEP,
               per_rate_s: float = _DFLT_PER_RATE_S,
               target_loss_pct: float = _DFLT_TARGET_LOSS_PCT,
               max_p95_latency_us: float = _DFLT_MAX_P95_LATENCY_US,
               driver: RateDriver | None = None) -> dict[str, Any]:
    """Walk the rate ramp against `target_url`; early-stop on saturation; return the envelope `rate` block.

    Args:
        target_url (str): URL the driver POSTs to.
        start (int, optional): first rate. Defaults to the runtime fallback.
        stop (int, optional): last rate (inclusive). Defaults to the runtime fallback.
        step (int, optional): rate increment. Defaults to the runtime fallback.
        per_rate_s (float, optional): seconds per rate. Defaults to the runtime fallback.
        target_loss_pct (float, optional): saturation threshold on loss. Defaults to the runtime fallback.
        max_p95_latency_us (float, optional): saturation threshold on p95 latency. Defaults to the runtime fallback.
        driver (RateDriver | None, optional): callable `(url, rate, duration_s) -> stats_dict`. Defaults to None, which uses the real httpx-based driver. Tests inject a fake.

    Returns:
        dict[str, Any]: envelope-ready block. Keys: `ramp`, `per_rate`, `target_loss_pct`, `max_p95_latency_us`, plus the `saturated` / `saturation_rate` / `reason` triple from `detect_saturation`.
    """
    if driver is None:
        _driver: RateDriver = _drive_at_rate
    else:
        _driver = driver
    _ramp = make_lambda_ramp(start=start,
                             stop=stop,
                             step=step)
    _per_rate: list[dict[str, Any]] = []
    for _r in _ramp:
        _stats = _driver(target_url, _r, per_rate_s)
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
