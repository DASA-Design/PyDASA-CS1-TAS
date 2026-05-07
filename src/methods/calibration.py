# -*- coding: utf-8 -*-
"""
Module methods/calibration.py
=============================

Per-host noise-floor characterisation orchestrator. Sibling to `src.methods.analytic` / `stochastic` / `dimensional` / `experiment` but its subject is the host, not the TAS architecture. Composes the host-floor probes (timer / jitter / loopback / handler-scaling), the optional rate-saturation block, and the optional handler-stability sweep into one JSON envelope. Every `experiment` run references the latest envelope so measured latencies report as `value - loopback_median +/- jitter_p99`.

After the calibration refactor (Stages C1-C9b, 2026-05-04) this module became a thin orchestrator: the actual probe implementations live in `src/calibration/` (host probes, rate sweep, stability sweep), the dimensional card lives in `src/dimensional/dasaprof.py`, and the multi-combo Route-B sweep lives in `src/dimensional/dasa_sweep.py`. This file re-exports their public names so existing call sites (notebook, CLI, tests) keep working unchanged.

Public entry points:

    - `run(...)` host-floor probes + optional rate / stability blocks + Route-B dim card.
    - `run_rate_sweep(...)` rate-saturation probe (re-export from `src.calibration.rate`).
    - `run_handler_stability_sweep(...)` apparatus self-consistency probe (re-export from `src.calibration.stability`).
    - `run_calib_sweep(envelope, sweep_grid, ...)` Route-B measured sweep across `(c, K, mu_factor)` (re-export from `src.dimensional.dasa_sweep`).
    - `derive_calib_coefs(envelope, ...)` Route-B dim card from a single envelope (re-export from `src.dimensional.dasaprof`).

Run::

    python -m src.methods.calibration
    python -m src.methods.calibration --timer-samples 50000 --jitter-samples 2000
    python -m src.methods.calibration --rate-sweep
    python -c "from src.methods.calibration import run, run_calib_sweep; \\
               env = run(); run_calib_sweep(env)"
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import atexit
import gc
import json
import platform
import socket
import sys
import threading
import time
import weakref
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# web stack
from fastapi import FastAPI

# local modules: re-exports from the new calibration + dimensional packages
from src.calibration import (measure_handler_scaling,
                             measure_jitter,
                             measure_loopback,
                             measure_timer,
                             run_handler_stability_sweep,
                             run_rate_sweep,
                             snapshot_host_profile)
from src.calibration.rate import (_aggregate_trials as _aggregate_rate_trials,
                                  _drive_lambda_step,
                                  _post_one,
                                  batch_size_for as _batch_size_for,
                                  find_highest_sustainable_rate
                                  as _find_highest_sustainable_rate)
from src.dimensional import derive_calib_coefs, run_calib_sweep
from src.dimensional.dasa_sweep import _resolve_mu_anchor
from src.dimensional.dasaprof import _CALIB_DIM_TAG
from src.experiment.instances import build_gauge
from src.experiment.runtime import UvicornThread
from src.experiment.runtime import windows_timer_resolution as _windows_timer_resolution
from src.experiment.services import SvcSpec


_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
# Path locked by Q-B of the calibration refactor (2026-05-04 migration): envelopes live at `data/results/calibration/<dpl>/<host>_<ts>.json`. The writer in this orchestrator targets the `localhost` subdir (legacy single-mode behaviour); the new `src/calibration/SweepController` handles per-`dpl` writes directly via `src/calibration/envelope.py::write_envelope`.
_CALIB_ROOT = _ROOT / "data" / "results" / "calibration"
_CALIB_DIR = _CALIB_ROOT / "localhost"


def _load_cfg() -> Dict[str, Any]:
    """*_load_cfg()* read calibration defaults from `data/config/method/calibration.json`.

    Returns:
        Dict[str, Any]: parsed JSON contents, or an empty dict when the file is absent.
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
_DEFAULT_N_CON_USR = tuple(_CALIB_CFG.get("n_con_usr", ()))
_DEFAULT_SAMPLES_PER_LEVEL = int(_CALIB_CFG.get("samples_per_level", 0))
_DEFAULT_PORT = int(_CALIB_CFG.get("port", 8765))
_DEFAULT_READY_TIMEOUT_S = float(_CALIB_CFG.get("ready_timeout_s", 5.0))
_DEFAULT_UVICORN_BACKLOG = int(_CALIB_CFG.get("uvicorn_backlog", 16384))
_DEFAULT_HTTPX_TIMEOUT_S = float(_CALIB_CFG.get("httpx_timeout_s", 0))
_DEFAULT_SKIP_JITTER = bool(_CALIB_CFG.get("skip_jitter", False))
_DEFAULT_SKIP_LOOPBACK = bool(_CALIB_CFG.get("skip_loopback", False))
_DEFAULT_PAYLOAD_SIZE_BYTES = int(_CALIB_CFG.get("payload_size_bytes", 0))
_DEFAULT_INTER_LEVEL_DELAY_S = float(_CALIB_CFG.get("inter_level_delay_s", 0.0))
_DEFAULT_INTER_TRIAL_DELAY_S = float(_CALIB_CFG.get("inter_trial_delay_s", 0.0))
_DEFAULT_INTER_COMBO_DELAY_S = float(_CALIB_CFG.get("inter_combo_delay_s", 0.0))

_DEFAULT_SKIP_RATE_SWEEP = bool(_CALIB_CFG.get("skip_rate_sweep", True))
_RATE_SWEEP_CFG: Dict[str, Any] = _CALIB_CFG.get("rate_sweep", {})
_DEFAULT_RATE_SWEEP_RATES: Tuple[float, ...] = tuple(
    float(_r) for _r in _RATE_SWEEP_CFG.get("rates", ()))
_DEFAULT_RATE_SWEEP_TRIALS = int(_RATE_SWEEP_CFG.get("trials_per_rate", 5))
_DEFAULT_RATE_SWEEP_PROBE_S = float(
    _RATE_SWEEP_CFG.get("max_probe_window_s", 4.0))
_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT = float(
    _RATE_SWEEP_CFG.get("target_loss_pct", 2.0))

_DEFAULT_SKIP_HANDLER_STABILITY_SWEEP = bool(
    _CALIB_CFG.get("skip_handler_stability_sweep", True))
_HANDLER_STAB_CFG: Dict[str, Any] = _CALIB_CFG.get(
    "handler_stability_sweep", {})
_DEFAULT_HSS_C_GRID: Tuple[int, ...] = tuple(
    int(_c) for _c in _HANDLER_STAB_CFG.get("c_grid",
                                             (1, 2, 4, 8, 16, 32, 64, 128)))
_DEFAULT_HSS_TRIALS = int(_HANDLER_STAB_CFG.get("trials_per_cell", 5))
_DEFAULT_HSS_TARGET_ERROR_PCT = float(
    _HANDLER_STAB_CFG.get("target_error_pct", 2.5))
_DEFAULT_HSS_ERROR_METRIC = str(
    _HANDLER_STAB_CFG.get("error_metric", "relative_std_of_median"))
_DEFAULT_HSS_SELECTION_RULE = str(
    _HANDLER_STAB_CFG.get("selection_rule", "min_c_meeting_target"))
_DEFAULT_HSS_INTER_CELL_DELAY_S = float(
    _HANDLER_STAB_CFG.get("inter_cell_delay_s", 1.0))


def _banner(msg: str) -> None:
    """*_banner()* render a centred header band on stdout."""
    print()
    print("=" * 78)
    print(f"  {msg}")
    print("=" * 78)


def _build_ping_app() -> FastAPI:
    """*_build_ping_app()* host-floor gauge with `c=1, K=10, mu=epsilon=0`.

    Reads the first elements of `sweep_grid.{c, K}` from JSON config so the legacy single-mode behaviour matches the pre-refactor envelope shape; the new `SweepController._gauge_spec` does the same lookup independently for per-`dpl` paths.

    Returns:
        FastAPI: app with `/healthz` and `/invoke`.
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
                    mem_per_buffer=int(_payload_bytes * _K
                                       * SvcSpec.MEM_HEADROOM_FACTOR))
    return build_gauge(_spec,
                       payload_size_bytes=_payload_bytes,
                       title="calibration-vernier")


# legacy alias kept for existing call sites
_UvicornThread = UvicornThread

# zombie-vernier guard: weakref registry catches graceful exits via atexit; daemon threads handle hard kills (taskkill / kernel crash) at the cost of brief TIME_WAIT on the listening port.
_ACTIVE_VERNIERS: "weakref.WeakSet[_UvicornThread]" = weakref.WeakSet()


def _register_vernier(srv: _UvicornThread) -> _UvicornThread:
    """*_register_vernier()* track an active vernier so the atexit cleanup can reach it; returns srv unchanged for fluent use."""
    _ACTIVE_VERNIERS.add(srv)
    return srv


def _shutdown_active_verniers() -> None:
    """*_shutdown_active_verniers()* atexit hook; best-effort shutdown of every still-running vernier so the parent process never leaks uvicorn workers on a clean exit."""
    for _srv in list(_ACTIVE_VERNIERS):
        try:
            _srv.shutdown()
        except (RuntimeError, OSError):
            pass


atexit.register(_shutdown_active_verniers)


def _print_phase_marker(name: str) -> None:
    """*_print_phase_marker()* emit the `[3/4]` / `[4/4]` line when a phase begins."""
    if name == "loopback":
        print("  [3/4] loopback latency ...", flush=True)
    elif name == "handler_scaling":
        print("  [4/4] vernier handler scaling ...", flush=True)


def _print_level_start(level: int, total: int) -> None:
    """*_print_level_start()* emit the `running N requests` marker at a scaling level."""
    print(f"      c={level:>6}  running {total} requests ...", flush=True)


def _print_level_done(level: int,
                      stats: Dict[str, float],
                      elapsed: float) -> None:
    """*_print_level_done()* emit the `done in Xs` marker with the level's headline stats."""
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
        Tuple[int, ...]: parsed levels; empty fragments are dropped.
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
        Tuple[float, ...]: parsed rates; empty fragments are dropped.
    """
    _out: List[float] = []
    for _raw in arg.split(","):
        _token = _raw.strip()
        if not _token:
            continue
        _out.append(float(_token))
    return tuple(_out)


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
                            on_level_done: Optional[Any] = None
                            ) -> Dict[str, Any]:
    """*_run_async_probes()* drive the loopback + handler-scaling probes against a uvicorn thread.

    Args:
        port (int): port the vernier server binds to.
        loopback_samples (int): request count for the loopback probe.
        loopback_warmup (int): warmup POSTs discarded upfront.
        n_con_usr (Tuple[int, ...]): concurrent-user load levels for the handler-scaling probe.
        per_worker (Optional[int]): requests per concurrent worker; None derives from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        inter_level_delay_s (float): quiet window between levels.
        on_phase_start (Optional[Any]): called with the phase name (`"loopback"` / `"handler_scaling"`) just before each phase begins.
        on_level_start (Optional[Any]): forwarded to `measure_handler_scaling`.
        on_level_done (Optional[Any]): forwarded to `measure_handler_scaling`.

    Returns:
        Dict[str, Any]: `{"loopback": {...}, "handler_scaling": {...}}`.
    """
    _result: Dict[str, Any] = {}
    _app = _build_ping_app()
    _server = _register_vernier(_UvicornThread(_app, port))
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


def _run_probes_in_dedicated_loop(**kwargs: Any) -> Dict[str, Any]:
    """*_run_probes_in_dedicated_loop()* drive `_run_async_probes` on a fresh thread with its own event loop.

    Jupyter installs `SelectorEventLoop` on Windows for tornado compatibility; `select()` on Windows caps at 512 file descriptors which breaks the high-load scaling probe. A fresh worker thread with `ProactorEventLoop` (Windows IOCP) has no such cap. On non-Windows platforms this still isolates the probes from any ambient loop and behaves identically.

    Args:
        **kwargs: forwarded verbatim to `_run_async_probes`.

    Returns:
        Dict[str, Any]: probes' result envelope.

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
    _result_box.clear()
    _error_box.clear()
    gc.collect()
    return _out


def _build_output_path(profile: Dict[str, Any],
                       stamp: Optional[str] = None) -> Path:
    """*_build_output_path()* build the per-host calibration JSON path.

    Shape: `data/results/calibration/localhost/<hostname>_<YYYYMMDD_HHMMSS>.json`.

    Args:
        profile (Dict[str, Any]): host profile (`hostname` consulted).
        stamp (Optional[str]): override the timestamp suffix; default `now()`.

    Returns:
        Path: resolved path.
    """
    _raw_host = profile.get("hostname", "unknown")
    _host = str(_raw_host).replace(" ", "-")
    if stamp is None:
        _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        _stamp = str(stamp)
    return _CALIB_DIR / f"{_host}_{_stamp}.json"


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """*_write_json()* write `data` to `path`, creating parents, pretty-printed, sorted keys."""
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
        _rs_rates = _rs.get("rates", [])
        _rs_trials = _rs.get("trials_per_rate")
        _rs_target = _rs.get("target_loss_pct")
        _rs_cal = _rs.get("calibrated_rate")
        print(f"  rate sweep   : rates={_rs_rates}  trials={_rs_trials}  "
              f"target_loss<={_rs_target}%")
        if _rs_cal is not None:
            print(f"  highest sustainable rate (<= {_rs_target}% loss): "
                  f"{float(_rs_cal):.1f} req/s")
        else:
            print(f"  no rate cleared the {_rs_target}% loss bar")


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
        skip_handler_stability_sweep: bool = _DEFAULT_SKIP_HANDLER_STABILITY_SWEEP,
        hss_c_grid: Tuple[int, ...] = _DEFAULT_HSS_C_GRID,
        hss_trials_per_cell: int = _DEFAULT_HSS_TRIALS,
        hss_target_error_pct: float = _DEFAULT_HSS_TARGET_ERROR_PCT,
        hss_error_metric: str = _DEFAULT_HSS_ERROR_METRIC,
        hss_selection_rule: str = _DEFAULT_HSS_SELECTION_RULE,
        hss_inter_cell_delay_s: float = _DEFAULT_HSS_INTER_CELL_DELAY_S,
        payload_size_bytes: int = _DEFAULT_PAYLOAD_SIZE_BYTES,
        inter_level_delay_s: float = _DEFAULT_INTER_LEVEL_DELAY_S,
        inter_trial_delay_s: float = _DEFAULT_INTER_TRIAL_DELAY_S,
        write: bool = True,
        output: Optional[str] = None,
        verbose: bool = True) -> Dict[str, Any]:
    """*run()* collect the calibration envelope.

    Runs the four host-floor probes (timer, jitter, loopback, handler scaling) under `windows_timer_resolution(1)`. When `skip_rate_sweep=False`, additionally runs `run_rate_sweep(...)` and merges the result under the envelope's `rate_sweep` key. When `write=True`, the JSON is persisted under `data/results/calibration/localhost/<host>_<YYYYMMDD_HHMMSS>.json` (or `output` when given) and the resolved path is recorded on the envelope as `output_path`.

    Args:
        timer_samples (int): back-to-back `perf_counter_ns` reads for the timer probe.
        jitter_samples (int): 1 ms sleep cycles for the jitter probe.
        loopback_samples (int): POST /invoke samples for the loopback probe.
        loopback_warmup (int): warmup POSTs discarded before the loopback probe.
        n_con_usr (Tuple[int, ...]): concurrent-user load levels for the handler-scaling probe.
        per_worker (Optional[int]): sequential requests per concurrent worker; None derives from `samples_per_level`.
        samples_per_level (int): target total samples per level when `per_worker` is derived.
        port (int): loopback vernier server port.
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        skip_jitter (bool): if True, skip the jitter probe.
        skip_loopback (bool): if True, skip both the loopback and handler-scaling probes.
        skip_rate_sweep (bool): if True (default from config), skip the rate-saturation probe.
        rate_sweep_rates (Tuple[float, ...]): target rates (req/s) for the rate-sweep probe.
        rate_sweep_trials (int): trials per rate for rate-sweep aggregation.
        rate_sweep_max_probe_s (float): rate-sweep wall-clock window per trial (seconds).
        rate_sweep_target_loss_pct (float): pass bar for the rate-sweep `calibrated_rate`.
        rate_sweep_calibrate (bool): when True, compute the highest-sustainable rate at or below `rate_sweep_target_loss_pct`.
        skip_handler_stability_sweep (bool): if True, skip the 2D `(n_con_usr × c)` apparatus self-consistency probe.
        hss_c_grid (Tuple[int, ...]): server-side handler counts swept by the stability probe.
        hss_trials_per_cell (int): trials per cell.
        hss_target_error_pct (float): error gate for the per-level c selector.
        hss_error_metric (str): cell-scoring metric name.
        hss_selection_rule (str): per-level c selection rule.
        hss_inter_cell_delay_s (float): quiet window between c values.
        payload_size_bytes (int): per-request body size for the dim card's phi coefficient.
        inter_level_delay_s (float): quiet window between handler-scaling levels.
        inter_trial_delay_s (float): quiet window between rate-sweep rates.
        write (bool): persist the envelope to JSON when True.
        output (Optional[str]): override path when `write=True`; defaults to the per-host path.
        verbose (bool): print phase markers to stdout when True.

    Returns:
        Dict[str, Any]: the envelope (`host_profile`, `args`, `timer`, `jitter`, `loopback`, `handler_scaling`, optional `rate_sweep` / `handler_stability_sweep` / `dimensional_card`, `timestamp`, `elapsed_s`, `output_path`).
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
        "skip_handler_stability_sweep": bool(skip_handler_stability_sweep),
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

    if skip_handler_stability_sweep:
        if verbose:
            print()
            print("  handler-stability sweep ... SKIPPED "
                  "(opt in via skip_handler_stability_sweep=False)",
                  flush=True)
    else:
        if verbose:
            print()
            print("  handler-stability sweep (2D n_con_usr x c) ...",
                  flush=True)
        _envelope["handler_stability_sweep"] = run_handler_stability_sweep(
            n_con_usr=tuple(int(_n) for _n in n_con_usr),
            c_grid=hss_c_grid,
            trials_per_cell=hss_trials_per_cell,
            target_error_pct=hss_target_error_pct,
            error_metric=hss_error_metric,
            selection_rule=hss_selection_rule,
            samples_per_level=samples_per_level,
            warmup=loopback_warmup,
            port=port,
            payload_size_bytes=payload_size_bytes,
            ready_timeout_s=ready_timeout_s,
            inter_cell_delay_s=hss_inter_cell_delay_s,
            verbose=verbose,
        )

    if ("handler_scaling" in _envelope) and ("loopback" in _envelope):
        _dim_card = derive_calib_coefs(_envelope,
                                       payload_size_bytes=payload_size_bytes)
        if _dim_card:
            _envelope["dimensional_card"] = _dim_card

    _t_end = time.perf_counter()
    _envelope["elapsed_s"] = round(_t_end - _t0, 3)

    if write:
        if output:
            _out = Path(output)
        else:
            _out = _build_output_path(_profile)
        _write_json(_out, _envelope)
        _envelope["output_path"] = str(_out)

    gc.collect()
    return _envelope


def _build_argparser() -> argparse.ArgumentParser:
    """*_build_argparser()* CLI surface for the calibration orchestrator."""
    _p = argparse.ArgumentParser(
        prog="calibration",
        description=("Per-host noise-floor characterisation for the "
                     "experiment method. Produces one JSON envelope under "
                     "data/results/calibration/localhost/. Run BEFORE "
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
                          f"(default: {_default_n_con_usr_csv})"))
    _p.add_argument("--per-worker", type=int, default=None,
                    help=("sequential requests per concurrent worker; "
                          "when omitted, derived from --samples-per-level"))
    _p.add_argument("--samples-per-level", type=int,
                    default=_DEFAULT_SAMPLES_PER_LEVEL,
                    help=("target total samples per n_con_usr level "
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

    if _DEFAULT_SKIP_RATE_SWEEP:
        _default_rate_sweep_state = "OFF"
    else:
        _default_rate_sweep_state = "ON"
    _p.add_argument("--rate-sweep", dest="rate_sweep", action="store_true",
                    default=(not _DEFAULT_SKIP_RATE_SWEEP),
                    help=("enable the rate-saturation probe; opt-in by default "
                          f"(currently {_default_rate_sweep_state})"))
    _p.add_argument("--no-rate-sweep", dest="rate_sweep",
                    action="store_false",
                    help="explicit opt-out of the rate-saturation probe")
    _default_rates_csv = ",".join(str(_r) for _r in _DEFAULT_RATE_SWEEP_RATES)
    _p.add_argument("--rate-sweep-rates", type=str, default=None,
                    help=("comma-separated target rates in req/s "
                          f"(default: {_default_rates_csv})"))
    _p.add_argument("--rate-sweep-trials", type=int,
                    default=_DEFAULT_RATE_SWEEP_TRIALS,
                    help=("trials per rate "
                          f"(default: {_DEFAULT_RATE_SWEEP_TRIALS})"))
    _p.add_argument("--rate-sweep-target-loss", type=float,
                    default=_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT,
                    help=("pass bar (percent) for the calibrated "
                          "highest-sustainable rate "
                          f"(default: {_DEFAULT_RATE_SWEEP_TARGET_LOSS_PCT})"))

    if _DEFAULT_SKIP_HANDLER_STABILITY_SWEEP:
        _default_hss_state = "OFF"
    else:
        _default_hss_state = "ON"
    _p.add_argument("--handler-stability-sweep",
                    dest="handler_stability_sweep",
                    action="store_true",
                    default=(not _DEFAULT_SKIP_HANDLER_STABILITY_SWEEP),
                    help=("enable the 2D handler-stability probe; opt-in by default "
                          f"(currently {_default_hss_state})"))
    _p.add_argument("--no-handler-stability-sweep",
                    dest="handler_stability_sweep",
                    action="store_false",
                    help="explicit opt-out of the handler-stability sweep")

    _p.add_argument("--payload-size-bytes", type=int,
                    default=_DEFAULT_PAYLOAD_SIZE_BYTES,
                    help=("per-request body size for the dim card's phi "
                          f"coefficient (default: {_DEFAULT_PAYLOAD_SIZE_BYTES})"))
    _p.add_argument("--output", type=str, default=None,
                    help="override the output JSON path")
    return _p


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
        skip_handler_stability_sweep=(not _args.handler_stability_sweep),
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
