"""Host-floor probes that characterise how quiet the host is before any experiment runs.

Four probes, each filling the matching envelope block:

- `probe_timer`: clock floor (deltas between consecutive `time.perf_counter_ns()` reads).
- `probe_jitter`: scheduler floor (overshoot of `asyncio.sleep` against a target).
- `probe_loopback`: kernel TCP floor (round-trip on a 127.0.0.1 socket pair).
- `probe_handler_scaling`: event-loop saturation knee (latency of a no-op handler at increasing concurrency).

STATISTICS. Each probe reports min, max, mean, std, median, p95, and p99 over its samples. The median is the headline summary because latency distributions skew long-tailed; p95 and p99 capture the typical and the slow-but-not-catastrophic tail. Min / max are useful on clock-tick samples where the spread itself is the signal.

Module-level `_DFLT_*` constants are runtime fallbacks for the matching `data/config/method/prototype/calibration.json` keys.
"""

from __future__ import annotations

import asyncio
import socket
import statistics
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
_DFLT_LOOPBACK_PAYLOAD = 32 * 1024
_DFLT_SCALING_START = 1
_DFLT_SCALING_STOP = 1024
_DFLT_SCALING_STEP = 10
_DFLT_SCALING_SAMPLES_PER_C = 10
_DFLT_SCALING_MAX_DRIFT_PCT = 5.0


def _stats_us(samples_us: list[float]) -> dict[str, float]:
    """Compute min / max / mean / std-dev / median / p95 / p99 over microsecond samples.

    Args:
        samples_us (list[float]): per-sample latencies in microseconds; may be empty.

    Returns:
        dict[str, float]: keys `min_us`, `max_us`, `mean_us`, `std_us`, `median_us`, `p95_us`, `p99_us`. All zero when the input is empty.
    """
    _ans: dict[str, float] = {
        "min_us": 0.0,
        "max_us": 0.0,
        "mean_us": 0.0,
        "std_us": 0.0,
        "median_us": 0.0,
        "p95_us": 0.0,
        "p99_us": 0.0,
    }
    if samples_us:
        _sorted = sorted(samples_us)
        _n = len(_sorted)
        if _n > 1:
            _std = statistics.pstdev(_sorted)
        else:
            _std = 0.0
        _ans["min_us"] = _sorted[0]
        _ans["max_us"] = _sorted[-1]
        _ans["mean_us"] = statistics.mean(_sorted)
        _ans["std_us"] = _std
        _ans["median_us"] = _sorted[_n // 2]
        _ans["p95_us"] = _sorted[min(int(_n * 0.95), _n - 1)]
        _ans["p99_us"] = _sorted[min(int(_n * 0.99), _n - 1)]
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
    _ans: dict[str, Any] = {
        "samples_n": 0,
        "median_ns": 0,
        "mean_ns": 0.0,
        "std_ns": 0.0,
        "min_ns": 0,
        "max_ns": 0,
    }
    if _samples:
        _samples.sort()
        _n = len(_samples)
        if _n > 1:
            _std_ns = statistics.pstdev(_samples)
        else:
            _std_ns = 0.0
        _ans["samples_n"] = _n
        _ans["median_ns"] = _samples[_n // 2]
        _ans["mean_ns"] = statistics.mean(_samples)
        _ans["std_ns"] = _std_ns
        _ans["min_ns"] = _samples[0]
        _ans["max_ns"] = _samples[-1]
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
        payload_bytes (int, optional): bytes per request. Defaults to 32 KiB.

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
            _client.sendall(_payload)
            _recv_exact(_client, payload_bytes)
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
            _data = _recv_exact(_conn, payload_bytes)
            if _data is None:
                break
            _conn.sendall(_data)
    except OSError:
        pass


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly `n` bytes from `sock`, looping over `recv` until the buffer is full.

    TCP is a byte stream; a single `recv(n)` may return fewer bytes than requested. At kB-scale payloads the response routinely spans multiple kernel reads, so the probe must accumulate.

    Args:
        sock (socket.socket): connected socket.
        n (int): exact byte count to read.

    Returns:
        bytes | None: the `n` bytes when the read completes; `None` when the peer closes before `n` bytes arrive.
    """
    _ans: bytes | None = None
    _buf = bytearray()
    _closed = False
    while len(_buf) < n and not _closed:
        _chunk = sock.recv(n - len(_buf))
        if not _chunk:
            _closed = True
        else:
            _buf.extend(_chunk)
    if not _closed:
        _ans = bytes(_buf)
    return _ans


def probe_handler_scaling(*,
                          start: int = _DFLT_SCALING_START,
                          stop: int = _DFLT_SCALING_STOP,
                          step: int = _DFLT_SCALING_STEP,
                          samples_per_c: int = _DFLT_SCALING_SAMPLES_PER_C,
                          max_drift_pct: float = _DFLT_SCALING_MAX_DRIFT_PCT) -> dict[str, Any]:
    """Walk concurrency from `start` to `stop`, stopping at the first level whose median drifts beyond `max_drift_pct`.

    Args:
        start (int, optional): first concurrency. Defaults to 1.
        stop (int, optional): inclusive upper bound. Defaults to 1024.
        step (int, optional): additive increment (`c <- c + step`). Defaults to 10.
        samples_per_c (int, optional): waves per concurrency level. Defaults to 10.
        max_drift_pct (float, optional): stop tolerance against `start`'s median. Defaults to 5.0.

    Returns:
        dict[str, Any]: keys `concurs` (list of `c` values walked) and `stats` (dict mapping `str(c)` to its sample stats).
    """
    with windows_timer_resolution(1):
        _ans = run_async_safe(lambda: _probe_handler_scaling_async(
            start, stop, step, samples_per_c, max_drift_pct))
    return _ans


async def _probe_handler_scaling_async(start: int,
                                       stop: int,
                                       step: int,
                                       samples_per_c: int,
                                       max_drift_pct: float) -> dict[str, Any]:
    """Async body of `probe_handler_scaling`; sentinel-driven loop, single return."""
    _cs: list[int] = []
    _stats: dict[str, dict[str, float]] = {}
    _base: float | None = None
    _drifted = False
    _c = start
    while _c <= stop and not _drifted:
        _all: list[float] = []
        for _ in range(samples_per_c):
            _tasks = [asyncio.create_task(_noop_handler()) for _ in range(_c)]
            _wave = await asyncio.gather(*_tasks)
            _all.extend(_wave)
        _block: dict[str, float] = {"samples_n": float(len(_all))}
        _block.update(_stats_us(_all))
        _stats[str(_c)] = _block
        _cs.append(_c)
        _med = _block.get("median_us", 0.0)
        if _base is None:
            _base = _med
        elif _base > 0:
            _drift = abs((_med - _base) / _base * 100.0)
            if _drift > max_drift_pct:
                _drifted = True
        _c += step
    _ans: dict[str, Any] = {"concurs": _cs, "stats": _stats}
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
