# -*- coding: utf-8 -*-
"""
calibration.py
==============

Per-host noise-floor characterization for the `experiment` method. Runs the four baselines from `notes/calibration.md` section 3 -- timer resolution, scheduling jitter, loopback latency, empty-handler scaling -- and writes a single JSON envelope to `data/results/experiment/calibration/<host>_<YYYYMMDD_HHMMSS>.json`.

Every `experiment` run should reference the latest calibration JSON by timestamp in its run envelope (`baseline_ref`) so measured latencies can be reported as `value - loopback_median +/- jitter_p99`. This is the pre-run gate planned for P0.3; this script (P0.1) only produces the baseline.

Kept deliberately small and dependency-light:

    - ctypes `timeBeginPeriod(1)` inlined -- no import from `src.methods.experiment` whose transitive imports would warm the executor pool and perturb the measurements.
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
import numpy as np

# bring the repo root onto sys.path so ad-hoc script runs import cleanly
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

# HTTP + server stack -- imported after sys.path tweak so a fresh clone works
import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402


_CALIB_DIR = _ROOT / "data" / "results" / "experiment" / "calibration"

_DEFAULT_TIMER_SAMPLES = 100_000
_DEFAULT_JITTER_SAMPLES = 5_000
_DEFAULT_LOOPBACK_SAMPLES = 5_000
_DEFAULT_LOOPBACK_WARMUP = 500
_DEFAULT_CONCURRENCY = (1, 10, 50, 100)
_DEFAULT_PORT = 8765

# sleep() target for the jitter probe; matches the recipe in section 3.2
_JITTER_TARGET_NS = 1_000_000  # 1 ms


def _banner(msg: str) -> None:
    """*_banner()* print a centred header band."""
    print()
    print("=" * 78)
    print(f"  {msg}")
    print("=" * 78)


@contextlib.contextmanager
def _windows_timer_resolution(period_ms: int = 1):
    """*_windows_timer_resolution()* raise the Windows system-timer floor for the block.

    No-op on non-Windows. Mirror of the helper in `src/methods/experiment.py`; inlined here to keep `calibration.py` free of the experiment module's transitive imports (which would warm the executor pool and perturb the jitter / loopback measurements).

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

    Does not depend on `psutil` (deliberately excluded per the `project_experiment_milestone.md` memory note). Thermal readings are not collected for the same reason; run with a cool laptop on charger and document conditions in the devlog.

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
    return {
        "min_ns": int(_arr.min()),
        "median_ns": float(np.median(_arr)),
        "mean_ns": float(_arr.mean()),
        "std_ns": float(_arr.std()),
        "zero_frac": float(_zero / samples),
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
    return {
        "mean_us": float(_us.mean()),
        "std_us": float(_us.std()),
        "p50_us": float(np.percentile(_us, 50)),
        "p99_us": float(np.percentile(_us, 99)),
        "max_us": float(_us.max()),
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

    def __init__(self, app: FastAPI, port: int) -> None:
        super().__init__(daemon=True)
        _config = uvicorn.Config(app,
                                 host="127.0.0.1",
                                 port=int(port),
                                 log_level="error",
                                 access_log=False)
        self._server = uvicorn.Server(_config)
        self._port = int(port)

    def run(self) -> None:
        """*run()* thread entry point; blocks until `shutdown()` is called."""
        self._server.run()

    def wait_ready(self, timeout_s: float = 5.0) -> None:
        """*wait_ready()* poll `/ping` until it returns 200 or the timeout fires."""
        _deadline = time.perf_counter() + float(timeout_s)
        _url = f"http://127.0.0.1:{self._port}/ping"
        while time.perf_counter() < _deadline:
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
    async with httpx.AsyncClient(base_url=_base) as _client:
        for _ in range(int(warmup)):
            await _client.get(_url)
        for _ in range(int(samples)):
            _t1 = time.perf_counter_ns()
            await _client.get(_url)
            _t2 = time.perf_counter_ns()
            _rtts.append(_t2 - _t1)
    _arr = np.asarray(_rtts, dtype=np.int64)
    _us = _arr / 1000.0
    return {
        "min_us": float(_us.min()),
        "median_us": float(np.median(_us)),
        "p95_us": float(np.percentile(_us, 95)),
        "p99_us": float(np.percentile(_us, 99)),
        "std_us": float(_us.std()),
        "samples": int(samples),
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
                                  per_worker: int,
                                  warmup: int) -> Dict[str, Dict[str, float]]:
    """*measure_handler_scaling()* loopback latency at increasing concurrency levels.

    For each level `c`, launches `c` concurrent workers each doing `per_worker` requests. Reports the aggregate latency distribution. Tells you how much the FastAPI / event-loop stack degrades as load stacks up on the empty handler.

    Args:
        port (int): port the ping server is listening on.
        concurrency (tuple[int, ...]): levels to test (e.g. 1, 10, 50, 100).
        per_worker (int): requests per concurrent worker.
        warmup (int): discard-this-many requests (total, not per-worker) upfront.

    Returns:
        dict[str, dict]: `{"<c>": {min_us, median_us, p95_us, p99_us, std_us, samples}}`.
    """
    _url = "/ping"
    _base = f"http://127.0.0.1:{port}"
    _result: Dict[str, Dict[str, float]] = {}
    async with httpx.AsyncClient(base_url=_base) as _client:
        for _ in range(int(warmup)):
            await _client.get(_url)
        for _c in concurrency:
            _tasks = [_run_concurrent_worker(_client, _url, per_worker)
                      for _ in range(int(_c))]
            _lists = await asyncio.gather(*_tasks)
            _all: List[int] = []
            for _lst in _lists:
                _all.extend(_lst)
            _arr = np.asarray(_all, dtype=np.int64)
            _us = _arr / 1000.0
            _result[str(int(_c))] = {
                "min_us": float(_us.min()),
                "median_us": float(np.median(_us)),
                "p95_us": float(np.percentile(_us, 95)),
                "p99_us": float(np.percentile(_us, 99)),
                "std_us": float(_us.std()),
                "samples": int(_us.size),
            }
    return _result


def _parse_concurrency(arg: str) -> Tuple[int, ...]:
    """*_parse_concurrency()* parse a comma-separated concurrency list."""
    return tuple(int(_x.strip()) for _x in arg.split(",") if _x.strip())


def _build_output_path(profile: Dict[str, Any], stamp: Optional[str] = None) -> Path:
    """*_build_output_path()* build the per-host calibration JSON path.

    Shape: `data/results/experiment/calibration/<hostname>_<YYYYMMDD_HHMMSS>.json`.

    Args:
        profile (dict): host profile (we use `hostname`).
        stamp (Optional[str]): override the timestamp suffix; default `now()`.
    """
    _host = str(profile.get("hostname", "unknown")).replace(" ", "-")
    if stamp is None:
        _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    print(f"  host         : {_hp.get('hostname')}  ({_hp.get('os')})")
    print(f"  python       : {_hp.get('python')} {_hp.get('python_impl')}  "
          f"cpu={_hp.get('cpu_count')}  ram={_hp.get('ram_total_gb')}")
    _t = envelope.get("timer", {})
    print(f"  timer        : min={_t.get('min_ns')} ns  "
          f"median={_t.get('median_ns'):.1f} ns  "
          f"std={_t.get('std_ns'):.1f} ns")
    _j = envelope.get("jitter")
    if _j is not None:
        print(f"  jitter       : mean={_j.get('mean_us'):.1f} us  "
              f"p99={_j.get('p99_us'):.1f} us  "
              f"max={_j.get('max_us'):.1f} us")
    _l = envelope.get("loopback")
    if _l is not None:
        print(f"  loopback     : min={_l.get('min_us'):.1f} us  "
              f"median={_l.get('median_us'):.1f} us  "
              f"p99={_l.get('p99_us'):.1f} us")
    _h = envelope.get("handler_scaling")
    if _h:
        print("  handler scaling (median / p99 us):")
        for _c, _stats in _h.items():
            print(f"    c={_c:>4}  median={_stats['median_us']:.1f}  "
                  f"p99={_stats['p99_us']:.1f}  "
                  f"samples={_stats['samples']}")


async def _run_async_probes(args: argparse.Namespace) -> Dict[str, Any]:
    """*_run_async_probes()* drive the loopback + handler-scaling probes against a uvicorn thread."""
    _result: Dict[str, Any] = {}
    if args.skip_loopback:
        return _result
    _app = _build_ping_app()
    _server = _UvicornThread(_app, args.port)
    _server.start()
    try:
        _server.wait_ready(timeout_s=args.ready_timeout_s)
        _result["loopback"] = await measure_loopback(
            port=args.port,
            samples=args.loopback_samples,
            warmup=args.loopback_warmup,
        )
        _result["handler_scaling"] = await measure_handler_scaling(
            port=args.port,
            concurrency=args.concurrency,
            per_worker=args.per_worker,
            warmup=args.loopback_warmup,
        )
    finally:
        _server.shutdown()
    return _result


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
    _p.add_argument("--concurrency", type=str, default=None,
                    help=("comma-separated concurrency levels for the "
                          "handler-scaling probe "
                          f"(default: {','.join(str(_c) for _c in _DEFAULT_CONCURRENCY)})"))
    _p.add_argument("--per-worker", type=int, default=200,
                    help=("requests per concurrent worker in the "
                          "handler-scaling probe (default: 200)"))
    _p.add_argument("--port", type=int, default=_DEFAULT_PORT,
                    help=("loopback ping server port "
                          f"(default: {_DEFAULT_PORT})"))
    _p.add_argument("--ready-timeout-s", type=float, default=5.0,
                    help="seconds to wait for uvicorn readiness (default: 5.0)")
    _p.add_argument("--skip-loopback", action="store_true",
                    help="run only the timer + jitter probes (no HTTP)")
    _p.add_argument("--skip-jitter", action="store_true",
                    help="run only the timer probe (fastest self-test)")
    _p.add_argument("--output", type=str, default=None,
                    help=("override the output path; default is "
                          "data/results/experiment/calibration/<host>_<date>.json"))
    return _p


def main(argv: Optional[List[str]] = None) -> None:
    """*main()* CLI entry point.

    Args:
        argv (Optional[List[str]]): argv override for tests; None uses `sys.argv`.
    """
    _args = _build_argparser().parse_args(argv)
    if _args.concurrency is not None:
        _args.concurrency = _parse_concurrency(_args.concurrency)
    else:
        _args.concurrency = _DEFAULT_CONCURRENCY

    _profile = snapshot_host_profile()

    _banner(f"calibration.py  host={_profile['hostname']!r}  "
            f"os={_profile['os']}  python={_profile['python']}")
    print(f"  cpu_count={_profile['cpu_count']}  "
          f"ram_total_gb={_profile['ram_total_gb']}")
    print(f"  timer_samples={_args.timer_samples}  "
          f"jitter_samples={_args.jitter_samples}  "
          f"loopback_samples={_args.loopback_samples}  "
          f"concurrency={_args.concurrency}")

    _t0 = time.perf_counter()
    _envelope: Dict[str, Any] = {
        "host_profile": _profile,
        "args": {
            "timer_samples": int(_args.timer_samples),
            "jitter_samples": int(_args.jitter_samples),
            "loopback_samples": int(_args.loopback_samples),
            "loopback_warmup": int(_args.loopback_warmup),
            "concurrency": list(int(_c) for _c in _args.concurrency),
            "per_worker": int(_args.per_worker),
            "port": int(_args.port),
            "skip_jitter": bool(_args.skip_jitter),
            "skip_loopback": bool(_args.skip_loopback),
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    with _windows_timer_resolution(1):
        print("\n  [1/4] timer resolution ...")
        _envelope["timer"] = measure_timer(_args.timer_samples)

        if _args.skip_jitter:
            print("\n  [2/4] jitter ... SKIPPED")
        else:
            print("\n  [2/4] scheduling jitter ...")
            _envelope["jitter"] = measure_jitter(_args.jitter_samples)

        if _args.skip_loopback:
            print("\n  [3/4] loopback ... SKIPPED")
            print("\n  [4/4] handler scaling ... SKIPPED")
        else:
            print("\n  [3/4] loopback latency ...")
            print("\n  [4/4] empty-handler scaling ...")
            _probes = asyncio.run(_run_async_probes(_args))
            _envelope.update(_probes)

    _envelope["elapsed_s"] = round(time.perf_counter() - _t0, 3)

    if _args.output:
        _out = Path(_args.output)
    else:
        _out = _build_output_path(_profile)
    _write_json(_out, _envelope)
    _envelope["output_path"] = str(_out)

    _print_summary(_envelope)
    print()
    print(f"  >>> written: {_out}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[interrupted]")
        sys.exit(130)
