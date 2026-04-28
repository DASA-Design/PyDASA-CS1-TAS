# -*- coding: utf-8 -*-
"""
Module methods/calibration.py
=============================

Per-host noise-floor characterisation. Sibling to `src.methods.analytic` / `stochastic` / `dimensional` / `experiment`, but its subject is the host, not the TAS architecture. Runs four baselines (timer resolution, scheduling jitter, loopback latency, vernier-handler scaling over `n_con_usr`) and writes one JSON envelope to `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`. Every `experiment` run references the latest envelope by timestamp (`baseline_ref`) so measured latencies report as `value - loopback_median +/- jitter_p99`.

Three public entry points share this module:

    - `run(...)` host-floor probes + optional rate-saturation block + Route-B dim card.
    - `run_rate_sweep(...)` rate-saturation probe driven against the standalone ping/echo vernier (host-transport ceiling); opt-in.
    - `run_calib_sweep(envelope, sweep_grid, ...)` Route-B measured sweep across `(c, K, mu_factor)`; drives vernier per combo and reuses `derive_calib_coefs`.

Kept deliberately small and dependency-light:

    - `time.perf_counter_ns()` throughout; integer arithmetic in the hot path, seconds only at JSON-write time.
    - A vernier echo service (`mount_vernier_svc` -> `POST /invoke`) runs in a background uvicorn thread so the loopback probe measures real TCP loopback, not ASGI in-process shortcuts. Requests carry a `SvcReq` body whose `payload.blob` is `payload_size_bytes` long, so the bytes traverse the kernel buffer + ASGI stack end-to-end and `phi` becomes informative.
    - `winmm.timeBeginPeriod(1)` is wrapped around the probe block via a contextmanager so asyncio.sleep can resolve sub-15-ms intervals on Windows.

Run::

    python -m src.methods.calibration
    python -m src.methods.calibration --timer-samples 50000 --jitter-samples 2000
    python -m src.methods.calibration --loopback-samples 2000 --n-con-usr 1,10,50,100
    python -m src.methods.calibration --skip-loopback                    # timer + jitter only
    python -m src.methods.calibration --rate-sweep                       # adds rate-saturation block
    python -c "from src.methods.calibration import run, run_calib_sweep; \\
               env = run(); run_calib_sweep(env)"                          # measured sweep

Output JSON shape (truncated)::

    {
        "host_profile":      {"hostname": "...", "os": "...", "cpu_count": 16, ...},
        "args":              {"timer_samples": 100000, ...},
        "timer":             {"min_ns": 100, "median_ns": 100.0, ...},
        "jitter":            {"mean_us": 627, "p99_us": 1272, "max_us": 10386, ...},
        "loopback":          {"min_us": 2210, "median_us": 3121, "p99_us": 7681, ...},
        "handler_scaling":   {"1": {...}, "10": {...}, "100": {...}, "1000": {...}},
        "rate_sweep":        {"rates": [...], "aggregates": {...}, ...},     # optional
        "dimensional_card":  {"\\theta_{CALIB}": [...], ...},                  # Route-B card
        "timestamp":         "2026-04-25T14:31:53",
        "elapsed_s":         37.4,
        "output_path":       ".../DESKTOP-INKGBK6_20260425_143153.json"
    }

The Route-B sweep envelope written by `run_calib_sweep` lands at the same directory with a `_sweep` suffix and carries one combo block per `(c, K, mu_factor)` cartesian point.
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
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

# web stack
import httpx
from fastapi import FastAPI

# local modules
from src.experiment.payload import generate_payload
from src.experiment.services import (SvcReq,
                                     SvcSpec,
                                     make_base_app,
                                     mount_vernier_svc)
from src.experiment.uvicorn_thread import UvicornThread

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
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
# per-request body size (bytes) for the phi coefficient; 0 -> NaN, 131072 (128 kB) -> phi resolves to L/K
_DEFAULT_PAYLOAD_SIZE_BYTES = int(_CALIB_CFG.get("payload_size_bytes", 0))
# quiet windows between phase-4 levels + phase-5 trials; lets uvicorn drain before the next ramp (default 0.0 = legacy no-delay)
_DEFAULT_INTER_LEVEL_DELAY_S = float(_CALIB_CFG.get("inter_level_delay_s", 0.0))
_DEFAULT_INTER_TRIAL_DELAY_S = float(_CALIB_CFG.get("inter_trial_delay_s", 0.0))

# rate-sweep: drives the standalone ping/echo vernier at increasing rates; opt-in via config or --rate-sweep
_DEFAULT_SKIP_RATE_SWEEP = bool(_CALIB_CFG.get("skip_rate_sweep", True))
_RATE_SWEEP_CFG: Dict[str, Any] = _CALIB_CFG.get("rate_sweep", {})
_DEFAULT_RATE_SWEEP_RATES: Tuple[float, ...] = tuple(
    float(_r) for _r in _RATE_SWEEP_CFG.get("rates", ()))
_DEFAULT_RATE_SWEEP_TRIALS = int(_RATE_SWEEP_CFG.get("trials_per_rate", 5))
_DEFAULT_RATE_SWEEP_PROBE_S = float(
    _RATE_SWEEP_CFG.get("max_probe_window_s", 4.0))
_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT = float(
    _RATE_SWEEP_CFG.get("target_loss_pct", 2.0))

# jitter-probe sleep target (ns); same unit as the hot path
_JITTER_TARGET_NS = int(_CALIB_CFG.get("jitter_target_ns", 1_000_000))

# auto-batch tick (s); mirrors ClientSimulator._probe_at_rate, duplicated to keep experiment import out of the rate sweep
_TARGET_TICK_S: float = 0.020


def _banner(msg: str) -> None:
    """*_banner()* render a centred header band on stdout."""
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
    except (OSError, AttributeError):
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
    """*measure_timer()* return min/median/mean/std of clock resolution from back-to-back `perf_counter_ns` reads.

    Zero-delta reads (same tick bucket) are skipped; only positive deltas are summarised. The minimum tick is the actual clock resolution on this host.

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
        return {
            "min_ns": 0,
            "median_ns": 0.0,
            "mean_ns": 0.0,
            "std_ns": 0.0,
            "zero_frac": 1.0,
        }
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
    """*measure_jitter()* report mean/std/p50/p99/max of OS sleep oversleep across N samples of `time.sleep(0.001)`.

    Records the difference between requested 1 ms and the actual elapsed ns. `max_us` and `p99_us` are the OS-interruption tail; any inter-arrival smaller than those values cannot resolve cleanly.

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
    """*_build_ping_app()* FastAPI app with the vernier echo route.

    Mounts a single terminal `mount_vernier_svc` handler on the app. SvcSpec knobs come from `data/config/method/calibration.json`: `c` and `K` are the first elements of `sweep_grid.{c, K}`; `mu` and `epsilon` are zero so the loopback floor stays honest; `mem_per_buffer` is derived from `payload_size_bytes * K * SvcSpec.MEM_HEADROOM_FACTOR`.

    Returns:
        FastAPI: app with `/healthz` (from `make_base_app`) and `/invoke` (from vernier).
    """
    _grid = _CALIB_CFG.get("sweep_grid", {})
    _payload_bytes = int(_DEFAULT_PAYLOAD_SIZE_BYTES)
    _c_list = _grid.get("c", [1])
    _K_list = _grid.get("K", [50])
    if _c_list:
        _c = int(_c_list[0])
    else:
        _c = 1
    if _K_list:
        _K = int(_K_list[0])
    else:
        _K = 50
    _spec = SvcSpec(name="CALIB",
                    role="atomic",
                    port=int(_DEFAULT_PORT),
                    mu=0.0,
                    epsilon=0.0,
                    c=_c,
                    K=_K,
                    seed=0,
                    mem_per_buffer=int(_payload_bytes * _K * SvcSpec.MEM_HEADROOM_FACTOR))
    _app = make_base_app("calibration-vernier")
    mount_vernier_svc(_app, _spec, payload_size_bytes=_payload_bytes)
    return _app


# `UvicornThread` was extracted to `src.experiment.uvicorn_thread` so the calibration probe, the experiment launcher, and the launch_services script share one lifecycle. The legacy `_UvicornThread` alias keeps existing code paths unchanged.
_UvicornThread = UvicornThread


def _stats_from_us_array(us_arr: np.ndarray) -> Dict[str, float]:
    """*_stats_from_us_array()* return the canonical 6-key latency-stats dict from a microsecond array.

    Single source of truth for the `handler_scaling[<level>]` shape (`min_us`, `median_us`, `p95_us`, `p99_us`, `std_us`, `samples`). Reused by `measure_loopback`, `measure_handler_scaling`, and `_drive_lambda_step` so the schema is declared once.

    Args:
        us_arr (np.ndarray): per-request latencies in microseconds; empty array yields a zero-valued stats dict so callers can short-circuit on `samples == 0`.

    Returns:
        Dict[str, float]: stats keyed identically to a `handler_scaling` entry.
    """
    if us_arr.size == 0:
        return {
            "min_us": 0.0,
            "median_us": 0.0,
            "p95_us": 0.0,
            "p99_us": 0.0,
            "std_us": 0.0,
            "samples": 0,
        }
    return {
        "min_us": float(us_arr.min()),
        "median_us": float(np.median(us_arr)),
        "p95_us": float(np.percentile(us_arr, 95)),
        "p99_us": float(np.percentile(us_arr, 99)),
        "std_us": float(us_arr.std()),
        "samples": int(us_arr.size),
    }


def _build_probe_body(payload_size_bytes: int) -> Dict[str, Any]:
    """*_build_probe_body()* build a `SvcReq.model_dump()` body for the vernier probes.

    Called once before each timed loop so payload generation does not enter the RTT brackets. The same dict is reused for every request inside the loop.

    Args:
        payload_size_bytes (int): declared payload size; produces a real ASCII blob of exactly that length.

    Returns:
        dict: serialised `SvcReq` ready to pass to `httpx.AsyncClient.post(json=...)`.
    """
    _payload = generate_payload(kind="ping",
                                size_bytes=int(payload_size_bytes))
    _req = SvcReq(kind="ping",
                  size_bytes=int(payload_size_bytes),
                  payload=_payload.to_dict())
    return _req.model_dump()


async def measure_loopback(port: int,
                           samples: int,
                           warmup: int) -> Dict[str, float]:
    """*measure_loopback()* round-trip latency of a vernier `POST /invoke`.

    Uses one `httpx.AsyncClient` with keep-alive so we measure steady-state loopback (TCP handshake excluded). The `SvcReq` body is built once before the timed loop so payload generation never enters the RTT brackets. All timings in `perf_counter_ns`.

    Args:
        port (int): port the vernier server is listening on.
        samples (int): request count after warmup.
        warmup (int): discard-this-many requests before timing.

    Returns:
        dict: min_us / median_us / p95_us / p99_us / std_us / samples.
    """
    _url = "/invoke"
    _base = f"http://127.0.0.1:{port}"
    # build the request body once outside the timed loop so payload generation never enters the RTT brackets
    _body = _build_probe_body(_DEFAULT_PAYLOAD_SIZE_BYTES)
    _rtts: List[int] = []
    # serial loopback; cap the pool at 1 to avoid accidental concurrency
    _limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
    async with httpx.AsyncClient(base_url=_base, limits=_limits) as _client:
        for _ in range(int(warmup)):
            await _client.post(_url, json=_body)
        for _ in range(int(samples)):
            _t1 = time.perf_counter_ns()
            await _client.post(_url, json=_body)
            _t2 = time.perf_counter_ns()
            _rtts.append(_t2 - _t1)
    _arr = np.asarray(_rtts, dtype=np.int64)
    _us = _arr / 1000.0
    return _stats_from_us_array(_us)


async def _run_concurrent_worker(client: httpx.AsyncClient,
                                 url: str,
                                 n: int,
                                 body: Dict[str, Any]) -> List[int]:
    """*_run_concurrent_worker()* one task; issues `n` sequential POSTs of `body` and returns the per-request RTT in nanoseconds.

    Transient connection errors (ReadError, ConnectionError, OSError, etc.) are swallowed so a single dropped connection at high `n_con_usr` does not abort the whole `asyncio.gather` cascade. The caller's stats reflect successful samples only; the dropped count surfaces via the per-level `samples` figure being below the requested total.
    """
    _out: List[int] = []
    for _ in range(int(n)):
        _t1 = time.perf_counter_ns()
        try:
            await client.post(url, json=body)
        except (httpx.HTTPError, ConnectionError, OSError):
            continue
        _t2 = time.perf_counter_ns()
        _out.append(_t2 - _t1)
    return _out


async def measure_handler_scaling(port: int,
                                  n_con_usr: Tuple[int, ...],
                                  warmup: int,
                                  per_worker: Optional[int] = None,
                                  samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
                                  inter_level_delay_s: float = _DEFAULT_INTER_LEVEL_DELAY_S,
                                  on_level_start: Optional[Any] = None,
                                  on_level_done: Optional[Any] = None) -> Dict[str, Dict[str, float]]:
    """*measure_handler_scaling()* loopback latency at increasing concurrent-user load levels.

    For each `n_con_usr` (concurrent in-flight requests from the calibration client) in the ladder, launches `n_con_usr` concurrent workers each doing a derived number of sequential requests against the single-worker (`c_srv=1`) calibration service, aggregates the latency distribution. Quantifies how the FastAPI / event-loop stack's response time grows as in-flight user requests stack up on the vernier handler.

    `n_con_usr` is the CLIENT-side concurrency knob; the SERVICE-side parallelism `c_srv` stays fixed at 1 (one uvicorn worker, one handler). The two must not be conflated.

    When `per_worker` is not supplied, each level targets `samples_per_level` total samples and sets `per_worker = max(1, samples_per_level // n_usr)`. This keeps per-level wall time bounded even at `n_usr = 10_000`, where a naive fixed `per_worker=200` would issue 2 million requests for one level.

    Args:
        port (int): port the vernier server is listening on.
        n_con_usr (tuple[int, ...]): concurrent-user load levels to test (e.g. 1, 10, 50, 100).
        warmup (int): discard-this-many requests (total, not per-worker) upfront.
        per_worker (Optional[int]): sequential requests per concurrent worker. When `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived; ignored when `per_worker` is given explicitly.
        on_level_start (Optional[callable]): invoked with `(n_con_usr, total_samples)` before each level starts.
        on_level_done (Optional[callable]): invoked with `(n_con_usr, stats_dict, elapsed_s)` after each level finishes.

    Returns:
        dict[str, dict]: `{"<n_con_usr>": {min_us, median_us, p95_us, p99_us, std_us, samples}}`.
    """
    _url = "/invoke"
    _base = f"http://127.0.0.1:{port}"
    # build the request body once outside the timed loop so payload generation never enters the RTT brackets
    _body = _build_probe_body(_DEFAULT_PAYLOAD_SIZE_BYTES)
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
            await _client.post(_url, json=_body)
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
                _tasks.append(_run_concurrent_worker(_client, _url, _reqs, _body))
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
            _key = str(_count)
            _stats = _stats_from_us_array(_us)
            _result[_key] = _stats
            if on_level_done is not None:
                _elapsed = time.perf_counter() - _t0
                on_level_done(_count, _stats, _elapsed)
            # release per-level buffers before the next level allocates
            del _all, _arr, _us, _tasks, _lists
            gc.collect()
            # quiet window between levels: lets uvicorn drain TCP backlog + tail responses
            if inter_level_delay_s > 0.0:
                await asyncio.sleep(float(inter_level_delay_s))
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
        print("  [4/4] vernier handler scaling ...", flush=True)


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

    Returns the per-scheduler-tick **send batch size** (NOT the M/M/c/K system capacity). At a given target rate, the client wakes on a `_TARGET_TICK_S` cadence and fires `batch` back-to-back requests per wake to amortise per-iteration overhead. Reported in the rate-sweep banner so the operator can correlate any rate loss with batch behaviour.

    Args:
        rate (float): target rate in req/s.

    Returns:
        int: batch = round(_TARGET_TICK_S / interarrival), clamped to >= 1.
    """
    if rate <= 0:
        return 1
    _interarrival = 1.0 / rate
    _batch = int(round(_TARGET_TICK_S / _interarrival))
    return max(1, _batch)


def _summarise_rate_trial_from_stats(rate: float,
                                     stats: Dict[str, float],
                                     window_s: float) -> Dict[str, float]:
    """*_summarise_rate_trial_from_stats()* compute trial summary from a `_drive_lambda_step` result.

    `samples` (int) is the count of completed `POST /invoke` requests in the probe window. Achieved rate = samples / window_s. Loss is the gap fraction relative to target.

    Args:
        rate (float): target rate driven in this trial (req/s).
        stats (Dict[str, float]): one entry from `_drive_lambda_step` (handler_scaling-shaped).
        window_s (float): wall-clock window the probe ran for (seconds).

    Returns:
        Dict[str, float]: `target / effective / gap / loss_pct`.
    """
    _samples = float(stats.get("samples", 0.0))
    if window_s > 0:
        _eff = _samples / window_s
    else:
        _eff = 0.0
    _target = float(rate)
    _gap = _target - _eff
    if rate > 0:
        _loss = _gap / rate * 100.0
    else:
        _loss = 0.0
    return {
        "target": _target,
        "effective": _eff,
        "gap": _gap,
        "loss_pct": _loss,
    }


def _aggregate_rate_trials(trials: List[Dict[str, float]]
                           ) -> Dict[str, float]:
    """*_aggregate_rate_trials()* summarise N per-trial records at one target rate.

    Args:
        trials (List[Dict]): per-trial summaries from `_summarise_rate_trial_from_stats`.

    Returns:
        Dict[str, float]: `target / mean / lo / hi / mean_loss_pct / n`. The legacy `mean_entry_lambda` field was dropped when the rate-sweep moved off the TAS profile to the standalone ping/echo vernier (no entry artifact to read).
    """
    _effs: List[float] = []
    for _t in trials:
        _effs.append(float(_t["effective"]))
    _n = len(_effs)
    if _n == 0:
        return {
            "target": 0.0,
            "mean": 0.0,
            "lo": 0.0,
            "hi": 0.0,
            "mean_loss_pct": 0.0,
            "n": 0,
        }
    _mean = sum(_effs) / _n
    _lo = min(_effs)
    _hi = max(_effs)
    _target = float(trials[0]["target"])
    if _target > 0:
        _mean_loss = (_target - _mean) / _target * 100.0
    else:
        _mean_loss = 0.0
    return {
        "target": _target,
        "mean": _mean,
        "lo": _lo,
        "hi": _hi,
        "mean_loss_pct": _mean_loss,
        "n": _n,
    }


def _print_rate_header(rate: float) -> None:
    """*_print_rate_header()* one-line banner per rate (target, interarrival, send batch). The reported `batch` is the send-batch size per scheduler tick (NOT the M/M/c/K system capacity)."""
    _interarrival_ms = 1000.0 / rate
    _batch = _batch_size_for(rate)
    print(f"--- target rate {rate:>6.1f} req/s  "
          f"(interarrival {_interarrival_ms:.2f} ms, batch={_batch}) ---",
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


async def _run_rate_sweep_async(rates: List[float],
                                trials_per_rate: int,
                                window_s: float,
                                inter_trial_delay_s: float,
                                port: int,
                                payload_size_bytes: int,
                                ready_timeout_s: float,
                                verbose: bool) -> Dict[float, List[Dict[str, float]]]:
    """*_run_rate_sweep_async()* spin up one vernier and drive it across rates x trials.

    Single uvicorn instance reused across the whole sweep (much cheaper than the legacy TAS-coupled path that re-spawned 13 services per trial). Each trial calls `_drive_lambda_step(rate, window_s)` and converts the returned `samples` count into an achieved rate.

    Args:
        rates (List[float]): target rates (req/s) to drive.
        trials_per_rate (int): trials per rate.
        window_s (float): wall-clock window per trial.
        inter_trial_delay_s (float): quiet seconds between rates (skipped before the first rate).
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        verbose (bool): when True, print per-rate banners + aggregate lines.

    Returns:
        Dict[float, List[Dict[str, float]]]: `{rate: [trial_summary, ...]}` keyed by target rate.
    """
    _trials_by_rate: Dict[float, List[Dict[str, float]]] = {}
    _app = _build_ping_app()
    _server = _UvicornThread(_app, port)
    _server.start()
    try:
        _server.wait_ready(timeout_s=ready_timeout_s)
        _body = _build_probe_body(payload_size_bytes)
        for _r_idx, _rate in enumerate(rates):
            if _r_idx > 0 and inter_trial_delay_s > 0.0:
                await asyncio.sleep(inter_trial_delay_s)
            if verbose:
                print()
                _print_rate_header(_rate)
            _trials: List[Dict[str, float]] = []
            for _trial in range(int(trials_per_rate)):
                _stats = await _drive_lambda_step(port=port,
                                                  target_rate=float(_rate),
                                                  window_s=float(window_s),
                                                  body=_body)
                _summary = _summarise_rate_trial_from_stats(_rate, _stats, window_s)
                _trials.append(_summary)
            _trials_by_rate[_rate] = _trials
    finally:
        _server.shutdown()
    return _trials_by_rate


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
                   trials_per_rate: int = _DEFAULT_RATE_SWEEP_TRIALS,
                   max_probe_s: float = _DEFAULT_RATE_SWEEP_PROBE_S,
                   target_loss_pct: float = _DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                   calibrate: bool = False,
                   inter_trial_delay_s: float = _DEFAULT_INTER_TRIAL_DELAY_S,
                   port: int = _DEFAULT_PORT,
                   payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
                   ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
                   verbose: bool = True) -> Dict[str, Any]:
    """*run_rate_sweep()* drive the standalone vernier ping/echo service at N target rates, `trials_per_rate` trials each.

    The sweep characterises pure host-transport saturation: how fast the host's loopback + uvicorn + FastAPI stack sustains traffic, with zero application logic in the way. One vernier instance is reused across the whole sweep (decoupled from the TAS profile entirely). Replaces the legacy TAS-coupled path that re-spawned 13 services per trial; full-mesh saturation testing now belongs in the experiment notebook itself.

    When `calibrate=True`, additionally reports the highest rate whose mean loss is at or below `target_loss_pct` across all trials.

    Args:
        rates (tuple[float, ...]): target rates (req/s) to drive.
        trials_per_rate (int): trials per rate for aggregation.
        max_probe_s (float): wall-clock window per trial (seconds). Achieved rate = samples / max_probe_s.
        target_loss_pct (float): pass bar for the `calibrate` result.
        calibrate (bool): when True, include the highest-sustainable-rate finding in the result.
        inter_trial_delay_s (float): quiet seconds between rates (skipped before the first rate).
        port (int): TCP port for the vernier.
        payload_size_bytes (int): per-request body size for the probe.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        verbose (bool): when True, print per-rate banners + aggregate lines; False stays silent.

    Returns:
        dict: `{rates, trials_per_rate, max_probe_window_s, target_loss_pct, aggregates, per_trial, calibrated_rate (if calibrate), elapsed_s}`. The legacy `adaptation`, `entry_service`, `cascade`, `min_samples_per_kind`, `mean_entry_lambda`, `lambda_z_at_entry` fields were removed when the sweep moved off the TAS profile.
    """
    _t0 = time.perf_counter()
    _rates_list: List[float] = sorted(set(float(_r) for _r in rates))

    async def _orchestrator() -> Dict[float, List[Dict[str, float]]]:
        return await _run_rate_sweep_async(
            rates=_rates_list,
            trials_per_rate=int(trials_per_rate),
            window_s=float(max_probe_s),
            inter_trial_delay_s=float(inter_trial_delay_s),
            port=int(port),
            payload_size_bytes=int(payload_size_bytes),
            ready_timeout_s=float(ready_timeout_s),
            verbose=bool(verbose),
        )

    _trials_by_rate = _run_sweep_in_dedicated_loop(_orchestrator)

    _aggregates: Dict[float, Dict[str, float]] = {}
    _per_trial: Dict[float, List[Dict[str, float]]] = {}
    for _rate in _rates_list:
        _trials = _trials_by_rate.get(_rate, [])
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

    _ans: Dict[str, Any] = {
        "rates": _rates_list,
        "trials_per_rate": int(trials_per_rate),
        "max_probe_window_s": float(max_probe_s),
        "target_loss_pct": float(target_loss_pct),
        "aggregates": _aggregates_json,
        "per_trial": _per_trial_json,
        "elapsed_s": _elapsed,
    }
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
                            inter_level_delay_s: float = _DEFAULT_INTER_LEVEL_DELAY_S,
                            on_phase_start: Optional[Any] = None,
                            on_level_start: Optional[Any] = None,
                            on_level_done: Optional[Any] = None) -> Dict[str, Any]:
    """*_run_async_probes()* drive the loopback + handler-scaling probes against a uvicorn thread.

    Args:
        port (int): port the vernier server binds to.
        loopback_samples (int): request count for the loopback probe.
        loopback_warmup (int): warmup POSTs discarded upfront.
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
            inter_level_delay_s=inter_level_delay_s,
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
        rate_sweep_trials: int = _DEFAULT_RATE_SWEEP_TRIALS,
        rate_sweep_max_probe_s: float = _DEFAULT_RATE_SWEEP_PROBE_S,
        rate_sweep_target_loss_pct: float = _DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
        rate_sweep_calibrate: bool = True,
        payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
        inter_level_delay_s: float = _DEFAULT_INTER_LEVEL_DELAY_S,
        inter_trial_delay_s: float = _DEFAULT_INTER_TRIAL_DELAY_S,
        write: bool = True,
        output: Optional[str] = None,
        verbose: bool = True) -> Dict[str, Any]:
    """*run()* collect the calibration envelope.

    Runs the four host-floor probes (timer, jitter, loopback, handler scaling) under `_windows_timer_resolution(1)`. When `skip_rate_sweep=False`, additionally runs `run_rate_sweep(...)` and merges the result under the envelope's `rate_sweep` key. When `write=True`, the JSON is persisted under `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json` (or `output` when given) and the resolved path is recorded on the envelope as `output_path`.

    Args:
        timer_samples (int): back-to-back `perf_counter_ns` reads for the timer probe.
        jitter_samples (int): 1 ms sleep cycles for the jitter probe.
        loopback_samples (int): POST /invoke samples for the loopback probe.
        loopback_warmup (int): warmup POSTs discarded before the loopback probe.
        n_con_usr (tuple[int, ...]): concurrent-user load levels (in-flight requests) for the handler-scaling probe.
        per_worker (Optional[int]): sequential requests per concurrent worker; when `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per `n_con_usr` level when `per_worker` is derived.
        port (int): loopback vernier server port.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        skip_jitter (bool): if True, skip the jitter probe.
        skip_loopback (bool): if True, skip both the loopback and handler-scaling probes.
        skip_rate_sweep (bool): if True (default from config), skip the rate-saturation probe; set to False to opt in.
        rate_sweep_rates (tuple[float, ...]): target rates (req/s) for the rate-sweep probe.
        rate_sweep_trials (int): trials per rate for rate-sweep aggregation.
        rate_sweep_max_probe_s (float): rate-sweep wall-clock window per trial (seconds).
        rate_sweep_target_loss_pct (float): pass bar for the rate-sweep `calibrated_rate`.
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
                inter_level_delay_s=inter_level_delay_s,
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
            trials_per_rate=rate_sweep_trials,
            max_probe_s=rate_sweep_max_probe_s,
            target_loss_pct=rate_sweep_target_loss_pct,
            calibrate=rate_sweep_calibrate,
            inter_trial_delay_s=inter_trial_delay_s,
            port=port,
            payload_size_bytes=payload_size_bytes,
            ready_timeout_s=ready_timeout_s,
            verbose=verbose,
        )

    # Route-B dimensional card from measured handler_scaling + loopback; phi stays NaN when payload_size_bytes=0
    if ("handler_scaling" in _envelope) and ("loopback" in _envelope):
        _dim_card = derive_calib_coefs(_envelope,
                                       payload_size_bytes=payload_size_bytes)
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
                    help=("POST /invoke samples for the loopback probe "
                          f"(default: {_DEFAULT_LOOPBACK_SAMPLES})"))
    _p.add_argument("--loopback-warmup", type=int,
                    default=_DEFAULT_LOOPBACK_WARMUP,
                    help=("warmup POSTs discarded before the loopback probe "
                          f"(default: {_DEFAULT_LOOPBACK_WARMUP})"))
    _default_n_con_usr_csv = ",".join(str(_c) for _c in _DEFAULT_N_CON_USR)

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
                    help=("loopback vernier server port "
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
    _default_rates_csv = ",".join(str(_r) for _r in _DEFAULT_RATE_SWEEP_RATES)

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
    _p.add_argument("--rate-sweep-trials", type=int,
                    default=_DEFAULT_RATE_SWEEP_TRIALS,
                    help=("trials per rate for rate-sweep aggregation "
                          f"(default: {_DEFAULT_RATE_SWEEP_TRIALS})"))
    _p.add_argument("--rate-sweep-target-loss", type=float,
                    default=_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                    help=("pass bar (percent) for the calibrated "
                          "highest-sustainable rate "
                          f"(default: {_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT})"))

    _p.add_argument("--payload-size-bytes", type=int,
                    default=_DEFAULT_PAYLOAD_SIZE_BYTES,
                    help=("per-request body size for the dimensional card's "
                          "phi coefficient (bytes); 0 leaves phi NaN "
                          f"(default: {_DEFAULT_PAYLOAD_SIZE_BYTES})"))

    _p.add_argument("--output", type=str, default=None,
                    help=("override the output path; default is "
                          "data/results/experiment/calibration/<host>_<date>.json"))
    return _p


# Route-B dimensional card; shape matches src.view.plot_yoly_chart
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
    # X = n / R
    _x = _n_np / _r_safe
    # steady-state arrival = throughput
    _lam = _x
    # Little's law: L = X*R = n at the level
    _l_load = _n_np
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


# calibration-artifact variable schema; M_{a<tag>}/M_{b<tag>} chosen because sympy parses MA_{X} as M*A and breaks aliases; q-suffixed and nested-brace forms (Lq, Wq, M_{act_{X}}) excluded for the same parser reason
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

    # explicit base-variable LaTeX expressions; no Pi-group indices so robust against Buckingham ordering shifts
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
         f"\\frac{{{_lam}*{_W}}}{{{_K}}}",
         (_lam, _W, _K)),
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
        # Coefficient.__post_init__ resets var_dims when _dim_col is empty; populate after construction so MCS accepts it
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
    # silence 0/0 RuntimeWarning when payload=0; downstream forces NaN regardless
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
                       tag: str = _CALIB_DIM_TAG,
                       K_values: Optional[List[int]] = None) -> Dict[str, Any]:
    """*derive_calib_coefs()* build the dimensional card from a calibration envelope using PyDASA.

    Routes the measured `handler_scaling` + `loopback` arrays through the PyDASA pipeline (Variable dicts -> Schema -> AnalysisEngine -> derive_coefs -> MonteCarloSimulation in DATA mode) so theta / sigma / eta / phi are computed by PyDASA's symbolic evaluator, not by hand-rolled arithmetic. Coefficient symbols carry the `_{<tag>}` subscript (default `_{CALIB}`).

    Route B semantics: coefficients are derived from measurements, not from an M/M/c/K prediction. Applies only when both `handler_scaling` and `loopback` are present in the envelope; returns an empty dict otherwise.

    When `K_values` is supplied, the per-`n_con_usr` observables are tiled once per K so the resulting coefficient arrays span the full (n_con_usr, K) cartesian — gives `plot_yoly_chart` multiple K-trajectories instead of a single point. Latency `R(n)` is independent of K (the host probe doesn't manipulate the buffer), so tiling is exact: only `theta = L/K`, `sigma = lambda*W/K`, and `phi = M_act/M_buf` shift across K.

    Args:
        envelope (Dict[str, Any]): calibration envelope (e.g. from `run()` or `load_latest_calibration()`).
        payload_size_bytes (int): body size per request for the phi coefficient; 0 marks phi as NaN to flag the degenerate 0/0 memory case.
        tag (str): LaTeX-subscript tag used in output keys. Default `CALIB`.
        K_values (Optional[List[int]]): K capacities to span. When None, falls back to a single K = `args.uvicorn_backlog` (legacy single-point card). When provided, output arrays have length `len(handler_scaling) * len(K_values)`.

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

    if K_values is None:
        _K_list = [_backlog]
    else:
        _K_list = [int(_k) for _k in K_values]
        if not _K_list:
            _K_list = [_backlog]

    _obs = _build_calib_observables(
        handler_scaling=_handler,
        loopback=_loop,
        payload_size_bytes=payload_size_bytes,
        uvicorn_backlog=_K_list[0],
        c_srv=1,
    )

    if int(_obs["n"].size) == 0:
        return {}

    # tile every per-n array K_count times so each K block spans every n_con_usr level; K + M_buf rebuilt directly from K_list because they're the only quantities that vary across K
    _N_n = int(_obs["n"].size)
    _N_K = len(_K_list)
    if _N_K > 1:
        _obs_tiled: Dict[str, np.ndarray] = {}
        for _key, _val in _obs.items():
            if _key in ("K", "M_buf"):
                continue
            _obs_tiled[_key] = np.tile(np.asarray(_val, dtype=float), _N_K)
        _K_full = np.repeat(np.asarray(_K_list, dtype=float), _N_n)
        _obs_tiled["K"] = _K_full
        _d_kB = float(payload_size_bytes) / 1000.0
        _obs_tiled["M_buf"] = _K_full * _d_kB
        _obs = _obs_tiled

    _n_levels = int(_obs["n"].size)

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
        "K_values": _K_list,
        "payload_size_bytes": int(payload_size_bytes),
        "n_con_usr": [int(_n) for _n in np.asarray(_obs["n"], dtype=float).tolist()],
        "pipeline": "pydasa.MonteCarloSimulation(mode=DATA)",
    }
    _coefs["meta"] = _meta
    return _coefs


# ---------------------------------------------------------------------------
# Route-B measured sweep: drive vernier across (c, K, mu_factor) cartesian
# ---------------------------------------------------------------------------


def _build_vernier_app_for_combo(c_srv: int,
                                 K: int,
                                 mu: float,
                                 epsilon: float,
                                 payload_size_bytes: int,
                                 tag: str) -> FastAPI:
    """*_build_vernier_app_for_combo()* sibling of `_build_ping_app` with explicit per-combo knobs.

    The host-floor app reads `sweep_grid.{c, K}[0]` and forces `mu = epsilon = 0`. The sweep needs to override every knob per combo, so this helper accepts them as arguments instead.

    Args:
        c_srv (int): per-combo server-side parallel handlers (M/M/c/K c).
        K (int): per-combo system capacity.
        mu (float): per-combo service rate in req/s.
        epsilon (float): per-combo Bernoulli failure rate.
        payload_size_bytes (int): request body size echoed end-to-end.
        tag (str): SvcSpec.name used as the LaTeX subscript on every CSV row.

    Returns:
        FastAPI: app with `/healthz` and `/invoke`.
    """
    _spec = SvcSpec(name=tag,
                    role="atomic",
                    port=int(_DEFAULT_PORT),
                    mu=float(mu),
                    epsilon=float(epsilon),
                    c=int(c_srv),
                    K=int(K),
                    seed=0,
                    mem_per_buffer=int(payload_size_bytes * K * SvcSpec.MEM_HEADROOM_FACTOR))
    _app = make_base_app(f"calibration-vernier::{tag}")
    mount_vernier_svc(_app, _spec, payload_size_bytes=payload_size_bytes)
    return _app


def _resolve_mu_anchor(envelope: Dict[str, Any],
                       sweep_grid: Dict[str, Any]) -> Tuple[float, str]:
    """*_resolve_mu_anchor()* pick the per-combo `mu = mu_factor * anchor` baseline from JSON config.

    Resolution order: explicit `sweep_grid.mu_anchor_req_per_s` (absolute, host-independent) -> named `sweep_grid.mu_anchor_source` (currently only `"loopback.median_us"`) -> default `"loopback.median_us"`. Returns a (value, source-tag) pair so the caller can record provenance on every combo's `meta` block.

    Args:
        envelope (Dict[str, Any]): host calibration envelope; consulted only when the source is `"loopback.median_us"`.
        sweep_grid (Dict[str, Any]): sweep grid (already resolved with config fallback).

    Returns:
        Tuple[float, str]: `(mu_anchor_req_per_s, source_tag)`. `source_tag` is `"explicit"` when `mu_anchor_req_per_s` was supplied, else the named source. Returns `(0.0, source_tag)` when the named source cannot be derived.
    """
    _explicit = sweep_grid.get("mu_anchor_req_per_s")
    if _explicit is not None:
        return float(_explicit), "explicit"
    _src = str(sweep_grid.get("mu_anchor_source", "loopback.median_us"))
    if _src == "loopback.median_us":
        _loop = envelope.get("loopback") or {}
        _r_us = float(_loop.get("median_us", 0.0))
        if _r_us <= 0.0:
            return 0.0, _src
        return 1e6 / _r_us, _src
    return 0.0, _src


async def _post_one(client: httpx.AsyncClient,
                    body: Dict[str, Any],
                    rtts_ns: List[int]) -> None:
    """*_post_one()* one POST `/invoke`; bracket the call with `perf_counter_ns` and append to the shared list."""
    _t1 = time.perf_counter_ns()
    try:
        await client.post("/invoke", json=body)
        rtts_ns.append(time.perf_counter_ns() - _t1)
    except (httpx.HTTPError, ConnectionError, OSError):
        # silent skip; the caller's stats reflect successful samples only
        pass


async def _drive_lambda_step(port: int,
                             target_rate: float,
                             window_s: float,
                             body: Dict[str, Any]) -> Dict[str, float]:
    """*_drive_lambda_step()* return latency stats after firing at `target_rate` for `window_s`.

    Follows the absolute-deadline recipe documented in `.claude/skills/develop/async-rate-precision.md`: every request anchors on `_start + idx * interarrival` so the actual arrival rate tracks the target across the window. Each request runs as its own task; observed latencies reflect concurrent in-flight, not serialised arrivals.

    Args:
        port (int): vernier server port.
        target_rate (float): target arrivals per second; scheduling anchor.
        window_s (float): wall-clock probe window in seconds.
        body (Dict[str, Any]): pre-built `SvcReq.model_dump()` reused per request.

    Returns:
        Dict[str, float]: percentile stats keyed identically to a `handler_scaling[<level>]` entry.
    """
    _interarrival = 1.0 / max(float(target_rate), 1e-6)
    _base = f"http://127.0.0.1:{port}"
    _rtts_ns: List[int] = []
    _limits = httpx.Limits(max_connections=4096, max_keepalive_connections=4096)
    _timeout = httpx.Timeout(_DEFAULT_HTTPX_TIMEOUT_S)
    async with httpx.AsyncClient(base_url=_base,
                                 limits=_limits,
                                 timeout=_timeout) as _client:
        _start = time.perf_counter()
        _deadline = _start + float(window_s)
        _idx = 0
        _tasks: List[asyncio.Task[None]] = []
        while True:
            _now = time.perf_counter()
            if _now >= _deadline:
                break
            _target_t = _start + _idx * _interarrival
            _wait = _target_t - _now
            if _wait > 0:
                await asyncio.sleep(_wait)
            _tasks.append(asyncio.create_task(
                _post_one(_client, body, _rtts_ns)))
            _idx += 1
        # drain any in-flight tasks before the client closes
        if _tasks:
            await asyncio.gather(*_tasks, return_exceptions=True)

    if not _rtts_ns:
        return _stats_from_us_array(np.asarray([], dtype=np.float64))
    _us = np.asarray(_rtts_ns, dtype=np.int64) / 1000.0
    return _stats_from_us_array(_us)


async def _drive_one_combo(c_srv: int,
                           K: int,
                           mu_combo: float,
                           lambda_steps: int,
                           lambda_factor_min: float,
                           util_threshold: float,
                           probe_window_s: float,
                           payload_size_bytes: int,
                           tag: str,
                           port: int,
                           lambda_min_req_per_s: Optional[float] = None,
                           lambda_max_req_per_s: Optional[float] = None,
                           ) -> Dict[str, Dict[str, float]]:
    """*_drive_one_combo()* stand up vernier with the combo spec, ramp lambda, return synthetic handler_scaling.

    Each lambda step keys the result by `int(round(target_rate * window_s))` (the count of arrivals dispatched in the probe window), so downstream `derive_calib_coefs` can read `n` per level the same way it reads `n_con_usr` from the host-floor block. Uvicorn lifecycle is fully contained: spawn, ready-poll, drive, shutdown.

    Ramp endpoints clamp to the absolute accuracy band when `lambda_min_req_per_s` / `lambda_max_req_per_s` are supplied. Combos whose `mu*c` cannot reach the lower bound (clamped band collapses) skip with an empty result so the orchestrator can warn and move on.

    Args:
        c_srv (int): server-side parallelism (M/M/c/K c) for THIS combo.
        K (int): system capacity for THIS combo.
        mu_combo (float): service rate (req/s) for THIS combo.
        lambda_steps (int): number of lambda points in the ramp.
        lambda_factor_min (float): start of the ramp as a fraction of `mu_combo` (e.g. 0.05 -> 5%).
        util_threshold (float): end of the ramp as a fraction of `mu_combo * c_srv` (e.g. 0.95 -> stops below saturation).
        probe_window_s (float): wall-clock window per lambda step.
        payload_size_bytes (int): per-request body size; drives `phi`.
        tag (str): combo's LaTeX-subscript artifact name; encoding `CALIBc<c>K<K>m<int(mu_factor*100)>` (e.g. `CALIBc2K100m150` for `mu_factor=1.5`). Axes are concatenated without dots or underscores because sympy's LaTeX parser treats `.` as multiplication and `_` as a nested subscript marker.
        port (int): TCP port for this combo's uvicorn (caller picks dynamically).
        lambda_min_req_per_s (Optional[float]): absolute lower clamp on the ramp; when set, `_lam_lo = max(lambda_factor_min*mu, lambda_min_req_per_s)`.
        lambda_max_req_per_s (Optional[float]): absolute upper clamp on the ramp; when set, `_lam_hi = min(util_threshold*mu*c, lambda_max_req_per_s)`.

    Returns:
        Dict[str, Dict[str, float]]: synthetic handler_scaling block, one entry per lambda step. Empty when the clamped band collapses (`_lam_hi <= _lam_lo`).
    """
    _app = _build_vernier_app_for_combo(c_srv=c_srv,
                                        K=K,
                                        mu=mu_combo, epsilon=0.0,
                                        payload_size_bytes=payload_size_bytes,
                                        tag=tag)
    _server = _UvicornThread(_app, port)
    _server.start()
    _result: Dict[str, Dict[str, float]] = {}
    try:
        _server.wait_ready(timeout_s=_DEFAULT_READY_TIMEOUT_S)
        _body = _build_probe_body(payload_size_bytes)
        _lam_lo = float(lambda_factor_min) * float(mu_combo)
        _lam_hi = float(util_threshold) * float(mu_combo) * float(c_srv)
        # absolute accuracy-band clamps; trims the ramp into [lambda_min, lambda_max] so plotted points stay inside the trustworthy region
        if lambda_min_req_per_s is not None:
            _lam_lo = max(_lam_lo, float(lambda_min_req_per_s))
        if lambda_max_req_per_s is not None:
            _lam_hi = min(_lam_hi, float(lambda_max_req_per_s))
        if _lam_hi <= _lam_lo:
            return _result
        _steps_n = max(int(lambda_steps), 1)
        _lams = np.linspace(_lam_lo, _lam_hi, _steps_n)
        for _lam in _lams:
            _stats = await _drive_lambda_step(port=port,
                                              target_rate=float(_lam),
                                              window_s=float(probe_window_s),
                                              body=_body)
            # key by approximate arrival count so derive_calib_coefs sees an n-shaped axis
            _level = max(int(round(float(_lam) * float(probe_window_s))), 1)
            _result[str(_level)] = _stats
    finally:
        _server.shutdown()
    return _result


def _resolve_sweep_grid(sweep_grid: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """*_resolve_sweep_grid()* pick the explicit grid argument or fall back to JSON config."""
    if sweep_grid is None:
        return dict(_CALIB_CFG.get("sweep_grid", {}))
    return dict(sweep_grid)


def _run_sweep_in_dedicated_loop(orchestrator) -> Dict[str, Dict[str, Any]]:
    """*_run_sweep_in_dedicated_loop()* execute the orchestrator on a fresh thread with its own event loop and return its result.

    Mirrors `_run_probes_in_dedicated_loop` but is generic over the coroutine instead of pinned to `_run_async_probes`. Lets the sweep execute cleanly from a Jupyter cell where the ambient loop would otherwise block.

    Args:
        orchestrator: zero-arg async callable returning the sweep dict.

    Returns:
        Dict[str, Dict[str, Any]]: sweep result.

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
                _result_box[0] = _loop.run_until_complete(orchestrator())
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
    _result_box.clear()
    _error_box.clear()
    gc.collect()
    return _out


def run_calib_sweep(envelope: Dict[str, Any],
                    sweep_grid: Optional[Dict[str, Any]] = None,
                    *,
                    write: bool = True,
                    verbose: bool = True) -> Dict[str, Dict[str, Any]]:
    """*run_calib_sweep()* drive vernier across `(c, K, mu_factor)` and derive the dim card per combo.

    For each combo on `sweep_grid.c x sweep_grid.K x sweep_grid.mu_factor`: spin up a fresh vernier with the combo spec, ramp `lambda` from `lambda_factor_min*mu` up to `util_threshold*mu*c` across `lambda_steps` points, drive each step for `max_probe_window_s` seconds, aggregate latencies into a synthetic `handler_scaling`-shaped block, and feed that to the same derivation pipeline `derive_calib_coefs` uses. Returns nested `{combo_tag: per_combo_card}` matching the shape consumed by `src.view.plot_yoly_chart`. Inter-combo waits read `inter_trial_delay_s` from the same JSON config so port lifecycles are clean.

    Per-combo `mu` resolves through `_resolve_mu_anchor`: explicit `sweep_grid.mu_anchor_req_per_s` first, then named `sweep_grid.mu_anchor_source` (defaults to `"loopback.median_us"`). Provenance is recorded on every per-combo `meta` block so plot legends can show which anchor each combo used.

    Args:
        envelope (Dict[str, Any]): host calibration envelope; carries `loopback.median_us` (used as the default mu anchor) and `host_profile` (for the output path).
        sweep_grid (Optional[Dict[str, Any]]): cartesian grid; falls back to `data/config/method/calibration.json::sweep_grid` when None. Required keys: `mu_factor` (List[float]), `c` (List[int]), `K` (List[int]), `lambda_steps` (int), `lambda_factor_min` (float), `util_threshold` (float). Optional: `mu_anchor_req_per_s` (float), `mu_anchor_source` (str), `max_probe_window_s` (float).
        write (bool): persist the result envelope under `data/results/experiment/calibration/<host>_<ts>_sweep.json`.
        verbose (bool): print one progress line per combo.

    Returns:
        Dict[str, Dict[str, Any]]: nested `{combo_tag: per_combo_card}`. Each per-combo block carries the same keys as `derive_calib_coefs` returns (theta / sigma / eta / phi + c / mu / K / lambda / n_con_usr + meta). Empty dict when the envelope lacks `loopback`, the grid is empty, or the mu anchor cannot be resolved.
    """
    _grid = _resolve_sweep_grid(sweep_grid)
    if not _grid:
        return {}

    _mu_anchor, _mu_source = _resolve_mu_anchor(envelope, _grid)
    if _mu_anchor <= 0.0:
        return {}

    _payload_bytes = int(_DEFAULT_PAYLOAD_SIZE_BYTES)
    _inter_trial_s = float(_DEFAULT_INTER_TRIAL_DELAY_S)
    _probe_window_s = float(_grid.get("max_probe_window_s",
                                      _DEFAULT_RATE_SWEEP_PROBE_S))
    _mu_factors = [float(_v) for _v in _grid.get("mu_factor", [1.0])]
    _cs = [int(_v) for _v in _grid.get("c", [1])]
    _Ks = [int(_v) for _v in _grid.get("K", [50])]
    _lambda_steps = int(_grid.get("lambda_steps", 20))
    _lambda_factor_min = float(_grid.get("lambda_factor_min", 0.05))
    _util_threshold = float(_grid.get("util_threshold", 0.95))
    # absolute accuracy-band clamps (None -> no clamp); JSON keys are optional, default behaviour matches the pre-clamp ramp
    _lambda_min_abs = _grid.get("lambda_min_req_per_s")
    _lambda_max_abs = _grid.get("lambda_max_req_per_s")
    if _lambda_min_abs is not None:
        _lambda_min_abs = float(_lambda_min_abs)
    if _lambda_max_abs is not None:
        _lambda_max_abs = float(_lambda_max_abs)

    _backlog = _DEFAULT_UVICORN_BACKLOG
    _base_port = int(_DEFAULT_PORT)

    async def _orchestrate() -> Dict[str, Dict[str, Any]]:
        _out: Dict[str, Dict[str, Any]] = {}
        _combo_idx = 0
        _total = len(_cs) * len(_Ks) * len(_mu_factors)
        for _c_val in _cs:
            for _K_val in _Ks:
                if _K_val < _c_val:
                    continue
                for _mu_factor in _mu_factors:
                    _combo_idx += 1
                    _mu_combo = float(_mu_factor) * float(_mu_anchor)
                    # collapse axes into one sympy-safe identifier (no dots, no internal underscores; encoding rationale lives on `_drive_one_combo`)
                    _mu_factor_tag = int(round(float(_mu_factor) * 100))
                    _tag = f"CALIBc{_c_val}K{_K_val}m{_mu_factor_tag}"
                    if verbose:
                        print(f"  [{_combo_idx}/{_total}] {_tag} "
                              f"mu={_mu_combo:.1f} req/s ...", flush=True)
                    # one port per combo so consecutive lifecycles do not collide on TIME_WAIT
                    _port = _base_port + _combo_idx
                    _hs = await _drive_one_combo(
                        c_srv=_c_val, K=_K_val, mu_combo=_mu_combo,
                        lambda_steps=_lambda_steps,
                        lambda_factor_min=_lambda_factor_min,
                        util_threshold=_util_threshold,
                        probe_window_s=_probe_window_s,
                        payload_size_bytes=_payload_bytes,
                        tag=_tag, port=_port,
                        lambda_min_req_per_s=_lambda_min_abs,
                        lambda_max_req_per_s=_lambda_max_abs)
                    if not _hs:
                        if verbose:
                            print("      band collapsed (mu*c below lambda_min) -- skipping",
                                  flush=True)
                        continue
                    # synthesise a per-combo envelope; loopback.median_us encodes mu_combo, args.uvicorn_backlog carries the COMBO's K (NOT the host default _backlog) so the per-combo card has K=_K_val and the yoly chart can paint a distinct trajectory per K-band
                    if _mu_combo > 0:
                        _r_us = 1e6 / _mu_combo
                    else:
                        _r_us = 0.0
                    _synth_env = {
                        "handler_scaling": _hs,
                        "loopback": {"median_us": _r_us},
                        "args": {"uvicorn_backlog": int(_K_val)},
                    }
                    _card = derive_calib_coefs(_synth_env,
                                               payload_size_bytes=_payload_bytes,
                                               tag=_tag,
                                               K_values=[int(_K_val)])
                    if not _card:
                        if verbose:
                            print("      empty card -- skipping",
                                  flush=True)
                        continue
                    # overlay combo-specific provenance on the meta block
                    _meta = dict(_card.get("meta", {}))
                    _meta.update({
                        "mu_anchor_req_per_s": float(_mu_anchor),
                        "mu_anchor_source": _mu_source,
                        "mu_factor": float(_mu_factor),
                        "c_srv": int(_c_val),
                        "K_capacity": int(_K_val),
                        "probe_window_s": float(_probe_window_s),
                        "lambda_steps": int(_lambda_steps),
                    })
                    _card["meta"] = _meta
                    _out[_tag] = _card
                    # quiet window between combos: lets uvicorn release the port + TCP TIME_WAIT drain
                    if _combo_idx < _total and _inter_trial_s > 0.0:
                        await asyncio.sleep(_inter_trial_s)
        return _out

    _sweep = _run_sweep_in_dedicated_loop(_orchestrate)

    if write and _sweep:
        _profile = envelope.get("host_profile") or {}
        _path = _build_output_path(_profile)
        _sweep_path = _path.with_name(_path.stem + "_sweep" + _path.suffix)
        _envelope_out: Dict[str, Any] = {
            "host_profile": _profile,
            "mu_anchor_req_per_s": float(_mu_anchor),
            "mu_anchor_source": _mu_source,
            "sweep_grid": _grid,
            "combos": _sweep,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        _write_json(_sweep_path, _envelope_out)
        if verbose:
            print(f"  wrote: {_sweep_path}", flush=True)

    return _sweep


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
        rate_sweep_trials=_args.rate_sweep_trials,
        rate_sweep_target_loss_pct=_args.rate_sweep_target_loss,
        payload_size_bytes=_args.payload_size_bytes,
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
