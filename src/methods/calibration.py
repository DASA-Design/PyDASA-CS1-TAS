# -*- coding: utf-8 -*-
"""
Module methods/calibration.py
=============================

Per-host noise-floor characterisation method; sibling to `src.methods.analytic` / `stochastic` / `dimensional` / `experiment`, but its subject is the **host**, not the TAS architecture. Runs four baselines (timer resolution, scheduling jitter, loopback latency, empty-handler scaling over `n_con_usr`) and writes a single JSON envelope to `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`.

Every `experiment` run should reference the latest calibration JSON by timestamp in its run envelope (`baseline_ref`) so measured latencies can be reported as `value - loopback_median +/- jitter_p99`.

Kept deliberately small and dependency-light:

    - ctypes `timeBeginPeriod(1)` is inlined so this module stays free of heavy transitive imports that would warm the executor pool and perturb the measurements.
    - `time.perf_counter_ns()` throughout; integer arithmetic in the hot path, seconds only at JSON-write time.
    - FastAPI `/ping` runs in a background uvicorn thread so the loopback probe measures real TCP loopback, not ASGI in-process shortcuts.

Run::

    python -m src.methods.calibration
    python -m src.methods.calibration --timer-samples 50000 --jitter-samples 2000
    python -m src.methods.calibration --loopback-samples 2000 --n-con-usr 1,10,50,100
    python -m src.methods.calibration --skip-loopback  # timer + jitter only

Output JSON shape (truncated)::

    {
        "host_profile": {"hostname": "...", "os": "...", "cpu_count": 8, ...},
        "timer":   {"min_ns": 100, "median_ns": 100.0, "mean_ns": 112.4, "std_ns": 18.3},
        "jitter":  {"mean_us": 480.1, "p99_us": 1250.2, "max_us": 2104.5, "std_us": 230.6},
        "loopback":{"min_us": 180.0, "median_us": 240.0, "p95_us": 410.0, "p99_us": 640.0, "std_us": 95.1},
        "handler_scaling": {"1": {...}, "10": {...}, "50": {...}, "100": {...}},
        "timestamp": "2026-04-23T19:42:11",
        "elapsed_s": 42.7
    }
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import contextlib
import gc
import json
import os
import platform
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# scientific stack
import numpy as np

# bring the repo root onto sys.path so ad-hoc script runs import cleanly
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

# HTTP + server stack: imported after the sys.path tweak so a fresh clone works
import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

_CALIB_DIR = _ROOT / "data" / "results" / "experiment" / "calibration"


# tunables from `data/config/method/calibration.json` (read once at import; fallbacks apply only when unreadable)
def _load_cfg() -> Dict[str, Any]:
    """*_load_cfg()* read calibration defaults from the method-config JSON.

    Returns:
        dict: the parsed JSON contents, or an empty dict when the file is absent.
    """
    try:
        from src.io.config import load_method_cfg
        return load_method_cfg("calibration")
    except (FileNotFoundError, ImportError):
        return {}


_CALIB_CFG: Dict[str, Any] = _load_cfg()

_DEFAULT_TIMER_SAMPLES = int(_CALIB_CFG.get("timer_samples", 0))
_DEFAULT_JITTER_SAMPLES = int(_CALIB_CFG.get("jitter_samples", 0))
_DEFAULT_LOOPBACK_SAMPLES = int(_CALIB_CFG.get("loopback_samples", 0))
_DEFAULT_LOOPBACK_WARMUP = int(_CALIB_CFG.get("loopback_warmup", 0))
# client-side load ladder; each entry is an in-flight-request count against the c_srv=1 calibration service
_DEFAULT_N_CON_USR = tuple(_CALIB_CFG.get("n_con_usr", ()))
# total samples per level; per_worker = max(1, samples_per_level // n_usr) unless overridden
_DEFAULT_SAMPLES_PER_LEVEL = int(_CALIB_CFG.get("samples_per_level", 0))
_DEFAULT_PORT = int(_CALIB_CFG.get("port", 8765))
_DEFAULT_READY_TIMEOUT_S = float(_CALIB_CFG.get("ready_timeout_s", 5.0))
_DEFAULT_UVICORN_BACKLOG = int(_CALIB_CFG.get("uvicorn_backlog", 16384))
_DEFAULT_HTTPX_TIMEOUT_S = float(_CALIB_CFG.get("httpx_timeout_s", 0))
_DEFAULT_SKIP_JITTER = bool(_CALIB_CFG.get("skip_jitter", False))
_DEFAULT_SKIP_LOOPBACK = bool(_CALIB_CFG.get("skip_loopback", False))

# rate-sweep: opt-in (each trial is a full experiment.run); enable via config or --rate-sweep
_DEFAULT_SKIP_RATE_SWEEP = bool(_CALIB_CFG.get("skip_rate_sweep", True))
_RATE_SWEEP_CFG: Dict[str, Any] = _CALIB_CFG.get("rate_sweep", {})
_DEFAULT_RATE_SWEEP_ADAPTATION = str(
    _RATE_SWEEP_CFG.get("adaptation", "baseline"))
_DEFAULT_RATE_SWEEP_RATES: Tuple[float, ...] = tuple(
    float(_r) for _r in _RATE_SWEEP_CFG.get("rates", ()))
_DEFAULT_RATE_SWEEP_TRIALS = int(_RATE_SWEEP_CFG.get("trials_per_rate", 5))
_DEFAULT_RATE_SWEEP_MIN_SAMPLES = int(
    _RATE_SWEEP_CFG.get("min_samples_per_kind", 32))
_DEFAULT_RATE_SWEEP_PROBE_S = float(
    _RATE_SWEEP_CFG.get("max_probe_window_s", 4.0))
_DEFAULT_RATE_SWEEP_CASCADE_MODE = str(
    _RATE_SWEEP_CFG.get("cascade_mode", "rolling"))
_DEFAULT_RATE_SWEEP_CASCADE_THRESHOLD = float(
    _RATE_SWEEP_CFG.get("cascade_threshold", 0.10))
_DEFAULT_RATE_SWEEP_CASCADE_WINDOW = int(
    _RATE_SWEEP_CFG.get("cascade_window", 50))
_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT = float(
    _RATE_SWEEP_CFG.get("target_loss_pct", 2.0))
_DEFAULT_RATE_SWEEP_ENTRY_SERVICE = str(
    _RATE_SWEEP_CFG.get("entry_service", "TAS_{1}"))

# jitter-probe sleep target (ns); same unit as the hot path
_JITTER_TARGET_NS = int(_CALIB_CFG.get("jitter_target_ns", 1_000_000))

# auto-batch tick (s); mirrors ClientSimulator._probe_at_rate, duplicated to keep experiment import out of the rate sweep
_TARGET_TICK_S: float = 0.020


def _banner(msg: str) -> None:
    """*_banner()* print a centred header band."""
    print()
    print("=" * 78)
    print(f"  {msg}")
    print("=" * 78)


@contextlib.contextmanager
def _windows_timer_resolution(period_ms: int = 1):
    """*_windows_timer_resolution()* raise the Windows system-timer floor for the block.

    No-op on non-Windows. Inlined rather than imported from elsewhere so this module stays free of heavy transitive imports that would warm the executor pool and perturb the jitter / loopback measurements.

    Args:
        period_ms (int): requested timer floor in milliseconds; OS clamps to supported range.
    """
    if sys.platform != "win32":
        yield
        return
    try:
        import ctypes
        _winmm = ctypes.WinDLL("winmm")
    except (OSError, AttributeError):
        yield
        return
    _winmm.timeBeginPeriod(int(period_ms))
    try:
        yield
    finally:
        _winmm.timeEndPeriod(int(period_ms))


def snapshot_host_profile() -> Dict[str, Any]:
    """*snapshot_host_profile()* capture OS, CPU, RAM, python identity for the envelope.

    Uses only the Python standard library so the probe adds no third-party dependency and does not perturb the measurements that follow. Thermal readings are intentionally omitted; run-time conditions (thermals, background load) should be captured out-of-band by the caller.

    Returns:
        dict: hostname, os, cpu_count, python, timer resolution guesses.
    """
    _mem_gb: Optional[float] = None
    try:
        if sys.platform == "win32":
            import ctypes

            class _MEMSTAT(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint32),
                    ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64),
                    ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64),
                    ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64),
                    ("ullAvailVirtual", ctypes.c_uint64),
                    ("sullAvailExtendedVirtual", ctypes.c_uint64),
                ]

            _stat = _MEMSTAT()
            _stat.dwLength = ctypes.sizeof(_MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(_stat))
            _total_phys = float(_stat.ullTotalPhys)
            _mem_gb = _total_phys / (1024 ** 3)
    except Exception:
        _mem_gb = None

    _hostname = socket.gethostname()
    _os = platform.platform()
    _py_ver = platform.python_version()
    _py_impl = platform.python_implementation()
    _cpu_count = os.cpu_count()
    _cpu_machine = platform.machine()
    _cpu_processor = platform.processor()

    _profile = {
        "hostname": _hostname,
        "os": _os,
        "python": _py_ver,
        "python_impl": _py_impl,
        "cpu_count": _cpu_count,
        "cpu_machine": _cpu_machine,
        "cpu_processor": _cpu_processor,
        "ram_total_gb": _mem_gb,
    }
    return _profile


def measure_timer(samples: int) -> Dict[str, float]:
    """*measure_timer()* probe clock resolution via back-to-back `perf_counter_ns` reads.

    Skips zero-delta reads (same tick bucket) and summarises the positive deltas. The minimum tick is the actual clock resolution on this host.

    Args:
        samples (int): number of back-to-back reads to collect.

    Returns:
        dict: min_ns / median_ns / mean_ns / std_ns / zero_frac.
    """
    _deltas: List[int] = []
    _zero = 0
    for _ in range(int(samples)):
        _a = time.perf_counter_ns()
        _b = time.perf_counter_ns()
        _d = _b - _a
        if _d > 0:
            _deltas.append(_d)
        else:
            _zero += 1
    if not _deltas:
        return {"min_ns": 0, "median_ns": 0.0, "mean_ns": 0.0,
                "std_ns": 0.0, "zero_frac": 1.0}
    _arr = np.asarray(_deltas, dtype=np.int64)
    _min = int(_arr.min())
    _median = float(np.median(_arr))
    _mean = float(_arr.mean())
    _std = float(_arr.std())
    _zero_frac = float(_zero / samples)
    _result = {
        "min_ns": _min,
        "median_ns": _median,
        "mean_ns": _mean,
        "std_ns": _std,
        "zero_frac": _zero_frac,
    }
    return _result


def measure_jitter(samples: int) -> Dict[str, float]:
    """*measure_jitter()* scheduling-jitter probe via `time.sleep(0.001)`.

    Records the difference between requested 1 ms and the actual elapsed ns. `max_us` and `p99_us` are the OS-interruption tail any inter-arrival smaller than those values cannot resolve cleanly.

    Args:
        samples (int): number of sleep cycles to measure.

    Returns:
        dict: mean_us / std_us / p50_us / p99_us / max_us.
    """
    _jitters: List[int] = []
    for _ in range(int(samples)):
        _t1 = time.perf_counter_ns()
        time.sleep(0.001)
        _t2 = time.perf_counter_ns()
        _jitters.append((_t2 - _t1) - _JITTER_TARGET_NS)
    _arr = np.asarray(_jitters, dtype=np.int64)
    _us = _arr / 1000.0
    _mean = float(_us.mean())
    _std = float(_us.std())
    _p50 = float(np.percentile(_us, 50))
    _p99 = float(np.percentile(_us, 99))
    _max = float(_us.max())
    _result = {
        "mean_us": _mean,
        "std_us": _std,
        "p50_us": _p50,
        "p99_us": _p99,
        "max_us": _max,
    }
    return _result


def _build_ping_app() -> FastAPI:
    """*_build_ping_app()* minimal FastAPI app exposing `GET /ping`."""
    _app = FastAPI()

    @_app.get("/ping")
    async def _ping() -> Dict[str, bool]:
        return {"ok": True}

    return _app


class _UvicornThread(threading.Thread):
    """Daemon thread that runs a uvicorn server on `127.0.0.1:port`.

    Exposes `.wait_ready()` so the caller can block until the server's `/ping` endpoint answers, and `.shutdown()` to stop cleanly.

    Attributes:
        _server: Underlying `uvicorn.Server` instance.
        _port: TCP port the server is bound to.
    """

    def __init__(self, app: FastAPI, port: int,
                 backlog: int = _DEFAULT_UVICORN_BACKLOG) -> None:
        super().__init__(daemon=True)
        # large backlog so high n_con_usr levels aren't refused at the kernel socket queue
        _config = uvicorn.Config(app,
                                 host="127.0.0.1",
                                 port=int(port),
                                 log_level="error",
                                 access_log=False,
                                 backlog=int(backlog))
        self._server = uvicorn.Server(_config)
        self._port = int(port)

    def run(self) -> None:
        """*run()* thread entry point; blocks until `shutdown()` is called."""
        self._server.run()

    def wait_ready(self, timeout_s: float = 5.0) -> None:
        """*wait_ready()* poll `/ping` until it returns 200 or the timeout fires."""
        _start = time.perf_counter()
        _timeout = float(timeout_s)
        _deadline = _start + _timeout
        _url = f"http://127.0.0.1:{self._port}/ping"
        while True:
            _now = time.perf_counter()
            if _now >= _deadline:
                break
            try:
                _r = httpx.get(_url, timeout=0.5)
                if _r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.05)
            _msg = f"uvicorn did not become ready within {timeout_s} s"
        raise RuntimeError(_msg)

    def shutdown(self) -> None:
        """*shutdown()* tell uvicorn to exit; joins the thread."""
        self._server.should_exit = True
        self.join(timeout=5.0)


async def measure_loopback(port: int,
                           samples: int,
                           warmup: int) -> Dict[str, float]:
    """*measure_loopback()* round-trip latency of an empty `GET /ping`.

    Uses one `httpx.AsyncClient` with keep-alive so we measure steady-state loopback (TCP handshake excluded). All timings in `perf_counter_ns`.

    Args:
        port (int): port the ping server is listening on.
        samples (int): request count after warmup.
        warmup (int): discard-this-many requests before timing.

    Returns:
        dict: min_us / median_us / p95_us / p99_us / std_us / samples.
    """
    _url = "/ping"
    _base = f"http://127.0.0.1:{port}"
    _rtts: List[int] = []
    # serial loopback; cap the pool at 1 to avoid accidental concurrency
    _limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
    async with httpx.AsyncClient(base_url=_base, limits=_limits) as _client:
        for _ in range(int(warmup)):
            await _client.get(_url)
        for _ in range(int(samples)):
            _t1 = time.perf_counter_ns()
            await _client.get(_url)
            _t2 = time.perf_counter_ns()
            _rtts.append(_t2 - _t1)
    _arr = np.asarray(_rtts, dtype=np.int64)
    _us = _arr / 1000.0
    _min = float(_us.min())
    _median = float(np.median(_us))
    _p95 = float(np.percentile(_us, 95))
    _p99 = float(np.percentile(_us, 99))
    _std = float(_us.std())
    _n = int(samples)
    _result = {
        "min_us": _min,
        "median_us": _median,
        "p95_us": _p95,
        "p99_us": _p99,
        "std_us": _std,
        "samples": _n,
    }
    return _result


async def _run_concurrent_worker(client: httpx.AsyncClient,
                                 url: str,
                                 n: int) -> List[int]:
    """*_run_concurrent_worker()* one task: issue `n` sequential GETs, return RTT ns list."""
    _out: List[int] = []
    for _ in range(int(n)):
        _t1 = time.perf_counter_ns()
        await client.get(url)
        _t2 = time.perf_counter_ns()
        _out.append(_t2 - _t1)
    return _out


async def measure_handler_scaling(port: int,
                                  n_con_usr: Tuple[int, ...],
                                  warmup: int,
                                  per_worker: Optional[int] = None,
                                  samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
                                  on_level_start: Optional[Any] = None,
                                  on_level_done: Optional[Any] = None) -> Dict[str, Dict[str, float]]:
    """*measure_handler_scaling()* loopback latency at increasing concurrent-user load levels.

    For each `n_con_usr` (concurrent in-flight requests from the calibration client) in the ladder, launches `n_con_usr` concurrent workers each doing a derived number of sequential requests against the single-worker (`c_srv=1`) calibration service, aggregates the latency distribution. Quantifies how the FastAPI / event-loop stack's response time grows as in-flight user requests stack up on an empty handler.

    `n_con_usr` is the CLIENT-side concurrency knob; the SERVICE-side parallelism `c_srv` stays fixed at 1 (one uvicorn worker, one handler). The two must not be conflated.

    When `per_worker` is not supplied, each level targets `samples_per_level` total samples and sets `per_worker = max(1, samples_per_level // n_usr)`. This keeps per-level wall time bounded even at `n_usr = 10_000`, where a naive fixed `per_worker=200` would issue 2 million requests for one level.

    Args:
        port (int): port the ping server is listening on.
        n_con_usr (tuple[int, ...]): concurrent-user load levels to test (e.g. 1, 10, 50, 100).
        warmup (int): discard-this-many requests (total, not per-worker) upfront.
        per_worker (Optional[int]): sequential requests per concurrent worker. When `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived; ignored when `per_worker` is given explicitly.
        on_level_start (Optional[callable]): invoked with `(n_con_usr, total_samples)` before each level starts.
        on_level_done (Optional[callable]): invoked with `(n_con_usr, stats_dict, elapsed_s)` after each level finishes.

    Returns:
        dict[str, dict]: `{"<n_con_usr>": {min_us, median_us, p95_us, p99_us, std_us, samples}}`.
    """
    _url = "/ping"
    _base = f"http://127.0.0.1:{port}"
    _result: Dict[str, Dict[str, float]] = {}
    # lift httpx pool cap (default 100) to the max ladder level
    _max_n_con = 1
    for _n_con_peek in n_con_usr:
        if int(_n_con_peek) > _max_n_con:
            _max_n_con = int(_n_con_peek)
    _limits = httpx.Limits(max_connections=_max_n_con,
                           max_keepalive_connections=_max_n_con)
    # high timeout; at n_con_usr>=5000 the kernel connect queue drains in seconds
    _timeout = httpx.Timeout(_DEFAULT_HTTPX_TIMEOUT_S)
    async with httpx.AsyncClient(base_url=_base,
                                 limits=_limits,
                                 timeout=_timeout) as _client:
        for _ in range(int(warmup)):
            await _client.get(_url)
        for _n_con in n_con_usr:
            _count = int(_n_con)
            if per_worker is not None:
                _reqs = int(per_worker)
            else:
                _reqs = max(1, int(samples_per_level) // _count)
            _total = _count * _reqs
            if on_level_start is not None:
                on_level_start(_count, _total)
            _t0 = time.perf_counter()
            _tasks: List[Any] = []
            for _ in range(_count):
                _tasks.append(_run_concurrent_worker(_client, _url, _reqs))
            _lists = await asyncio.gather(*_tasks)
            _all: List[int] = []
            for _lst in _lists:
                _all.extend(_lst)
            _arr = np.asarray(_all, dtype=np.int64)
            # trim to samples_per_level so every level is comparable.
            if per_worker is None:
                _cap = int(samples_per_level)
                if _arr.size > _cap:
                    _arr = _arr[:_cap]
            _us = _arr / 1000.0
            _min = float(_us.min())
            _median = float(np.median(_us))
            _p95 = float(np.percentile(_us, 95))
            _p99 = float(np.percentile(_us, 99))
            _std = float(_us.std())
            _n = int(_us.size)
            _key = str(_count)
            _stats = {
                "min_us": _min,
                "median_us": _median,
                "p95_us": _p95,
                "p99_us": _p99,
                "std_us": _std,
                "samples": _n,
            }
            _result[_key] = _stats
            if on_level_done is not None:
                _elapsed = time.perf_counter() - _t0
                on_level_done(_count, _stats, _elapsed)
            # release per-level buffers before the next level allocates
            del _all, _arr, _us, _tasks, _lists
            gc.collect()
    return _result


def _run_probes_in_dedicated_loop(**kwargs: Any) -> Dict[str, Any]:
    """*_run_probes_in_dedicated_loop()* drive `_run_async_probes` on a fresh thread with its own event loop.

    Jupyter (and any ipykernel-based host) installs `SelectorEventLoop` on Windows for tornado compatibility; `select()` on Windows caps at 512 file descriptors, which breaks the high-load scaling probe (`n_con_usr >= 1000` needs thousands of sockets). A fresh thread running `ProactorEventLoop` on Windows (IOCP) has no such cap.

    On non-Windows platforms this still isolates the probes from any ambient loop and behaves identically.

    Args:
        **kwargs: forwarded verbatim to `_run_async_probes`.

    Returns:
        dict: the probes' result envelope.

    Raises:
        Exception: re-raises any exception that fired inside the worker thread.
    """
    _result_box: List[Any] = [None]
    _error_box: List[Optional[BaseException]] = [None]

    def _worker() -> None:
        try:
            if sys.platform == "win32":
                _loop = asyncio.ProactorEventLoop()
            else:
                _loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(_loop)
                _result_box[0] = _loop.run_until_complete(
                    _run_async_probes(**kwargs))
            finally:
                _loop.close()
        except BaseException as _exc:
            _error_box[0] = _exc

    _t = threading.Thread(target=_worker, daemon=False)
    _t.start()
    _t.join()
    _err = _error_box[0]
    if _err is not None:
        raise _err
    _out = _result_box[0]
    # drop thread-owned sockets / coroutine state before returning
    _result_box.clear()
    _error_box.clear()
    gc.collect()
    return _out


def _print_phase_marker(name: str) -> None:
    """*_print_phase_marker()* emit the `[3/4]` / `[4/4]` line when a phase begins."""
    if name == "loopback":
        print("  [3/4] loopback latency ...", flush=True)
    elif name == "handler_scaling":
        print("  [4/4] empty-handler scaling ...", flush=True)


def _print_level_start(level: int, total: int) -> None:
    """*_print_level_start()* emit the one-line "running N requests" marker at a scaling level."""
    print(f"      c={level:>6}  running {total} requests ...", flush=True)


def _print_level_done(level: int,
                      stats: Dict[str, float],
                      elapsed: float) -> None:
    """*_print_level_done()* emit the one-line "done in Xs" marker with the level's headline stats."""
    _med = stats.get("median_us", 0.0)
    _p99 = stats.get("p99_us", 0.0)
    print(f"      c={level:>6}  done in {elapsed:.1f}s  "
          f"median={_med:.1f}us  p99={_p99:.1f}us",
          flush=True)


def _parse_n_con_usr(arg: str) -> Tuple[int, ...]:
    """*_parse_n_con_usr()* parse a comma-separated `n_con_usr` ladder.

    Args:
        arg (str): comma-separated concurrent-user load levels, e.g. `"1,10,50,100"`.

    Returns:
        tuple[int, ...]: parsed levels; empty fragments are dropped.
    """
    _out: List[int] = []
    for _raw in arg.split(","):
        _token = _raw.strip()
        if not _token:
            continue
        _out.append(int(_token))
    return tuple(_out)


def _parse_rates(arg: str) -> Tuple[float, ...]:
    """*_parse_rates()* parse a comma-separated target-rate list.

    Args:
        arg (str): comma-separated rates in req/s, e.g. `"100,200,345"`.

    Returns:
        tuple[float, ...]: parsed rates; empty fragments are dropped.
    """
    _out: List[float] = []
    for _raw in arg.split(","):
        _token = _raw.strip()
        if not _token:
            continue
        _out.append(float(_token))
    return tuple(_out)


def _batch_size_for(rate: float) -> int:
    """*_batch_size_for()* mirror the auto-batch derivation in `ClientSimulator._probe_at_rate`.

    Reports the expected K at each target rate in the rate-sweep banner so the operator can correlate any loss with batch behaviour.

    Args:
        rate (float): target rate in req/s.

    Returns:
        int: K = round(TARGET_TICK_S / interarrival), clamped to >= 1.
    """
    if rate <= 0:
        return 1
    _interarrival = 1.0 / rate
    _k = int(round(_TARGET_TICK_S / _interarrival))
    return max(1, _k)


def _read_lambda_z_at(adaptation: str,
                      entry_service: str = "TAS_{1}") -> float:
    """*_read_lambda_z_at()* read the seeded external arrival rate at `entry_service`.

    Lazy-imports `src.io.load_profile` so `calibration.py` stays light at module-load time; the import cost is paid once on the first rate-sweep call.

    Args:
        adaptation (str): adaptation stem (`baseline` / `s1` / `s2` / `aggregate`).
        entry_service (str): artifact key to read from.

    Returns:
        float: seeded lambda_z at `entry_service`, or 0.0 when the key is absent.

    Raises:
        KeyError: when `entry_service` is not present in the profile.
    """
    from src.io import load_profile
    _cfg = load_profile(adaptation=adaptation)
    for _a in _cfg.artifacts:
        if _a.key == entry_service:
            return float(_a.lambda_z)
    raise KeyError(
        f"entry artifact {entry_service!r} not in adaptation {adaptation!r}")


def _run_single_rate_probe(rate: float,
                           adaptation: str,
                           min_samples: int,
                           max_probe_s: float,
                           cascade_mode: str,
                           cascade_threshold: float,
                           cascade_window: int) -> Dict[str, Any]:
    """*_run_single_rate_probe()* one trial at `rate` against `adaptation`.

    Lazy-imports `src.methods.experiment.run` + `src.io.load_method_cfg` so the rate-sweep path only pays the experiment-module import cost when the operator opts in; the module-top import surface stays light.

    `skip_calibration=True` is forced on the inner call so the sweep does not recurse through its own calibration gate; `verbose=False` suppresses the gate's warning so per-trial output stays readable.

    Args:
        rate (float): single target rate (req/s).
        adaptation (str): adaptation stem.
        min_samples (int): `min_samples_per_kind` per probe (>= 32 for CLT).
        max_probe_s (float): probe wall-clock cap in seconds.
        cascade_mode (str): cascade detector mode (e.g. `"rolling"`).
        cascade_threshold (float): cascade threshold (fraction).
        cascade_window (int): cascade detector window size.

    Returns:
        dict: result envelope from `experiment.run`.
    """
    from src.io import load_method_cfg
    from src.methods.experiment import run as _experiment_run
    _mcfg = load_method_cfg("experiment")
    _mcfg["ramp"] = {
        "min_samples_per_kind": int(min_samples),
        "max_probe_window_s": float(max_probe_s),
        "rates": [float(rate)],
        "cascade": {"mode": str(cascade_mode),
                    "threshold": float(cascade_threshold),
                    "window": int(cascade_window)},
    }
    return _experiment_run(
        adp=adaptation,
        wrt=False,
        method_cfg=_mcfg,
        skip_calibration=True,
        verbose=False,
    )


def _summarise_rate_trial(rate: float,
                          result: Dict[str, Any],
                          entry_service: str) -> Dict[str, float]:
    """*_summarise_rate_trial()* extract headline rate metrics from one experiment run envelope.

    Args:
        rate (float): target rate driven in this trial.
        result (dict): `experiment.run` envelope (contains `client_effective_rate` + `nodes`).
        entry_service (str): artifact key whose operational `lambda` we want (typically `TAS_{1}`).

    Returns:
        dict: target / effective / entry_lambda / gap / loss_pct.
    """
    _eff = float(result.get("client_effective_rate", 0.0))
    _nds = result["nodes"]
    _row = _nds.loc[_nds["key"] == entry_service]
    if _row.empty:
        _entry_lam = 0.0
    else:
        _entry_lam = float(_row.iloc[0]["lambda"])
    _target = float(rate)
    _gap = _target - _eff
    if rate > 0:
        _loss = _gap / rate * 100.0
    else:
        _loss = 0.0
    _summary = {
        "target": _target,
        "effective": _eff,
        "entry_lambda": _entry_lam,
        "gap": _gap,
        "loss_pct": _loss,
    }
    return _summary


def _aggregate_rate_trials(trials: List[Dict[str, float]]
                           ) -> Dict[str, float]:
    """*_aggregate_rate_trials()* summarise N per-trial records at one target rate.

    Args:
        trials (List[Dict]): per-trial summaries from `_summarise_rate_trial`.

    Returns:
        dict: target / mean / lo / hi / mean_loss_pct / mean_entry_lambda / n.
    """
    _effs: List[float] = []
    _lams: List[float] = []
    for _t in trials:
        _effs.append(float(_t["effective"]))
        _lams.append(float(_t["entry_lambda"]))
    _n = len(_effs)
    if _n == 0:
        _empty = {"target": 0.0, "mean": 0.0, "lo": 0.0, "hi": 0.0,
                  "mean_loss_pct": 0.0, "mean_entry_lambda": 0.0, "n": 0}
        return _empty
    _mean = sum(_effs) / _n
    _lo = min(_effs)
    _hi = max(_effs)
    _mean_lam = sum(_lams) / _n
    _target = float(trials[0]["target"])
    if _target > 0:
        _mean_loss = (_target - _mean) / _target * 100.0
    else:
        _mean_loss = 0.0
    _agg = {
        "target": _target,
        "mean": _mean,
        "lo": _lo,
        "hi": _hi,
        "mean_loss_pct": _mean_loss,
        "mean_entry_lambda": _mean_lam,
        "n": _n,
    }
    return _agg


def _print_rate_header(rate: float) -> None:
    """*_print_rate_header()* one-line banner per rate (target, interarrival, K)."""
    _interarrival_ms = 1000.0 / rate
    _k = _batch_size_for(rate)
    print(f"--- target rate {rate:>6.1f} req/s  "
          f"(interarrival {_interarrival_ms:.2f} ms, K={_k}) ---",
          flush=True)


def _print_rate_trial_row(trial_idx: int,
                          summary: Dict[str, float]) -> None:
    """*_print_rate_trial_row()* one-line per-trial output."""
    _eff = summary["effective"]
    _lam = summary["entry_lambda"]
    _gap = summary["gap"]
    _loss = summary["loss_pct"]
    print(f"  trial{trial_idx}: effective={_eff:>7.2f}  "
          f"entry.lambda={_lam:>7.2f}  "
          f"gap={_gap:>+7.2f}  loss={_loss:>+6.2f}%",
          flush=True)


def _print_rate_aggregate(agg: Dict[str, float]) -> None:
    """*_print_rate_aggregate()* one-line aggregate across all trials at a rate."""
    _mean = agg["mean"]
    _lo = agg["lo"]
    _hi = agg["hi"]
    _loss = agg["mean_loss_pct"]
    print(f"  >>> mean={_mean:>7.2f}  "
          f"range=[{_lo:>6.2f}, {_hi:>6.2f}]  "
          f"mean_loss={_loss:>+6.2f}%",
          flush=True)


def _find_highest_sustainable_rate(aggregates: Dict[float, Dict[str, float]],
                                   threshold_pct: float
                                   ) -> Optional[float]:
    """*_find_highest_sustainable_rate()* highest rate whose mean_loss_pct is at or below `threshold_pct`.

    Walks the aggregates in ascending rate order; returns the last rate that cleared the bar. Returns `None` when no rate cleared the bar.

    Args:
        aggregates (Dict[float, Dict]): per-rate aggregate from `_aggregate_rate_trials`.
        threshold_pct (float): maximum allowed mean loss in percent.

    Returns:
        Optional[float]: the highest passing rate, or `None`.
    """
    _sorted = sorted(aggregates.items(), key=lambda _kv: _kv[0])
    _best: Optional[float] = None
    for _rate, _agg in _sorted:
        _loss = abs(float(_agg.get("mean_loss_pct", 0.0)))
        if _loss <= threshold_pct:
            _best = _rate
    return _best


def run_rate_sweep(*,
                   rates: Tuple[float, ...] = _DEFAULT_RATE_SWEEP_RATES,
                   adaptation: str = _DEFAULT_RATE_SWEEP_ADAPTATION,
                   trials_per_rate: int = _DEFAULT_RATE_SWEEP_TRIALS,
                   min_samples: int = _DEFAULT_RATE_SWEEP_MIN_SAMPLES,
                   max_probe_s: float = _DEFAULT_RATE_SWEEP_PROBE_S,
                   cascade_mode: str = _DEFAULT_RATE_SWEEP_CASCADE_MODE,
                   cascade_threshold: float = _DEFAULT_RATE_SWEEP_CASCADE_THRESHOLD,
                   cascade_window: int = _DEFAULT_RATE_SWEEP_CASCADE_WINDOW,
                   target_loss_pct: float = _DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                   entry_service: str = _DEFAULT_RATE_SWEEP_ENTRY_SERVICE,
                   with_lambda_z: bool = False,
                   calibrate: bool = False,
                   verbose: bool = True) -> Dict[str, Any]:
    """*run_rate_sweep()* drive the experiment mesh at N target rates, `trials_per_rate` trials each.

    Each trial is a full `experiment.run(adp=...)` call with an inline ramp config built from the arguments; the experiment's calibration gate is bypassed (`skip_calibration=True`) so the sweep never recurses through its own calibration loader. Results land under the calibration envelope's `rate_sweep` key so the run gate has both host-floor AND rate-saturation characterisation in one file.

    When `calibrate=True`, additionally reports the highest rate whose mean loss is at or below `target_loss_pct` across all trials; use this to pick a notebook ramp rate the prototype can sustain.

    When `with_lambda_z=True`, the sweep appends the seeded `lambda_z` at `entry_service` (e.g. `TAS_{1}`) to the rate list so the analytic operating point is included.

    Args:
        rates (tuple[float, ...]): target rates (req/s) to drive.
        adaptation (str): adaptation stem.
        trials_per_rate (int): trials per rate for aggregation.
        min_samples (int): per-probe `min_samples_per_kind`.
        max_probe_s (float): probe wall-clock cap (seconds).
        cascade_mode (str): cascade detector mode.
        cascade_threshold (float): cascade threshold (fraction).
        cascade_window (int): cascade detector window.
        target_loss_pct (float): pass bar for the `calibrate` result.
        entry_service (str): artifact key for seeded `lambda_z` + per-trial `entry_lambda`.
        with_lambda_z (bool): when True, inject the seeded `lambda_z` at `entry_service` into the rate list.
        calibrate (bool): when True, include the highest-sustainable-rate finding in the result.
        verbose (bool): when True, print per-trial + per-rate output; False stays silent.

    Returns:
        dict: `{adaptation, rates, trials_per_rate, aggregates, per_trial, target_loss_pct, calibrated_rate (if calibrate), lambda_z_at_entry (if with_lambda_z), started_at, elapsed_s}`.
    """
    _t0 = time.perf_counter()
    _rates_list: List[float] = []
    for _r in rates:
        _rates_list.append(float(_r))

    if with_lambda_z:
        _lz = _read_lambda_z_at(adaptation, entry_service)
        if _lz > 0.0 and _lz not in _rates_list:
            _rates_list.append(_lz)
        _rates_list = sorted(set(_rates_list))
    else:
        _lz = 0.0

    _aggregates: Dict[float, Dict[str, float]] = {}
    _per_trial: Dict[float, List[Dict[str, float]]] = {}

    for _rate in _rates_list:
        if verbose:
            print()
            _print_rate_header(_rate)
        _trials: List[Dict[str, float]] = []
        for _i in range(int(trials_per_rate)):
            _res = _run_single_rate_probe(
                rate=_rate,
                adaptation=adaptation,
                min_samples=min_samples,
                max_probe_s=max_probe_s,
                cascade_mode=cascade_mode,
                cascade_threshold=cascade_threshold,
                cascade_window=cascade_window,
            )
            _summary = _summarise_rate_trial(_rate, _res, entry_service)
            _trials.append(_summary)
            if verbose:
                _print_rate_trial_row(_i, _summary)
            # drop envelope before the next trial allocates
            del _res
            gc.collect()
        _agg = _aggregate_rate_trials(_trials)
        _aggregates[_rate] = _agg
        _per_trial[_rate] = _trials
        if verbose:
            _print_rate_aggregate(_agg)

    _t_end = time.perf_counter()
    _elapsed = round(_t_end - _t0, 3)

    _aggregates_json: Dict[str, Dict[str, float]] = {}
    for _rate_key, _agg_val in _aggregates.items():
        _aggregates_json[str(_rate_key)] = _agg_val
    _per_trial_json: Dict[str, List[Dict[str, float]]] = {}
    for _rate_key, _trials_val in _per_trial.items():
        _per_trial_json[str(_rate_key)] = _trials_val

    _cascade_block = {"mode": str(cascade_mode),
                      "threshold": float(cascade_threshold),
                      "window": int(cascade_window)}

    _ans: Dict[str, Any] = {
        "adaptation": str(adaptation),
        "rates": _rates_list,
        "trials_per_rate": int(trials_per_rate),
        "min_samples_per_kind": int(min_samples),
        "max_probe_window_s": float(max_probe_s),
        "cascade": _cascade_block,
        "entry_service": str(entry_service),
        "target_loss_pct": float(target_loss_pct),
        "aggregates": _aggregates_json,
        "per_trial": _per_trial_json,
        "elapsed_s": _elapsed,
    }
    if with_lambda_z:
        _ans["lambda_z_at_entry"] = float(_lz)
    if calibrate:
        _ans["calibrated_rate"] = _find_highest_sustainable_rate(
            _aggregates, float(target_loss_pct))

    return _ans


def _build_output_path(profile: Dict[str, Any], stamp: Optional[str] = None) -> Path:
    """*_build_output_path()* build the per-host calibration JSON path.

    Shape: `data/results/experiment/calibration/<hostname>_<YYYYMMDD_HHMMSS>.json`.

    Args:
        profile (dict): host profile (we use `hostname`).
        stamp (Optional[str]): override the timestamp suffix; default `now()`.
    """
    _raw_host = profile.get("hostname", "unknown")
    _host_str = str(_raw_host)
    _host = _host_str.replace(" ", "-")
    if stamp is None:
        _now = datetime.now()
        _stamp = _now.strftime("%Y%m%d_%H%M%S")
    else:
        _stamp = str(stamp)
    return _CALIB_DIR / f"{_host}_{_stamp}.json"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """*_write_json()* write `data` to `path`, creating parents, pretty-printed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as _fh:
        json.dump(data, _fh, indent=2, sort_keys=True)


def _print_summary(envelope: Dict[str, Any]) -> None:
    """*_print_summary()* compact post-run readout."""
    _banner("Calibration summary")

    _hp = envelope.get("host_profile", {})
    _host = _hp.get("hostname")
    _os = _hp.get("os")
    _py = _hp.get("python")
    _py_impl = _hp.get("python_impl")
    _cpu = _hp.get("cpu_count")
    _ram = _hp.get("ram_total_gb")
    print(f"  host         : {_host}  ({_os})")
    print(f"  python       : {_py} {_py_impl}  cpu={_cpu}  ram={_ram}")

    _t = envelope.get("timer", {})
    _t_min = _t.get("min_ns")
    _t_median = _t.get("median_ns")
    _t_std = _t.get("std_ns")
    print(f"  timer        : min={_t_min} ns  "
          f"median={_t_median:.1f} ns  "
          f"std={_t_std:.1f} ns")

    _j = envelope.get("jitter")
    if _j is not None:
        _j_mean = _j.get("mean_us")
        _j_p99 = _j.get("p99_us")
        _j_max = _j.get("max_us")
        print(f"  jitter       : mean={_j_mean:.1f} us  "
              f"p99={_j_p99:.1f} us  "
              f"max={_j_max:.1f} us")

    _l = envelope.get("loopback")
    if _l is not None:
        _l_min = _l.get("min_us")
        _l_median = _l.get("median_us")
        _l_p99 = _l.get("p99_us")
        print(f"  loopback     : min={_l_min:.1f} us  "
              f"median={_l_median:.1f} us  "
              f"p99={_l_p99:.1f} us")

    _h = envelope.get("handler_scaling")
    if _h:
        print("  handler scaling (median / p99 us):")
        for _c, _stats in _h.items():
            _s_median = _stats["median_us"]
            _s_p99 = _stats["p99_us"]
            _s_n = _stats["samples"]
            print(f"    c={_c:>4}  median={_s_median:.1f}  "
                  f"p99={_s_p99:.1f}  "
                  f"samples={_s_n}")

    _rs = envelope.get("rate_sweep")
    if _rs:
        _rs_adp = _rs.get("adaptation")
        _rs_rates = _rs.get("rates", [])
        _rs_trials = _rs.get("trials_per_rate")
        _rs_target = _rs.get("target_loss_pct")
        _rs_cal = _rs.get("calibrated_rate")
        print(f"  rate sweep   : adp={_rs_adp!r}  "
              f"rates={_rs_rates}  trials={_rs_trials}  "
              f"target_loss<={_rs_target}%")
        _aggs = _rs.get("aggregates", {})
        _sorted_keys = sorted(_aggs.keys(), key=lambda _k: float(_k))
        for _k in _sorted_keys:
            _a = _aggs[_k]
            _rate = float(_k)
            _mean = float(_a.get("mean", 0.0))
            _loss = float(_a.get("mean_loss_pct", 0.0))
            _lam = float(_a.get("mean_entry_lambda", 0.0))
            print(f"    rate={_rate:>6.1f}  effective_mean={_mean:>7.2f}  "
                  f"mean_loss={_loss:>+6.2f}%  "
                  f"entry.lambda={_lam:>7.2f}")
        if _rs_cal is not None:
            print(f"  highest sustainable rate (<= {_rs_target}% loss): "
                  f"{float(_rs_cal):.1f} req/s")
        else:
            print(f"  no rate cleared the {_rs_target}% loss bar")


async def _run_async_probes(*,
                            port: int,
                            loopback_samples: int,
                            loopback_warmup: int,
                            n_con_usr: Tuple[int, ...],
                            per_worker: Optional[int],
                            samples_per_level: int,
                            ready_timeout_s: float,
                            on_phase_start: Optional[Any] = None,
                            on_level_start: Optional[Any] = None,
                            on_level_done: Optional[Any] = None) -> Dict[str, Any]:
    """*_run_async_probes()* drive the loopback + handler-scaling probes against a uvicorn thread.

    Args:
        port (int): port the ping server binds to.
        loopback_samples (int): request count for the loopback probe.
        loopback_warmup (int): warmup GETs discarded upfront.
        n_con_usr (tuple[int, ...]): concurrent-user load levels for the handler-scaling probe.
        per_worker (int): requests per concurrent worker.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        on_phase_start (Optional[callable]): called with the phase name (`"loopback"` or `"handler_scaling"`) just before each phase begins, so the caller can print a progress marker at the right moment.
        on_level_start (Optional[callable]): forwarded to `measure_handler_scaling`.
        on_level_done (Optional[callable]): forwarded to `measure_handler_scaling`.

    Returns:
        dict: `{"loopback": {...}, "handler_scaling": {...}}`.
    """
    _result: Dict[str, Any] = {}
    _app = _build_ping_app()
    _server = _UvicornThread(_app, port)
    _server.start()
    try:
        _server.wait_ready(timeout_s=ready_timeout_s)
        if on_phase_start is not None:
            on_phase_start("loopback")
        _result["loopback"] = await measure_loopback(
            port=port,
            samples=loopback_samples,
            warmup=loopback_warmup,
        )
        if on_phase_start is not None:
            on_phase_start("handler_scaling")
        _result["handler_scaling"] = await measure_handler_scaling(
            port=port,
            n_con_usr=n_con_usr,
            warmup=loopback_warmup,
            per_worker=per_worker,
            samples_per_level=samples_per_level,
            on_level_start=on_level_start,
            on_level_done=on_level_done,
        )
    finally:
        _server.shutdown()
    return _result


def run(*,
        timer_samples: int = _DEFAULT_TIMER_SAMPLES,
        jitter_samples: int = _DEFAULT_JITTER_SAMPLES,
        loopback_samples: int = _DEFAULT_LOOPBACK_SAMPLES,
        loopback_warmup: int = _DEFAULT_LOOPBACK_WARMUP,
        n_con_usr: Tuple[int, ...] = _DEFAULT_N_CON_USR,
        per_worker: Optional[int] = None,
        samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
        port: int = _DEFAULT_PORT,
        ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
        skip_jitter: bool = _DEFAULT_SKIP_JITTER,
        skip_loopback: bool = _DEFAULT_SKIP_LOOPBACK,
        skip_rate_sweep: bool = _DEFAULT_SKIP_RATE_SWEEP,
        rate_sweep_rates: Tuple[float, ...] = _DEFAULT_RATE_SWEEP_RATES,
        rate_sweep_adaptation: str = _DEFAULT_RATE_SWEEP_ADAPTATION,
        rate_sweep_trials: int = _DEFAULT_RATE_SWEEP_TRIALS,
        rate_sweep_min_samples: int = _DEFAULT_RATE_SWEEP_MIN_SAMPLES,
        rate_sweep_max_probe_s: float = _DEFAULT_RATE_SWEEP_PROBE_S,
        rate_sweep_cascade_mode: str = _DEFAULT_RATE_SWEEP_CASCADE_MODE,
        rate_sweep_cascade_threshold: float = _DEFAULT_RATE_SWEEP_CASCADE_THRESHOLD,
        rate_sweep_cascade_window: int = _DEFAULT_RATE_SWEEP_CASCADE_WINDOW,
        rate_sweep_target_loss_pct: float = _DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
        rate_sweep_entry_service: str = _DEFAULT_RATE_SWEEP_ENTRY_SERVICE,
        rate_sweep_with_lambda_z: bool = False,
        rate_sweep_calibrate: bool = True,
        write: bool = True,
        output: Optional[str] = None,
        verbose: bool = True) -> Dict[str, Any]:
    """*run()* collect the calibration envelope.

    Runs the four host-floor probes (timer, jitter, loopback, handler scaling) under `_windows_timer_resolution(1)`. When `skip_rate_sweep=False`, additionally runs `run_rate_sweep(...)` and merges the result under the envelope's `rate_sweep` key. When `write=True`, the JSON is persisted under `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json` (or `output` when given) and the resolved path is recorded on the envelope as `output_path`.

    Args:
        timer_samples (int): back-to-back `perf_counter_ns` reads for the timer probe.
        jitter_samples (int): 1 ms sleep cycles for the jitter probe.
        loopback_samples (int): GET /ping samples for the loopback probe.
        loopback_warmup (int): warmup GETs discarded before the loopback probe.
        n_con_usr (tuple[int, ...]): concurrent-user load levels (in-flight requests) for the handler-scaling probe.
        per_worker (Optional[int]): sequential requests per concurrent worker; when `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per `n_con_usr` level when `per_worker` is derived.
        port (int): loopback ping server port.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        skip_jitter (bool): if True, skip the jitter probe.
        skip_loopback (bool): if True, skip both the loopback and handler-scaling probes.
        skip_rate_sweep (bool): if True (default from config), skip the rate-saturation probe; set to False to opt in.
        rate_sweep_rates (tuple[float, ...]): target rates (req/s) for the rate-sweep probe.
        rate_sweep_adaptation (str): adaptation stem the rate sweep drives against.
        rate_sweep_trials (int): trials per rate for rate-sweep aggregation.
        rate_sweep_min_samples (int): `min_samples_per_kind` per rate-sweep probe.
        rate_sweep_max_probe_s (float): rate-sweep probe wall-clock cap (seconds).
        rate_sweep_cascade_mode (str): rate-sweep cascade detector mode.
        rate_sweep_cascade_threshold (float): rate-sweep cascade threshold (fraction).
        rate_sweep_cascade_window (int): rate-sweep cascade detector window.
        rate_sweep_target_loss_pct (float): pass bar for the rate-sweep `calibrated_rate`.
        rate_sweep_entry_service (str): rate-sweep entry artifact for seeded `lambda_z` + per-trial `entry_lambda`.
        rate_sweep_with_lambda_z (bool): when True, inject the seeded `lambda_z` at `rate_sweep_entry_service` into the rate list.
        rate_sweep_calibrate (bool): when True, compute the highest-sustainable rate at or below `rate_sweep_target_loss_pct`.
        write (bool): persist the envelope to JSON when True.
        output (Optional[str]): override path when `write=True`; defaults to the per-host path.
        verbose (bool): print phase markers to stdout when True.

    Returns:
        dict: the envelope (`host_profile`, `args`, `timer`, `jitter`, `loopback`, `handler_scaling`, `rate_sweep` (optional), `timestamp`, `elapsed_s`, `output_path`).
    """
    _profile = snapshot_host_profile()
    _t0 = time.perf_counter()

    _n_con_usr_list: List[int] = []
    for _c in n_con_usr:
        _n_con_usr_list.append(int(_c))

    _now = datetime.now()
    _timestamp = _now.isoformat(timespec="seconds")

    if per_worker is None:
        _per_worker_record: Optional[int] = None
    else:
        _per_worker_record = int(per_worker)
    _args_block = {
        "timer_samples": int(timer_samples),
        "jitter_samples": int(jitter_samples),
        "loopback_samples": int(loopback_samples),
        "loopback_warmup": int(loopback_warmup),
        "n_con_usr": _n_con_usr_list,
        "per_worker": _per_worker_record,
        "samples_per_level": int(samples_per_level),
        "port": int(port),
        "skip_jitter": bool(skip_jitter),
        "skip_loopback": bool(skip_loopback),
        "skip_rate_sweep": bool(skip_rate_sweep),
    }
    _envelope: Dict[str, Any] = {
        "host_profile": _profile,
        "args": _args_block,
        "timestamp": _timestamp,
    }

    with _windows_timer_resolution(1):
        if verbose:
            print("  [1/4] timer resolution ...", flush=True)
        _envelope["timer"] = measure_timer(timer_samples)

        if skip_jitter:
            if verbose:
                print("  [2/4] jitter ... SKIPPED", flush=True)
        else:
            if verbose:
                print("  [2/4] scheduling jitter ...", flush=True)
            _envelope["jitter"] = measure_jitter(jitter_samples)

        if skip_loopback:
            if verbose:
                print("  [3/4] loopback ... SKIPPED", flush=True)
                print("  [4/4] handler scaling ... SKIPPED", flush=True)
        else:
            if verbose:
                _on_phase = _print_phase_marker
                _on_level_start = _print_level_start
                _on_level_done = _print_level_done
            else:
                _on_phase = None
                _on_level_start = None
                _on_level_done = None

            _probes = _run_probes_in_dedicated_loop(
                port=port,
                loopback_samples=loopback_samples,
                loopback_warmup=loopback_warmup,
                n_con_usr=n_con_usr,
                per_worker=per_worker,
                samples_per_level=samples_per_level,
                ready_timeout_s=ready_timeout_s,
                on_phase_start=_on_phase,
                on_level_start=_on_level_start,
                on_level_done=_on_level_done,
            )
            _envelope.update(_probes)

    # P0.2 rate-saturation probe; opt-in, runs outside the Windows timer ctx (experiment.run owns its own timer boost)
    if skip_rate_sweep:
        if verbose:
            print()
            print("  [5/5] rate sweep ... SKIPPED "
                  "(opt in via skip_rate_sweep=False)", flush=True)
    else:
        if verbose:
            print()
            print("  [5/5] rate saturation sweep ...", flush=True)
        _envelope["rate_sweep"] = run_rate_sweep(
            rates=rate_sweep_rates,
            adaptation=rate_sweep_adaptation,
            trials_per_rate=rate_sweep_trials,
            min_samples=rate_sweep_min_samples,
            max_probe_s=rate_sweep_max_probe_s,
            cascade_mode=rate_sweep_cascade_mode,
            cascade_threshold=rate_sweep_cascade_threshold,
            cascade_window=rate_sweep_cascade_window,
            target_loss_pct=rate_sweep_target_loss_pct,
            entry_service=rate_sweep_entry_service,
            with_lambda_z=rate_sweep_with_lambda_z,
            calibrate=rate_sweep_calibrate,
            verbose=verbose,
        )

    # Route-B dimensional card from measured handler_scaling + loopback; phi stays NaN when payload_size_bytes=0
    if ("handler_scaling" in _envelope) and ("loopback" in _envelope):
        _dim_card = derive_calib_coefs(_envelope, payload_size_bytes=0)
        if _dim_card:
            _envelope["dimensional_card"] = _dim_card

    _t_end = time.perf_counter()
    _elapsed = _t_end - _t0
    _envelope["elapsed_s"] = round(_elapsed, 3)

    if write:
        if output:
            _out = Path(output)
        else:
            _out = _build_output_path(_profile)
        _write_json(_out, _envelope)
        _envelope["output_path"] = str(_out)

    # final GC pass; httpx/uvicorn module caches may still hold cycles
    gc.collect()
    return _envelope


def _build_argparser() -> argparse.ArgumentParser:
    """*_build_argparser()* CLI surface."""
    _p = argparse.ArgumentParser(
        prog="calibration",
        description=("Per-host noise-floor characterisation for the "
                     "experiment method. Produces one JSON envelope under "
                     "data/results/experiment/calibration/. Run BEFORE "
                     "every experiment sweep."))
    _p.add_argument("--timer-samples", type=int,
                    default=_DEFAULT_TIMER_SAMPLES,
                    help=("back-to-back perf_counter_ns reads for the timer "
                          f"probe (default: {_DEFAULT_TIMER_SAMPLES})"))
    _p.add_argument("--jitter-samples", type=int,
                    default=_DEFAULT_JITTER_SAMPLES,
                    help=("1 ms sleep samples for the jitter probe "
                          f"(default: {_DEFAULT_JITTER_SAMPLES})"))
    _p.add_argument("--loopback-samples", type=int,
                    default=_DEFAULT_LOOPBACK_SAMPLES,
                    help=("GET /ping samples for the loopback probe "
                          f"(default: {_DEFAULT_LOOPBACK_SAMPLES})"))
    _p.add_argument("--loopback-warmup", type=int,
                    default=_DEFAULT_LOOPBACK_WARMUP,
                    help=("warmup GETs discarded before the loopback probe "
                          f"(default: {_DEFAULT_LOOPBACK_WARMUP})"))
    _default_n_con_usr_tokens: List[str] = []
    for _c in _DEFAULT_N_CON_USR:
        _default_n_con_usr_tokens.append(str(_c))
    _default_n_con_usr_csv = ",".join(_default_n_con_usr_tokens)

    _p.add_argument("--n-con-usr", type=str, default=None,
                    help=("comma-separated concurrent-user load levels "
                          "(in-flight requests) for the handler-scaling "
                          "probe "
                          f"(default: {_default_n_con_usr_csv})"))
    _p.add_argument("--per-worker", type=int, default=None,
                    help=("sequential requests per concurrent worker; "
                          "when omitted, derived from --samples-per-level "
                          "so total samples per level stay bounded"))
    _p.add_argument("--samples-per-level", type=int,
                    default=_DEFAULT_SAMPLES_PER_LEVEL,
                    help=("target total samples per n_con_usr level "
                          "when --per-worker is derived "
                          f"(default: {_DEFAULT_SAMPLES_PER_LEVEL})"))
    _p.add_argument("--port", type=int, default=_DEFAULT_PORT,
                    help=("loopback ping server port "
                          f"(default: {_DEFAULT_PORT})"))
    _p.add_argument("--ready-timeout-s", type=float,
                    default=_DEFAULT_READY_TIMEOUT_S,
                    help=("seconds to wait for uvicorn readiness "
                          f"(default: {_DEFAULT_READY_TIMEOUT_S})"))
    _p.add_argument("--skip-loopback", action="store_true",
                    help="run only the timer + jitter probes (no HTTP)")
    _p.add_argument("--skip-jitter", action="store_true",
                    help="run only the timer probe (fastest self-test)")

    # -- rate-sweep flags (opt-in; adds ~N_rates * trials * probe_s to wall time) --
    _default_rates_tokens: List[str] = []
    for _r in _DEFAULT_RATE_SWEEP_RATES:
        _default_rates_tokens.append(str(_r))
    _default_rates_csv = ",".join(_default_rates_tokens)

    if _DEFAULT_SKIP_RATE_SWEEP:
        _default_rate_sweep_state = "OFF"
    else:
        _default_rate_sweep_state = "ON"
    _p.add_argument("--rate-sweep", dest="rate_sweep", action="store_true",
                    default=(not _DEFAULT_SKIP_RATE_SWEEP),
                    help=("enable the rate-saturation probe; each target rate "
                          "runs `--rate-sweep-trials` full experiment-method "
                          "trials. Opt-in by default "
                          f"(currently {_default_rate_sweep_state})"))
    _p.add_argument("--no-rate-sweep", dest="rate_sweep",
                    action="store_false",
                    help="explicit opt-out of the rate-saturation probe")
    _p.add_argument("--rate-sweep-rates", type=str, default=None,
                    help=("comma-separated target rates in req/s for the "
                          f"rate-saturation probe (default: {_default_rates_csv})"))
    _p.add_argument("--rate-sweep-adp", type=str,
                    default=_DEFAULT_RATE_SWEEP_ADAPTATION,
                    choices=("baseline", "s1", "s2", "aggregate"),
                    help=("adaptation driven by the rate-saturation probe "
                          f"(default: {_DEFAULT_RATE_SWEEP_ADAPTATION})"))
    _p.add_argument("--rate-sweep-trials", type=int,
                    default=_DEFAULT_RATE_SWEEP_TRIALS,
                    help=("trials per rate for rate-sweep aggregation "
                          f"(default: {_DEFAULT_RATE_SWEEP_TRIALS})"))
    _p.add_argument("--rate-sweep-target-loss", type=float,
                    default=_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                    help=("pass bar (percent) for the calibrated "
                          "highest-sustainable rate "
                          f"(default: {_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT})"))
    _p.add_argument("--rate-sweep-with-lambda-z", action="store_true",
                    help=("inject the seeded lambda_z at the entry service "
                          "into the rate-sweep rate list"))

    _p.add_argument("--output", type=str, default=None,
                    help=("override the output path; default is "
                          "data/results/experiment/calibration/<host>_<date>.json"))
    return _p


# Route-B dimensional card; shape matches src.view.dc_charts.plot_yoly_chart
_CALIB_DIM_TAG = "CALIB"


def _build_calib_observables(handler_scaling: Dict[str, Dict[str, float]],
                             loopback: Dict[str, float],
                             *,
                             payload_size_bytes: int,
                             uvicorn_backlog: int,
                             c_srv: int,
                             ) -> Dict[str, np.ndarray]:
    """*_build_calib_observables()* extract per-`n_con_usr` measurement arrays from a calibration envelope.

    Aggregates the measured response-time medians at each `n_con_usr` level into the operational quantities the M/M/c/K Variable schema expects (lambda, mu, c, K, L, Lq, W, Wq, M_act, M_buf, d, eps, chi). Each array has one entry per level, ordered by ascending `n_con_usr`. Used to populate `Variable._data` arrays so PyDASA's MonteCarloSimulation can evaluate coefficient expressions row-wise.

    Args:
        handler_scaling (Dict[str, Dict[str, float]]): envelope's `handler_scaling` block; keys are `n_con_usr` as strings, values hold `median_us` and distribution stats.
        loopback (Dict[str, float]): envelope's `loopback` block; `median_us` supplies the idle-service reference.
        payload_size_bytes (int): per-request body size in bytes; populates `M_act`, `M_buf`, `d`. When 0, the memory-usage coefficient `phi` reduces to a degenerate 0/0 and is post-processed to NaN.
        uvicorn_backlog (int): system capacity `K`.
        c_srv (int): service-side parallel-handler count (always 1 for the calibration service).

    Returns:
        Dict[str, np.ndarray]: arrays keyed by short symbolic name (`n`, `lam`, `mu`, `eps`, `chi`, `c`, `K`, `L`, `Lq`, `W`, `Wq`, `M_act`, `M_buf`, `d`); all share length N (number of `n_con_usr` levels).
    """
    _r_median_us = float(loopback.get("median_us", 0.0))
    if _r_median_us <= 0.0:
        _mu_scalar = 0.0
    else:
        _mu_scalar = 1e6 / _r_median_us
    _k_capacity = int(uvicorn_backlog)

    _levels: List[int] = []
    for _k in handler_scaling.keys():
        _levels.append(int(_k))
    _levels.sort()

    _n_arr: List[int] = []
    _r_arr: List[float] = []
    for _n in _levels:
        _stats = handler_scaling.get(str(_n), {})
        _median_us = float(_stats.get("median_us", 0.0))
        _n_arr.append(int(_n))
        _r_arr.append(_median_us * 1e-6)

    _n_np = np.asarray(_n_arr, dtype=float)
    _r_np = np.asarray(_r_arr, dtype=float)

    # zero-latency rows -> NaN so downstream divisions stay finite
    _r_safe = np.where(_r_np > 0.0, _r_np, np.nan)
    _x = _n_np / _r_safe                              # X = n / R
    _lam = _x                                         # steady state: lambda = X
    _l_load = _n_np                                   # Little: L = X*R = n
    _r_service = _r_median_us * 1e-6
    _wq = np.maximum(_r_np - _r_service, 0.0)

    _eps = np.zeros_like(_n_np, dtype=float)
    _chi = _lam * (1.0 - _eps)
    _c_np = np.full_like(_n_np, float(c_srv))
    _k_np = np.full_like(_n_np, float(_k_capacity))
    _mu_np = np.full_like(_n_np, float(_mu_scalar))

    # memory side; d in kB. 0 means "degenerate phi" -> NaN row downstream
    _d_kB = float(payload_size_bytes) / 1000.0
    _m_act = _l_load * _d_kB
    _m_buf = _k_np * _d_kB

    _out: Dict[str, np.ndarray] = {
        "n": _n_np,
        "lam": _lam,
        "mu": _mu_np,
        "chi": _chi,
        "c": _c_np,
        "K": _k_np,
        "L": _l_load,
        "W": _r_np,
        "Wq": _wq,
        "M_act": _m_act,
        "M_buf": _m_buf,
    }
    return _out


# Variable schema for the calibration artifact. Trimmed to what the four
# target coefficients (theta, sigma, eta, phi) reference. Memory variables use
# `M_{a<tag>}` / `M_{b<tag>}` (a = active, b = buffer): sympy's parse_latex
# treats multi-character roots (e.g. `MA_{X}`) as products of single letters
# (`M*A`), which mangles aliases; keeping a single-letter root with the tag
# folded into the subscript avoids that. q-suffixed forms (Lq, Wq) and the
# nested-brace M_{act_{X}} layout are excluded for the same reason: their
# coefficient expressions break sympy's LaTeX parser when MCS lambdifies them.
_CALIB_VAR_SPECS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    # (short_key, latex_template, dims, units, cat, dist_type)
    ("lam", "\\lambda_{<TAG>}", "S*T^-1", "req/s", "IN", "uniform"),
    ("mu", "\\mu_{<TAG>}", "S*T^-1", "req/s", "CTRL", "uniform"),
    ("chi", "\\chi_{<TAG>}", "S*T^-1", "req/s", "CTRL", "uniform"),
    ("c", "c_{<TAG>}", "S", "req", "IN", "uniform_int"),
    ("K", "K_{<TAG>}", "S", "req", "CTRL", "uniform_int"),
    ("L", "L_{<TAG>}", "S", "req", "CTRL", "uniform"),
    ("W", "W_{<TAG>}", "T", "s", "OUT", "uniform"),
    ("M_act", "M_{a<TAG>}", "D", "kB", "CTRL", "uniform"),
    ("M_buf", "M_{b<TAG>}", "D", "kB", "CTRL", "uniform"),
)


def _calib_var_sym(short: str, tag: str) -> str:
    """*_calib_var_sym()* render a calibration-variable LaTeX symbol from its short key.

    Looks the short key up in `_CALIB_VAR_SPECS` and substitutes the tag into the per-variable LaTeX template (where `<TAG>` marks the subscript slot).

    Args:
        short (str): short key (`"lam"`, `"mu"`, `"M_act"`, ...).
        tag (str): artifact subscript tag (e.g. `"CALIB"`).

    Raises:
        KeyError: when `short` is not in `_CALIB_VAR_SPECS`.

    Returns:
        str: full LaTeX symbol (e.g. `"\\lambda_{CALIB}"`, `"M_{aCALIB}"`).
    """
    for _spec in _CALIB_VAR_SPECS:
        if _spec[0] == short:
            return _spec[1].replace("<TAG>", tag)
    raise KeyError(f"unknown calibration variable short key: {short!r}")


def _build_calib_vars(observables: Dict[str, np.ndarray],
                      *,
                      tag: str) -> Dict[str, Dict[str, Any]]:
    """*_build_calib_vars()* construct a per-artifact PACS Variable dict for the calibration data.

    Each `_CALIB_VAR_SPECS` entry yields one Variable dict shaped to match `pydasa.elements.parameter.Variable.__init__`. The measured array from `observables` populates `_data`; `_setpoint` / `_min` / `_max` / `_mean` are derived as nan-aware reductions over that array so `Variable.calculate_setpoint()` works at deterministic values.

    Args:
        observables (Dict[str, np.ndarray]): output of `_build_calib_observables`.
        tag (str): artifact subscript tag used in the LaTeX symbols.

    Returns:
        Dict[str, Dict[str, Any]]: PACS Variable-dict for the calibration artifact, ready to feed `src.dimensional.build_engine`.
    """
    _vars: Dict[str, Dict[str, Any]] = {}
    for _idx, _spec in enumerate(_CALIB_VAR_SPECS, start=1):
        _short, _template, _dims, _units, _cat, _dist = _spec
        _arr = observables[_short]

        if _arr.size > 0:
            _finite = _arr[np.isfinite(_arr)]
        else:
            _finite = _arr
        if _finite.size > 0:
            _mn = float(np.min(_finite))
            _mx = float(np.max(_finite))
            _mean = float(np.mean(_finite))
            _setp = float(np.median(_finite))
        else:
            _mn = 0.0
            _mx = 0.0
            _mean = 0.0
            _setp = 0.0

        _sym = _calib_var_sym(_short, tag)
        _alias = _sym.replace("\\", "").replace("{", "").replace("}", "").replace(",", "").replace(" ", "_")

        if _mx > _mn:
            _params = {"low": _mn, "high": _mx}
        else:
            _params = {"low": _mn, "high": _mn + 1.0}

        _vars[_sym] = {
            "_sym": _sym,
            "_fwk": "CUSTOM",
            "_alias": _alias,
            "_idx": _idx,
            "_name": f"{tag} {_short}",
            "description": f"Calibration {_short} per n_con_usr level",
            "_cat": _cat,
            "relevant": True,
            "_dims": _dims,
            "_units": _units,
            "_std_units": _units,
            "_setpoint": _setp,
            "_min": _mn,
            "_max": _mx,
            "_mean": _mean,
            "_dist_type": _dist,
            "_dist_params": _params,
            "_depends": [],
            "_data": [float(_v) for _v in _arr.tolist()],
        }
    return _vars


def _run_calib_pipeline(vars_block: Dict[str, Dict[str, Any]],
                        *,
                        n_levels: int,
                        tag: str
                        ) -> Dict[str, np.ndarray]:
    """*_run_calib_pipeline()* drive PyDASA Variable -> Schema -> AnalysisEngine -> Coefficient(...) -> MonteCarloSimulation(DATA) and extract per-level coefficient arrays.

    The calibration `_data` arrays live on the Variables. The engine instantiates them and runs Buckingham; the four target coefficients (theta, sigma, eta, phi) are then constructed as `pydasa.Coefficient` objects directly, with `_pi_expr` written in terms of the base CALIB variables (so we are robust to Pi-group ordering shifts vs the TAS profile). `MonteCarloSimulation.run_simulation(mode='DATA')` lambdifies each coefficient expression and evaluates it row-wise across the `_data` arrays.

    Args:
        vars_block (Dict[str, Dict[str, Any]]): PACS Variable dict produced by `_build_calib_vars`.
        n_levels (int): number of measurement rows; matches the length of every `_data` array.
        tag (str): artifact subscript tag (`"CALIB"`).

    Returns:
        Dict[str, np.ndarray]: coefficient arrays keyed by full LaTeX symbol (`\\theta_{<tag>}`, `\\sigma_{<tag>}`, `\\eta_{<tag>}`, `\\phi_{<tag>}`); one entry per level.
    """
    # PyDASA stack imported lazily so calibration's import surface stays light
    from pydasa import Coefficient, MonteCarloSimulation  # noqa: WPS433
    from src.dimensional import build_engine, build_schema  # noqa: WPS433
    from src.io import load_method_cfg  # noqa: WPS433

    _mcfg = load_method_cfg("dimensional")
    _sch = build_schema(_mcfg["fdus"])
    _eng = build_engine(tag, vars_block, _sch)
    _eng.run_analysis()

    # Resolve runtime variable symbols and build target-coefficient expressions
    # against base variables (no Pi-group indices) so the pipeline is robust
    # against Buckingham's ordering shifts on a different variable set.
    _lam = _calib_var_sym("lam", tag)
    _mu = _calib_var_sym("mu", tag)
    _chi = _calib_var_sym("chi", tag)
    _c = _calib_var_sym("c", tag)
    _K = _calib_var_sym("K", tag)
    _L = _calib_var_sym("L", tag)
    _W = _calib_var_sym("W", tag)
    _MA = _calib_var_sym("M_act", tag)
    _MB = _calib_var_sym("M_buf", tag)

    _coef_specs = (
        ("\\theta", "Occupancy",
         f"\\frac{{{_L}}}{{{_K}}}",
         (_L, _K)),
        ("\\sigma", "Stall",
         f"\\frac{{{_lam}*{_W}}}{{{_L}}}",
         (_lam, _W, _L)),
        ("\\eta", "Effective-yield",
         f"\\frac{{{_chi}*{_K}}}{{{_c}*{_mu}}}",
         (_chi, _K, _c, _mu)),
        ("\\phi", "Memory-usage",
         f"\\frac{{{_MA}}}{{{_MB}}}",
         (_MA, _MB)),
    )

    _der: Dict[str, Any] = {}
    for _sym_pre, _name, _expr, _refs in _coef_specs:
        _full = f"{_sym_pre}_{{{tag}}}"
        _coeff = Coefficient(_sym=_full,
                             _pi_expr=_expr,
                             _fwk="CUSTOM",
                             _variables=dict(_eng.variables),
                             _name=f"{tag} {_name} coefficient",
                             description=f"{_name} ({_full})")
        # __post_init__ resets var_dims when _dim_col is empty; populate after
        # construction so MonteCarloSimulation accepts the coefficient.
        _coeff.var_dims = {_v: 0 for _v in _refs}
        _der[_full] = _coeff

    _mcs = MonteCarloSimulation(
        _variables=_eng.variables,
        _coefficients=_der,
        _experiments=max(int(n_levels), 1),
        _fwk="CUSTOM",
        _cat="DATA",
    )
    _mcs.create_simulations()
    # 0/0 in the phi expression when payload_size_bytes=0 surfaces as a
    # RuntimeWarning from the lambdified function; the resulting NaNs are
    # forced to NaN downstream regardless, so silence the noise.
    with np.errstate(divide="ignore", invalid="ignore"):
        _mcs.run_simulation(iters=max(int(n_levels), 1), mode="DATA")

    _out: Dict[str, np.ndarray] = {}
    for _sym in _der.keys():
        _blk = _mcs._results.get(_sym, {})
        _arr = np.asarray(_blk.get("results", []), dtype=float)
        _out[_sym] = _arr
    return _out


def derive_calib_coefs(envelope: Dict[str, Any],
                       *,
                       payload_size_bytes: int = 0,
                       tag: str = _CALIB_DIM_TAG) -> Dict[str, Any]:
    """*derive_calib_coefs()* public entry point: build the dimensional card from a calibration envelope using PyDASA.

    Routes the measured `handler_scaling` + `loopback` arrays through the PyDASA pipeline (Variable dicts -> Schema -> AnalysisEngine -> derive_coefs -> MonteCarloSimulation in DATA mode) so theta / sigma / eta / phi are computed by PyDASA's symbolic evaluator, not by hand-rolled arithmetic. Coefficient symbols carry the `_{<tag>}` subscript (default `_{CALIB}`).

    Route B semantics: coefficients are derived from measurements, not from an M/M/c/K prediction. Applies only when both `handler_scaling` and `loopback` are present in the envelope; returns an empty dict otherwise.

    Args:
        envelope (Dict[str, Any]): calibration envelope (e.g. from `run()` or `load_latest_calibration()`).
        payload_size_bytes (int): body size per request for the phi coefficient; 0 marks phi as NaN to flag the degenerate 0/0 memory case.
        tag (str): LaTeX-subscript tag used in output keys. Default `CALIB`.

    Returns:
        Dict[str, Any]: coefficient arrays (JSON-serialisable `List[float]`) keyed by LaTeX-subscripted symbol (`\\theta_{<tag>}`, `\\sigma_{<tag>}`, `\\eta_{<tag>}`, `\\phi_{<tag>}`, plus the input-side `c_{<tag>}`, `\\mu_{<tag>}`, `K_{<tag>}`, `\\lambda_{<tag>}`, `n_con_usr_{<tag>}`), and a `meta` sub-dict with provenance (`tag / mu_source / mu_req_per_s / c_srv / uvicorn_backlog / payload_size_bytes / n_con_usr / pipeline`). Empty dict when `handler_scaling` or `loopback` is missing.
    """
    _handler = envelope.get("handler_scaling")
    _loop = envelope.get("loopback")
    if not isinstance(_handler, dict) or not isinstance(_loop, dict):
        return {}

    _args_block = envelope.get("args") or {}
    _backlog = int(_args_block.get("uvicorn_backlog",
                                   _DEFAULT_UVICORN_BACKLOG))

    _obs = _build_calib_observables(
        handler_scaling=_handler,
        loopback=_loop,
        payload_size_bytes=payload_size_bytes,
        uvicorn_backlog=_backlog,
        c_srv=1,
    )
    _n_levels = int(_obs["n"].size)

    if _n_levels == 0:
        return {}

    _vars_block = _build_calib_vars(_obs, tag=tag)
    _coef_arrays = _run_calib_pipeline(_vars_block, n_levels=_n_levels, tag=tag)

    # phi is degenerate (0/0) when no payload was supplied; force NaN so the dashboard skips the panel
    _phi_key = f"\\phi_{{{tag}}}"
    if int(payload_size_bytes) <= 0 and _phi_key in _coef_arrays:
        _coef_arrays[_phi_key] = np.full(_n_levels, np.nan, dtype=float)

    # carry the input-side context arrays alongside the coefficients so plot_yoly_chart panel labels stay honest
    _context = {
        f"c_{{{tag}}}": _obs["c"],
        f"\\mu_{{{tag}}}": _obs["mu"],
        f"K_{{{tag}}}": _obs["K"],
        f"\\lambda_{{{tag}}}": _obs["lam"],
        f"n_con_usr_{{{tag}}}": _obs["n"],
    }

    _coefs: Dict[str, Any] = {}
    for _k, _v in _coef_arrays.items():
        _coefs[_k] = [float(_x) for _x in np.asarray(_v, dtype=float).tolist()]
    for _k, _v in _context.items():
        _coefs[_k] = [float(_x) for _x in np.asarray(_v, dtype=float).tolist()]

    if _obs["mu"].size > 0:
        _mu_val = float(_obs["mu"][0])
    else:
        _mu_val = 0.0
    _meta = {
        "tag": str(tag),
        "mu_source": "loopback.median_us",
        "mu_req_per_s": _mu_val,
        "c_srv": 1,
        "uvicorn_backlog": _backlog,
        "payload_size_bytes": int(payload_size_bytes),
        "n_con_usr": [int(_n) for _n in _obs["n"].tolist()],
        "pipeline": "pydasa.MonteCarloSimulation(mode=DATA)",
    }
    _coefs["meta"] = _meta
    return _coefs


def main(argv: Optional[List[str]] = None) -> None:
    """*main()* CLI entry point; parses `argv` and delegates to `run()`.

    Args:
        argv (Optional[List[str]]): argv override for tests; None uses `sys.argv`.
    """
    _parser = _build_argparser()
    _args = _parser.parse_args(argv)
    if _args.n_con_usr is not None:
        _n_con_usr = _parse_n_con_usr(_args.n_con_usr)
    else:
        _n_con_usr = _DEFAULT_N_CON_USR
    if _args.rate_sweep_rates is not None:
        _rate_sweep_rates = _parse_rates(_args.rate_sweep_rates)
    else:
        _rate_sweep_rates = _DEFAULT_RATE_SWEEP_RATES

    _hostname = socket.gethostname()
    _py_ver = platform.python_version()
    _banner(f"calibration.py  host={_hostname!r}  python={_py_ver}")
    print(f"  timer_samples={_args.timer_samples}  "
          f"jitter_samples={_args.jitter_samples}  "
          f"loopback_samples={_args.loopback_samples}  "
          f"n_con_usr={_n_con_usr}")
    if _args.rate_sweep:
        print(f"  rate_sweep=ON  rates={list(_rate_sweep_rates)}  "
              f"trials={_args.rate_sweep_trials}  "
              f"adp={_args.rate_sweep_adp!r}  "
              f"target_loss={_args.rate_sweep_target_loss}%")
    else:
        print("  rate_sweep=OFF (pass --rate-sweep to opt in)")
    print()

    _envelope = run(
        timer_samples=_args.timer_samples,
        jitter_samples=_args.jitter_samples,
        loopback_samples=_args.loopback_samples,
        loopback_warmup=_args.loopback_warmup,
        n_con_usr=_n_con_usr,
        per_worker=_args.per_worker,
        samples_per_level=_args.samples_per_level,
        port=_args.port,
        ready_timeout_s=_args.ready_timeout_s,
        skip_jitter=_args.skip_jitter,
        skip_loopback=_args.skip_loopback,
        skip_rate_sweep=(not _args.rate_sweep),
        rate_sweep_rates=_rate_sweep_rates,
        rate_sweep_adaptation=_args.rate_sweep_adp,
        rate_sweep_trials=_args.rate_sweep_trials,
        rate_sweep_target_loss_pct=_args.rate_sweep_target_loss,
        rate_sweep_with_lambda_z=_args.rate_sweep_with_lambda_z,
        write=True,
        output=_args.output,
        verbose=True,
    )

    _print_summary(_envelope)
    print()
    _out_path = _envelope.get("output_path")
    print(f"  >>> written: {_out_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[interrupted]")
        sys.exit(130)
