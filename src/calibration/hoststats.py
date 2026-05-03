# -*- coding: utf-8 -*-
"""
Module calibration/hoststats.py
===============================

Host-floor probes that produce the raw observables every calibration envelope carries: timer resolution, asyncio scheduling jitter, loopback round-trip latency, and handler-scaling response under closed-loop concurrency. All four return plain dicts; persistence and dpl-aware path resolution live in `envelope.py`; the sweep-cell halt rules live in `conditionals.py`.

`snapshot_host_profile` captures OS / CPU / RAM / Python identity for envelope provenance using only the Python standard library so it adds no third-party dependency and does not perturb the measurements that follow.

Public API:
    - `snapshot_host_profile()`: host identity for the envelope.
    - `measure_timer(samples)`: clock-resolution stats from back-to-back `perf_counter_ns` reads.
    - `measure_jitter(samples)`: OS oversleep stats around `time.sleep(0.001)`.
    - `measure_loopback(port, samples, warmup, payload_size_bytes)`: vernier RTT stats with one keep-alive client.
    - `measure_handler_scaling(port, n_con_usr, ...)`: per-`n_con_usr` latency stats under closed-loop concurrency.
    - `stats_from_us_array(us_arr)`: canonical 6-key stats dict for a microsecond array.
    - `stats_from_us_status_pairs(pairs)`: success-only stats plus per-status counts for `(rtt_ns, status)` pairs.
"""
# native python modules
from __future__ import annotations

import asyncio
import ctypes
import gc
import os
import platform
import socket
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

# scientific stack
import numpy as np

# web stack
import httpx

# local modules
from src.experiment.services import SvcReq
from src.experiment.wire import generate_payload


# defaults match data/config/method/calibration.json; the orchestrator (Stage C9) passes JSON-loaded values explicitly so production runs never depend on these literals
_DEFAULT_PAYLOAD_SIZE_BYTES = 128000
_DEFAULT_HTTPX_TIMEOUT_S = 60.0
_DEFAULT_SAMPLES_PER_LEVEL = 1024
_DEFAULT_INTER_LEVEL_DELAY_S = 1.0

# nanoseconds the OS sleep is asked to wait so jitter is reported as actual minus requested
_JITTER_TARGET_NS = 1_000_000


def _read_total_ram_gb_windows() -> float:
    """*_read_total_ram_gb_windows()* total physical RAM via Win32 `GlobalMemoryStatusEx`.

    Returns:
        float: total physical RAM in gigabytes.
    """
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
    return float(_stat.ullTotalPhys) / (1024 ** 3)


def _read_total_ram_gb_linux() -> Optional[float]:
    """*_read_total_ram_gb_linux()* total physical RAM via `/proc/meminfo::MemTotal`.

    Returns:
        Optional[float]: total physical RAM in gigabytes, or None when `MemTotal` is absent.
    """
    with open("/proc/meminfo", "r", encoding="utf-8") as _fh:
        for _line in _fh:
            if _line.startswith("MemTotal:"):
                _kb = float(_line.split()[1])
                return _kb / (1024 ** 2)
    return None


def _read_total_ram_gb_macos() -> float:
    """*_read_total_ram_gb_macos()* total physical RAM via `sysctl -n hw.memsize`.

    Returns:
        float: total physical RAM in gigabytes.
    """
    _out = subprocess.check_output(["sysctl",
                                    "-n",
                                    "hw.memsize"],
                                   text=True,
                                   timeout=2.0)
    return float(_out.strip()) / (1024 ** 3)


def snapshot_host_profile() -> Dict[str, Any]:
    """*snapshot_host_profile()* gather OS, CPU, RAM, python identity for envelope provenance.

    Thermal readings are intentionally omitted; run-time conditions (thermals, background load) belong out-of-band via the caller.

    Returns:
        Dict[str, Any]: `{hostname, os, python, python_impl, cpu_count, cpu_machine, cpu_processor, ram_total_gb}`. `ram_total_gb` is None when the OS-specific RAM probe failed.
    """
    _platform: str = sys.platform
    _mem_gb: Optional[float] = None
    try:
        if _platform == "win32":
            _mem_gb = _read_total_ram_gb_windows()
        elif _platform.startswith("linux"):
            _mem_gb = _read_total_ram_gb_linux()
        elif _platform == "darwin":
            _mem_gb = _read_total_ram_gb_macos()
    except (OSError, AttributeError, ValueError, FileNotFoundError,
            subprocess.SubprocessError):
        _mem_gb = None

    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "python_impl": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "cpu_machine": platform.machine(),
        "cpu_processor": platform.processor(),
        "ram_total_gb": _mem_gb,
    }


def measure_timer(samples: int) -> Dict[str, float]:
    """*measure_timer()* clock-resolution stats from back-to-back `perf_counter_ns` reads.

    Zero-delta reads (same tick bucket) are skipped; only positive deltas feed the percentile stats. The minimum positive delta is the host's actual clock resolution; `zero_frac` reports how often two consecutive reads land in the same tick (high `zero_frac` means the timer is too coarse for the workload).

    Args:
        samples (int): number of back-to-back reads to collect.

    Returns:
        Dict[str, float]: `{min_ns, median_ns, mean_ns, std_ns, zero_frac}`. All-zero deltas yield zero stats and `zero_frac == 1.0`.
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
    if _deltas:
        _arr = np.asarray(_deltas, dtype=np.int64)
        _min = int(_arr.min())
        _median = float(np.median(_arr))
        _mean = float(_arr.mean())
        _std = float(_arr.std())
        _zero_frac = float(_zero / samples)
    else:
        _min = 0
        _median = 0.0
        _mean = 0.0
        _std = 0.0
        _zero_frac = 1.0
    return {
        "min_ns": _min,
        "median_ns": _median,
        "mean_ns": _mean,
        "std_ns": _std,
        "zero_frac": _zero_frac,
    }


def measure_jitter(samples: int) -> Dict[str, float]:
    """*measure_jitter()* OS oversleep stats across N samples of `time.sleep(0.001)`.

    Records the difference between the requested 1 ms and the actual elapsed nanoseconds. `max_us` and `p99_us` are the OS-interruption tail; any inter-arrival smaller than those values cannot resolve cleanly.

    Args:
        samples (int): number of sleep cycles to measure.

    Returns:
        Dict[str, float]: `{mean_us, std_us, p50_us, p99_us, max_us}`.
    """
    _jitters: List[int] = []
    for _ in range(int(samples)):
        _t1 = time.perf_counter_ns()
        time.sleep(0.001)
        _t2 = time.perf_counter_ns()
        _jitters.append((_t2 - _t1) - _JITTER_TARGET_NS)
    _arr = np.asarray(_jitters, dtype=np.int64)
    _us = _arr / 1000.0
    return {
        "mean_us": float(_us.mean()),
        "std_us": float(_us.std()),
        "p50_us": float(np.percentile(_us, 50)),
        "p99_us": float(np.percentile(_us, 99)),
        "max_us": float(_us.max()),
    }


def stats_from_us_array(us_arr: np.ndarray) -> Dict[str, float]:
    """*stats_from_us_array()* canonical 6-key latency-stats dict from a microsecond array.

    Single source of truth for the `handler_scaling[<level>]` shape. Reused by `measure_loopback` for single-status paths; `measure_handler_scaling` uses `stats_from_us_status_pairs` instead because it needs success-only filtering plus per-status metadata.

    Args:
        us_arr (np.ndarray): per-request latencies in microseconds; an empty array yields a zero-valued stats dict so callers can short-circuit on `samples == 0`.

    Returns:
        Dict[str, float]: `{min_us, median_us, p95_us, p99_us, std_us, samples}`.
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


def stats_from_us_status_pairs(pairs: List[Tuple[int, int]]) -> Dict[str, float]:
    """*stats_from_us_status_pairs()* success-only latency stats plus per-status counts from `(rtt_ns, status_code)` pairs.

    The dimensional model assumes successful request/reply, so the latency stats are computed over `status == 200` only; fast 503 rejections no longer pull the median down. Raw rejection counts persist as `reject_count` / `reject_rate` / `infra_fail_count` for future error-handler-aware DASA models.

    Args:
        pairs (List[Tuple[int, int]]): `(rtt_ns, status_code)` per request. `status == 0` marks an infra failure (ConnectionError / OSError swallowed at the worker), `status == 503` marks K-overflow rejection, `status == 200` marks successful completion.

    Returns:
        Dict[str, float]: the 6-key stats from `stats_from_us_array` (over success-only) plus `total_count`, `succ_count`, `reject_count`, `infra_fail_count`, `reject_rate`.
    """
    if not pairs:
        return {
            "min_us": 0.0, "median_us": 0.0, "p95_us": 0.0, "p99_us": 0.0,
            "std_us": 0.0, "samples": 0,
            "total_count": 0, "succ_count": 0,
            "reject_count": 0, "infra_fail_count": 0, "reject_rate": 0.0,
        }
    _total = len(pairs)
    _succ_us = [_rtt / 1000.0 for (_rtt, _st) in pairs if _st == 200]
    _reject = sum(1 for (_, _st) in pairs if _st == 503)
    _infra = sum(1 for (_, _st) in pairs if _st == 0)
    _succ_arr = np.asarray(_succ_us, dtype=np.float64)
    _stats = stats_from_us_array(_succ_arr)
    _stats["total_count"] = int(_total)
    _stats["succ_count"] = int(_succ_arr.size)
    _stats["reject_count"] = int(_reject)
    _stats["infra_fail_count"] = int(_infra)
    if _total > 0:
        _stats["reject_rate"] = float(_reject) / float(_total)
    else:
        _stats["reject_rate"] = 0.0
    return _stats


def _build_probe_body(payload_size_bytes: int) -> Dict[str, Any]:
    """*_build_probe_body()* serialised `SvcReq` body for the vernier probes, built once before the timed loop so payload generation never enters the RTT brackets.

    Args:
        payload_size_bytes (int): declared payload size; produces a real ASCII blob of exactly that length.

    Returns:
        Dict[str, Any]: `SvcReq.model_dump()` ready to pass as `httpx.AsyncClient.post(json=...)`.
    """
    _payload = generate_payload(kind="ping",
                                size_bytes=int(payload_size_bytes))
    _req = SvcReq(kind="ping",
                  size_bytes=int(payload_size_bytes),
                  payload=_payload.to_dict())
    return _req.model_dump()


async def measure_loopback(port: int,
                           samples: int,
                           warmup: int,
                           payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES
                           ) -> Dict[str, float]:
    """*measure_loopback()* round-trip latency stats of a vernier `POST /invoke`.

    Uses one `httpx.AsyncClient` with keep-alive so the measurement is steady-state (TCP handshake excluded). All timings via `perf_counter_ns`.

    Args:
        port (int): port the vernier server is listening on.
        samples (int): request count after warmup.
        warmup (int): discard-this-many requests before timing.
        payload_size_bytes (int): body size for the probe; defaults to `_DEFAULT_PAYLOAD_SIZE_BYTES`.

    Returns:
        Dict[str, float]: `{min_us, median_us, p95_us, p99_us, std_us, samples}`.
    """
    _url = "/invoke"
    _base = f"http://127.0.0.1:{port}"
    _body = _build_probe_body(payload_size_bytes)
    _rtts: List[int] = []
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
    return stats_from_us_array(_us)


async def _run_concurrent_worker(client: httpx.AsyncClient,
                                 url: str,
                                 n: int,
                                 body: Dict[str, Any]
                                 ) -> List[Tuple[int, int]]:
    """*_run_concurrent_worker()* fire `n` sequential POSTs of `body` and return `(rtt_ns, status_code)` per request.

    Transient connection errors (httpx.HTTPError, ConnectionError, OSError) are swallowed so a single dropped connection at high `n_con_usr` does not abort the whole `asyncio.gather` cascade; they surface as `(rtt, 0)` so downstream stats can distinguish infra failure (status 0) from K-overflow (status 503) from successful completion (status 200).

    Args:
        client (httpx.AsyncClient): shared client; the caller controls keep-alive limits.
        url (str): relative path under the client's `base_url`.
        n (int): sequential request count.
        body (Dict[str, Any]): pre-built request body reused for every request.

    Returns:
        List[Tuple[int, int]]: per-request `(rtt_ns, status_code)`.
    """
    _out: List[Tuple[int, int]] = []
    for _ in range(int(n)):
        _t1 = time.perf_counter_ns()
        _status = 0
        try:
            _resp = await client.post(url, json=body)
            _status = int(_resp.status_code)
        except (httpx.HTTPError, ConnectionError, OSError):
            _status = 0
        _t2 = time.perf_counter_ns()
        _out.append((_t2 - _t1, _status))
    return _out


async def measure_handler_scaling(port: int,
                                  n_con_usr: Tuple[int, ...],
                                  warmup: int,
                                  per_worker: Optional[int] = None,
                                  samples_per_level: int = _DEFAULT_SAMPLES_PER_LEVEL,
                                  inter_level_delay_s: float = _DEFAULT_INTER_LEVEL_DELAY_S,
                                  payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
                                  httpx_timeout_s: float = _DEFAULT_HTTPX_TIMEOUT_S,
                                  on_level_start: Optional[Callable[[int, int], None]] = None,
                                  on_level_done: Optional[Callable[[int, Dict[str, float], float], None]] = None
                                  ) -> Dict[str, Dict[str, float]]:
    """*measure_handler_scaling()* per-level latency stats under closed-loop concurrency.

    For each `n_con_usr` level in the ladder, launches that many concurrent workers each issuing a derived number of sequential requests against the single-worker vernier, then aggregates the latency distribution. Quantifies how the FastAPI / event-loop stack's response time grows as in-flight user requests stack up on one handler.

    `n_con_usr` is the CLIENT-side concurrency knob; the SERVICE-side parallelism `c_srv` stays fixed at 1 (one uvicorn worker, one handler). The two must not be conflated.

    When `per_worker` is None, `per_worker = max(1, samples_per_level // n_usr)` keeps per-level wall time bounded even at `n_usr = 10_000` (otherwise a fixed `per_worker = 200` would issue 2 million requests for one level).

    Args:
        port (int): port the vernier server is listening on.
        n_con_usr (Tuple[int, ...]): concurrent-user load levels (e.g. 1, 10, 50, 100).
        warmup (int): discard-this-many requests (total, not per-worker) upfront.
        per_worker (Optional[int]): sequential requests per concurrent worker. When None, derived from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived; ignored when `per_worker` is given explicitly.
        inter_level_delay_s (float): quiet window between levels so uvicorn drains TCP backlog plus tail responses.
        payload_size_bytes (int): body size for each probe; defaults to `_DEFAULT_PAYLOAD_SIZE_BYTES`.
        httpx_timeout_s (float): per-request httpx timeout; high default because at `n_con_usr >= 5000` the kernel connect queue drains in seconds.
        on_level_start (Optional[Callable[[int, int], None]]): invoked with `(n_con_usr, total_samples)` before each level starts.
        on_level_done (Optional[Callable[[int, Dict, float], None]]): invoked with `(n_con_usr, stats_dict, elapsed_s)` after each level finishes.

    Returns:
        Dict[str, Dict[str, float]]: `{"<n_con_usr>": stats_from_us_status_pairs(...)}` per ladder level.
    """
    _url = "/invoke"
    _base = f"http://127.0.0.1:{port}"
    _body = _build_probe_body(payload_size_bytes)
    _result: Dict[str, Dict[str, float]] = {}
    _max_n_con = 1
    for _n_con_peek in n_con_usr:
        if int(_n_con_peek) > _max_n_con:
            _max_n_con = int(_n_con_peek)
    _limits = httpx.Limits(max_connections=_max_n_con,
                           max_keepalive_connections=_max_n_con)
    _timeout = httpx.Timeout(float(httpx_timeout_s))
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
            _all_pairs: List[Tuple[int, int]] = []
            for _lst in _lists:
                _all_pairs.extend(_lst)
            if per_worker is None:
                _cap = int(samples_per_level)
                if len(_all_pairs) > _cap:
                    _all_pairs = _all_pairs[:_cap]
            _key = str(_count)
            _stats = stats_from_us_status_pairs(_all_pairs)
            _result[_key] = _stats
            if on_level_done is not None:
                _elapsed = time.perf_counter() - _t0
                on_level_done(_count, _stats, _elapsed)
            del _all_pairs, _tasks, _lists
            gc.collect()
            if inter_level_delay_s > 0.0:
                await asyncio.sleep(float(inter_level_delay_s))
    return _result
