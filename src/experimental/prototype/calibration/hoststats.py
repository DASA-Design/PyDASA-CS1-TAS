"""Host-floor probes: timer, jitter, loopback, handler scaling.

Four pure-Python probes that quantify how quiet the host is before any experiment runs. Each fills the matching envelope block. None touches the vernier or HTTP; the goal is to characterise the platform itself.

- `probe_timer`: median delta between consecutive `time.perf_counter_ns()` reads (clock floor).
- `probe_jitter`: actual elapsed time of `asyncio.sleep(target)` (scheduler precision).
- `probe_loopback`: TCP round-trip on a 127.0.0.1 socket pair (kernel + socket floor).
- `probe_handler_scaling`: latency of a no-op async handler at increasing concurrency (event-loop saturation knee).

**Statistics terminology** (used by every probe's output dict):

- `median` (also written `p50`): the middle value when samples are sorted; half are below, half above. Robust against outliers and the headline summary for skewed latency data.
- `p95`: the 95th-percentile value; 95 % of samples are at or below it. Captures the typical tail.
- `p99`: the 99th-percentile value; the slow-but-not-catastrophic tail.
- `min` / `max`: extremes of the sample. Useful for clock-tick probes where the spread itself is the signal.
- The arithmetic mean is intentionally NOT reported. Sample distributions here are skewed (long upper tail), so median + percentiles describe them better than the average.

Defaults are runtime fallbacks for `data/config/method/prototype/calibration.json::hoststats.*`.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import Any

from src.experimental.prototype.runtime.async_loop import run_async_safe
from src.experimental.prototype.runtime.os_timer import windows_timer_resolution

# Runtime fallbacks for data/config/method/prototype/calibration.json::hoststats.*.
_DFLT_TIMER_SAMPLES = 1000
_DFLT_JITTER_SAMPLES = 100
_DFLT_JITTER_TARGET_US = 1000
_DFLT_LOOPBACK_SAMPLES = 100
_DFLT_LOOPBACK_PAYLOAD = 64
_DFLT_SCALING_CONCURS: tuple[int, ...] = (1, 2, 4, 8, 16)
_DFLT_SCALING_SAMPLES_PER_C = 10


def _stats_us(samples_us: list[float]) -> dict[str, float]:
    """Compute p50 / p95 / p99 over a list of microsecond samples.

    Args:
        samples_us (list[float]): per-sample latencies in microseconds; may be empty.

    Returns:
        dict[str, float]: keys `median_us`, `p95_us`, `p99_us`. All zero when the input is empty.
    """
    if not samples_us:
        return {"median_us": 0.0, "p95_us": 0.0, "p99_us": 0.0}
    _sorted = sorted(samples_us)
    _n = len(_sorted)
    _ans: dict[str, float] = {
        "median_us": _sorted[_n // 2],
        "p95_us": _sorted[min(int(_n * 0.95), _n - 1)],
        "p99_us": _sorted[min(int(_n * 0.99), _n - 1)],
    }
    return _ans


def probe_timer(*, samples_n: int = _DFLT_TIMER_SAMPLES) -> dict[str, Any]:
    """Sample consecutive `time.perf_counter_ns()` reads; return delta stats.

    Only counts deltas where the counter actually advanced (otherwise the resolution is below the inter-read overhead). On a coarse-clock platform many reads return the same value and only a handful of non-zero deltas land in the sample.

    Args:
        samples_n (int, optional): how many reads to attempt. Defaults to 1000.

    Returns:
        dict[str, Any]: keys `samples_n` (advances actually observed), `median_ns`, `min_ns`, `max_ns`. All zero when no advance was seen.
    """
    _samples: list[int] = []
    _last = time.perf_counter_ns()
    for _ in range(samples_n):
        _now = time.perf_counter_ns()
        if _now != _last:
            _samples.append(_now - _last)
            _last = _now
    if not _samples:
        _ans: dict[str, Any] = {"samples_n": 0, "median_ns": 0, "min_ns": 0, "max_ns": 0}
        return _ans
    _samples.sort()
    _n = len(_samples)
    _ans = {
        "samples_n": _n,
        "median_ns": _samples[_n // 2],
        "min_ns": _samples[0],
        "max_ns": _samples[-1],
    }
    return _ans


def probe_jitter(*,
                 samples_n: int = _DFLT_JITTER_SAMPLES,
                 target_us: int = _DFLT_JITTER_TARGET_US) -> dict[str, Any]:
    """Measure `asyncio.sleep` precision over N samples at a target microsecond duration.

    On Windows the call is wrapped in `windows_timer_resolution(1)` so the system clock floor drops from ~15 ms to ~1 ms for the duration of the probe. On POSIX the wrapper is a no-op.

    Args:
        samples_n (int, optional): how many sleeps to time. Defaults to 100.
        target_us (int, optional): per-sleep target in microseconds. Defaults to 1000 (1 ms).

    Returns:
        dict[str, Any]: keys `samples_n`, `target_us`, `median_us`, `p95_us`, `p99_us`.
    """
    with windows_timer_resolution(1):
        _ans = run_async_safe(lambda: _probe_jitter_async(samples_n, target_us))
    return _ans


async def _probe_jitter_async(samples_n: int, target_us: int) -> dict[str, Any]:
    """Async body of `probe_jitter`: do the sleeps, time each one, return stats.

    Args:
        samples_n (int): how many sleeps to time.
        target_us (int): per-sleep target in microseconds.

    Returns:
        dict[str, Any]: same shape as `probe_jitter`'s return.
    """
    _target_s = target_us / 1_000_000.0
    _actuals: list[float] = []
    for _ in range(samples_n):
        _t0 = time.perf_counter()
        await asyncio.sleep(_target_s)
        _actuals.append((time.perf_counter() - _t0) * 1_000_000.0)
    _ans: dict[str, Any] = {"samples_n": len(_actuals), "target_us": target_us}
    _ans.update(_stats_us(_actuals))
    return _ans


def probe_loopback(*,
                   samples_n: int = _DFLT_LOOPBACK_SAMPLES,
                   payload_bytes: int = _DFLT_LOOPBACK_PAYLOAD) -> dict[str, Any]:
    """Measure TCP loopback round-trip on a 127.0.0.1 socket pair.

    Stands up a tiny echo server in a daemon thread on a kernel-assigned port, connects a client, sends N requests, records each round-trip. `TCP_NODELAY` is set so Nagle's algorithm does not skew the per-sample timing.

    Args:
        samples_n (int, optional): how many round-trips to time. Defaults to 100.
        payload_bytes (int, optional): bytes per request. Defaults to 64.

    Returns:
        dict[str, Any]: keys `samples_n`, `payload_bytes`, `median_us`, `p95_us`, `p99_us`.
    """
    _server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _server.bind(("127.0.0.1", 0))
    _server.listen(1)
    _port = _server.getsockname()[1]
    _conn_holder: list[socket.socket] = []
    _t = threading.Thread(target=_loopback_echo, args=(_server, payload_bytes, _conn_holder), daemon=True)
    _t.start()

    _client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _client.connect(("127.0.0.1", _port))
    _client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    _payload = b"x" * payload_bytes
    _samples_us: list[float] = []
    try:
        for _ in range(samples_n):
            _t0 = time.perf_counter()
            _client.send(_payload)
            _ = _client.recv(payload_bytes)
            _samples_us.append((time.perf_counter() - _t0) * 1_000_000.0)
    finally:
        _client.close()
        if _conn_holder:
            _conn_holder[0].close()
        _server.close()
        _t.join(timeout=1.0)

    _ans: dict[str, Any] = {"samples_n": len(_samples_us), "payload_bytes": payload_bytes}
    _ans.update(_stats_us(_samples_us))
    return _ans


def _loopback_echo(server: socket.socket,
                   payload_bytes: int,
                   conn_holder: list[socket.socket]) -> None:
    """Daemon-thread body for the loopback probe: accept once, echo until the client closes.

    Args:
        server (socket.socket): listening socket; the thread accepts exactly one connection.
        payload_bytes (int): per-recv buffer size.
        conn_holder (list[socket.socket]): single-element list the caller pre-allocates; slot 0 receives the accepted connection so the caller can close it on shutdown.
    """
    try:
        _conn, _ = server.accept()
    except OSError:
        return
    conn_holder.append(_conn)
    try:
        while True:
            _data = _conn.recv(payload_bytes)
            if not _data:
                break
            _conn.send(_data)
    except OSError:
        pass


def probe_handler_scaling(*,
                          concurs: list[int] | None = None,
                          samples_per_c: int = _DFLT_SCALING_SAMPLES_PER_C) -> dict[str, Any]:
    """Measure no-op async-handler latency at increasing concurrency levels.

    For each concurrency `c`, runs `samples_per_c` waves of `c` parallel coroutines (each does one `await asyncio.sleep(0)` yield) and records every coroutine's wall-clock time. Reveals event-loop saturation: ideal scaling is flat latency vs `c`; real scaling shows a knee.

    Args:
        concurs (list[int] | None, optional): concurrency levels to sweep. Defaults to None, which uses `(1, 2, 4, 8, 16)`.
        samples_per_c (int, optional): waves per concurrency level. Defaults to 10.

    Returns:
        dict[str, Any]: keys `concurs` (list of `c` values used) and `stats` (dict mapping `str(c)` -> `{samples_n, median_us, p95_us, p99_us}`).
    """
    if concurs is None:
        _cs = list(_DFLT_SCALING_CONCURS)
    else:
        _cs = list(concurs)
    with windows_timer_resolution(1):
        _ans = run_async_safe(lambda: _probe_handler_scaling_async(_cs, samples_per_c))
    return _ans


async def _probe_handler_scaling_async(concurs: list[int],
                                       samples_per_c: int) -> dict[str, Any]:
    """Async body of `probe_handler_scaling`: drive each concurrency level, collect per-coroutine latencies.

    Args:
        concurs (list[int]): concurrency levels to sweep.
        samples_per_c (int): waves per concurrency level.

    Returns:
        dict[str, Any]: same shape as `probe_handler_scaling`'s return.
    """
    _stats: dict[str, dict[str, float]] = {}
    for _c in concurs:
        _all: list[float] = []
        for _ in range(samples_per_c):
            _tasks = [asyncio.create_task(_noop_handler()) for _ in range(_c)]
            _wave = await asyncio.gather(*_tasks)
            _all.extend(_wave)
        _block: dict[str, float] = {"samples_n": float(len(_all))}
        _block.update(_stats_us(_all))
        _stats[str(_c)] = _block
    _ans: dict[str, Any] = {"concurs": list(concurs), "stats": _stats}
    return _ans


async def _noop_handler() -> float:
    """No-op async handler: yield once via `asyncio.sleep(0)`, return wall-clock elapsed in microseconds.

    Returns:
        float: handler-side elapsed time in microseconds.
    """
    _t0 = time.perf_counter()
    await asyncio.sleep(0)
    return (time.perf_counter() - _t0) * 1_000_000.0


__all__ = [
    "probe_handler_scaling",
    "probe_jitter",
    "probe_loopback",
    "probe_timer",
]
