# -*- coding: utf-8 -*-
"""
calibration.py
==============

Per-host noise-floor characterization for the `experiment` method. Runs four baselines (timer resolution, scheduling jitter, loopback latency, empty-handler scaling) and writes a single JSON envelope to `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`.

Every `experiment` run should reference the latest calibration JSON by timestamp in its run envelope (`baseline_ref`) so measured latencies can be reported as `value - loopback_median +/- jitter_p99`.

Kept deliberately small and dependency-light:

    - ctypes `timeBeginPeriod(1)` is inlined so this module stays free of heavy transitive imports that would warm the executor pool and perturb the measurements.
    - `time.perf_counter_ns()` throughout; integer arithmetic in the hot path, seconds only at JSON-write time.
    - FastAPI `/ping` runs in a background uvicorn thread so the loopback probe measures real TCP loopback, not ASGI in-process shortcuts.

Run::

    python src/scripts/calibration.py
    python src/scripts/calibration.py --timer-samples 50000 --jitter-samples 2000
    python src/scripts/calibration.py --loopback-samples 2000 --concurrency 1,10,50,100
    python src/scripts/calibration.py --skip-loopback  # timer + jitter only

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
import gc
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


# All tunables live in `data/config/method/calibration.json`; this module
# reads them once at import so every entry point (CLI, `run()`, notebook)
# sees the same defaults. Fallbacks are preserved here only for the case
# where the config file is missing or unreadable.
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
_DEFAULT_CONCURRENCY = tuple(_CALIB_CFG.get("concurrency", ()))
# Target sample count per concurrency level. `per_worker` is derived as
# `max(1, samples_per_level // concurrency)` unless the caller overrides
# it, and the aggregated latencies are trimmed to `samples_per_level` so
# every level reports the same number of observations.
_DEFAULT_SAMPLES_PER_LEVEL = int(_CALIB_CFG.get("samples_per_level", 0))
_DEFAULT_PORT = int(_CALIB_CFG.get("port", 8765))
_DEFAULT_READY_TIMEOUT_S = float(_CALIB_CFG.get("ready_timeout_s", 5.0))
_DEFAULT_UVICORN_BACKLOG = int(_CALIB_CFG.get("uvicorn_backlog", 16384))
_DEFAULT_HTTPX_TIMEOUT_S = float(_CALIB_CFG.get("httpx_timeout_s", 0))
_DEFAULT_SKIP_JITTER = bool(_CALIB_CFG.get("skip_jitter", False))
_DEFAULT_SKIP_LOOPBACK = bool(_CALIB_CFG.get("skip_loopback", False))

# sleep() target for the jitter probe, in nanoseconds. Read directly
# from the config in the same unit (ns) used internally by the hot path.
_JITTER_TARGET_NS = int(_CALIB_CFG.get("jitter_target_ns", 1_000_000))


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
            _mem_gb = float(_stat.ullTotalPhys) / (1024 ** 3)
        elif hasattr(os, "sysconf"):
            _pages = os.sysconf("SC_PHYS_PAGES")
            _page_size = os.sysconf("SC_PAGE_SIZE")
            _mem_gb = float(_pages * _page_size) / (1024 ** 3)
    except Exception:
        _mem_gb = None

    _hostname = socket.gethostname()
    _os = platform.platform()
    _py_ver = platform.python_version()
    _py_impl = platform.python_implementation()
    _cpu_count = os.cpu_count()
    _cpu_machine = platform.machine()
    _cpu_processor = platform.processor()
    return {
        "hostname": _hostname,
        "os": _os,
        "python": _py_ver,
        "python_impl": _py_impl,
        "cpu_count": _cpu_count,
        "cpu_machine": _cpu_machine,
        "cpu_processor": _cpu_processor,
        "ram_total_gb": _mem_gb,
    }


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
    return {
        "min_ns": _min,
        "median_ns": _median,
        "mean_ns": _mean,
        "std_ns": _std,
        "zero_frac": _zero_frac,
    }


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
    return {
        "mean_us": _mean,
        "std_us": _std,
        "p50_us": _p50,
        "p99_us": _p99,
        "max_us": _max,
    }


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
        # large accept backlog so the high-concurrency levels (c=5000,
        # c=10000) don't get refused at the kernel socket queue.
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
        raise RuntimeError(f"uvicorn did not become ready within {timeout_s} s")

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
    # loopback is serial so 1 keep-alive connection is enough; explicit
    # Limits still documents intent and avoids accidental pool caps.
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
    return {
        "min_us": _min,
        "median_us": _median,
        "p95_us": _p95,
        "p99_us": _p99,
        "std_us": _std,
        "samples": _n,
    }


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
                                  concurrency: Tuple[int, ...],
                                  warmup: int,
                                  per_worker: Optional[int] = None,
                                  samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
                                  on_level_start: Optional[Any] = None,
                                  on_level_done: Optional[Any] = None) -> Dict[str, Dict[str, float]]:
    """*measure_handler_scaling()* loopback latency at increasing concurrency levels.

    For each level `c`, launches `c` concurrent workers each doing a derived number of sequential requests, aggregates the latency distribution. Quantifies how the FastAPI / event-loop stack's response time grows as in-flight requests stack up on the empty handler.

    When `per_worker` is not supplied, each level targets `samples_per_level` total samples and sets `per_worker = max(1, samples_per_level // c)`. This keeps per-level wall time bounded even at c = 10 000, where a naive fixed `per_worker=200` would issue 2 million requests for one level.

    Args:
        port (int): port the ping server is listening on.
        concurrency (tuple[int, ...]): levels to test (e.g. 1, 10, 50, 100).
        warmup (int): discard-this-many requests (total, not per-worker) upfront.
        per_worker (Optional[int]): sequential requests per concurrent worker. When `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived; ignored when `per_worker` is given explicitly.
        on_level_start (Optional[callable]): invoked with `(level, total_samples)` before each level starts.
        on_level_done (Optional[callable]): invoked with `(level, stats_dict, elapsed_s)` after each level finishes.

    Returns:
        dict[str, dict]: `{"<c>": {min_us, median_us, p95_us, p99_us, std_us, samples}}`.
    """
    _url = "/ping"
    _base = f"http://127.0.0.1:{port}"
    _result: Dict[str, Dict[str, float]] = {}
    # raise httpx's connection pool cap (default 100) so the real
    # concurrency matches the requested level; uvicorn answers over a
    # single /ping route so keep-alive reuse is fine.
    _max_c = 1
    for _c_peek in concurrency:
        if int(_c_peek) > _max_c:
            _max_c = int(_c_peek)
    _limits = httpx.Limits(max_connections=_max_c,
                           max_keepalive_connections=_max_c)
    # long connect + read timeouts because at c=5000-10000 the kernel
    # connect queue drains slowly and per-request latency can be in the
    # seconds; the default 5 s timeout trips before the measurement runs.
    _timeout = httpx.Timeout(_DEFAULT_HTTPX_TIMEOUT_S)
    async with httpx.AsyncClient(base_url=_base,
                                 limits=_limits,
                                 timeout=_timeout) as _client:
        for _ in range(int(warmup)):
            await _client.get(_url)
        for _c in concurrency:
            _count = int(_c)
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
            # Uniform sample size per level so statistics are comparable.
            # At high concurrency the per_worker=1 floor forces total to
            # equal the concurrency level (e.g. c=10000 -> 10000 samples);
            # trim to samples_per_level after gathering so every level
            # contributes the same number of observations while still
            # exercising the requested concurrency in flight. Only trims
            # when per_worker was auto-derived; explicit per_worker keeps
            # the full count.
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
            # release per-level buffers (latency list, numpy arrays,
            # task list) before moving on so the next high-concurrency
            # level doesn't stack its allocations on top of stale ones.
            del _all, _arr, _us, _tasks, _lists
            gc.collect()
    return _result


def _run_probes_in_dedicated_loop(**kwargs: Any) -> Dict[str, Any]:
    """*_run_probes_in_dedicated_loop()* drive `_run_async_probes` on a fresh thread with its own event loop.

    Jupyter (and any ipykernel-based host) installs `SelectorEventLoop` on Windows for tornado compatibility; `select()` on Windows caps at 512 file descriptors, which breaks the high-concurrency scaling probe (c=1000+ needs thousands of sockets). A fresh thread running `ProactorEventLoop` on Windows (IOCP) has no such cap.

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
    # the worker thread owned the event loop, the uvicorn server, and
    # the httpx client; now that the thread has joined, clear the local
    # boxes + force a GC pass so none of the sockets / coroutine state
    # lingers once the caller returns.
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


def _parse_concurrency(arg: str) -> Tuple[int, ...]:
    """*_parse_concurrency()* parse a comma-separated concurrency list.

    Args:
        arg (str): comma-separated concurrency levels, e.g. `"1,10,50,100"`.

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


async def _run_async_probes(*,
                            port: int,
                            loopback_samples: int,
                            loopback_warmup: int,
                            concurrency: Tuple[int, ...],
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
        concurrency (tuple[int, ...]): levels for the handler-scaling probe.
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
            concurrency=concurrency,
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
        concurrency: Tuple[int, ...] = _DEFAULT_CONCURRENCY,
        per_worker: Optional[int] = None,
        samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
        port: int = _DEFAULT_PORT,
        ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
        skip_jitter: bool = _DEFAULT_SKIP_JITTER,
        skip_loopback: bool = _DEFAULT_SKIP_LOOPBACK,
        write: bool = True,
        output: Optional[str] = None,
        verbose: bool = True) -> Dict[str, Any]:
    """*run()* collect the calibration envelope.

    Runs the four probes (timer, jitter, loopback, handler scaling) under `_windows_timer_resolution(1)` and returns the full envelope. When `write=True`, the JSON is persisted under `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json` (or `output` when given) and the resolved path is recorded on the envelope as `output_path`.

    Args:
        timer_samples (int): back-to-back `perf_counter_ns` reads for the timer probe.
        jitter_samples (int): 1 ms sleep cycles for the jitter probe.
        loopback_samples (int): GET /ping samples for the loopback probe.
        loopback_warmup (int): warmup GETs discarded before the loopback probe.
        concurrency (tuple[int, ...]): levels for the handler-scaling probe.
        per_worker (Optional[int]): sequential requests per concurrent worker; when `None`, derived from `samples_per_level`.
        samples_per_level (int): target total samples per concurrency level when `per_worker` is derived.
        port (int): loopback ping server port.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        skip_jitter (bool): if True, skip the jitter probe.
        skip_loopback (bool): if True, skip both the loopback and handler-scaling probes.
        write (bool): persist the envelope to JSON when True.
        output (Optional[str]): override path when `write=True`; defaults to the per-host path.
        verbose (bool): print phase markers to stdout when True.

    Returns:
        dict: the envelope (`host_profile`, `args`, `timer`, `jitter`, `loopback`, `handler_scaling`, `timestamp`, `elapsed_s`, `output_path`).
    """
    _profile = snapshot_host_profile()
    _t0 = time.perf_counter()

    _concurrency_list: List[int] = []
    for _c in concurrency:
        _concurrency_list.append(int(_c))

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
        "concurrency": _concurrency_list,
        "per_worker": _per_worker_record,
        "samples_per_level": int(samples_per_level),
        "port": int(port),
        "skip_jitter": bool(skip_jitter),
        "skip_loopback": bool(skip_loopback),
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
                concurrency=concurrency,
                per_worker=per_worker,
                samples_per_level=samples_per_level,
                ready_timeout_s=ready_timeout_s,
                on_phase_start=_on_phase,
                on_level_start=_on_level_start,
                on_level_done=_on_level_done,
            )
            _envelope.update(_probes)

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

    # final sweep: the probe allocations are gone but interpreter-level
    # caches (httpx module, uvicorn server class) may still hold cycles.
    gc.collect()
    return _envelope


def _build_argparser() -> argparse.ArgumentParser:
    """*_build_argparser()* CLI surface."""
    _p = argparse.ArgumentParser(
        prog="calibration",
        description=("Per-host noise-floor characterization for the "
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
    _default_conc_tokens: List[str] = []
    for _c in _DEFAULT_CONCURRENCY:
        _default_conc_tokens.append(str(_c))
    _default_conc_csv = ",".join(_default_conc_tokens)

    _p.add_argument("--concurrency", type=str, default=None,
                    help=("comma-separated concurrency levels for the "
                          "handler-scaling probe "
                          f"(default: {_default_conc_csv})"))
    _p.add_argument("--per-worker", type=int, default=None,
                    help=("sequential requests per concurrent worker; "
                          "when omitted, derived from --samples-per-level "
                          "so total samples per level stay bounded"))
    _p.add_argument("--samples-per-level", type=int,
                    default=_DEFAULT_SAMPLES_PER_LEVEL,
                    help=("target total samples per concurrency level "
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
    _p.add_argument("--output", type=str, default=None,
                    help=("override the output path; default is "
                          "data/results/experiment/calibration/<host>_<date>.json"))
    return _p


def main(argv: Optional[List[str]] = None) -> None:
    """*main()* CLI entry point; parses `argv` and delegates to `run()`.

    Args:
        argv (Optional[List[str]]): argv override for tests; None uses `sys.argv`.
    """
    _parser = _build_argparser()
    _args = _parser.parse_args(argv)
    if _args.concurrency is not None:
        _concurrency = _parse_concurrency(_args.concurrency)
    else:
        _concurrency = _DEFAULT_CONCURRENCY

    _hostname = socket.gethostname()
    _py_ver = platform.python_version()
    _banner(f"calibration.py  host={_hostname!r}  python={_py_ver}")
    print(f"  timer_samples={_args.timer_samples}  "
          f"jitter_samples={_args.jitter_samples}  "
          f"loopback_samples={_args.loopback_samples}  "
          f"concurrency={_concurrency}")
    print()

    _envelope = run(
        timer_samples=_args.timer_samples,
        jitter_samples=_args.jitter_samples,
        loopback_samples=_args.loopback_samples,
        loopback_warmup=_args.loopback_warmup,
        concurrency=_concurrency,
        per_worker=_args.per_worker,
        samples_per_level=_args.samples_per_level,
        port=_args.port,
        ready_timeout_s=_args.ready_timeout_s,
        skip_jitter=_args.skip_jitter,
        skip_loopback=_args.skip_loopback,
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
