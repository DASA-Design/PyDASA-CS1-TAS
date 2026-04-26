# -*- coding: utf-8 -*-
"""
Module experiment.py
====================

Method 4 of the CS-01 TAS pipeline; FastAPI mesh + ramped client through `TAS_{1}`, emits the standard envelope (per-node df + network aggregate + R1/R2/R3 verdict). Output split by deployment (`local` / `loopback_aliased` / `remote`).

Public API:
    - `run(adp, prf, scn, wrt, method_cfg=None, skip_calibration=False, verbose=True, dpl=None, launcher_role=None)` standard orchestrator contract.
    - `main()` CLI entry point.

CLI::

    python -m src.methods.experiment --adaptation baseline
    python -m src.methods.experiment --adaptation s1 --profile opti
    python -m src.methods.experiment --deployment loopback_aliased
    python -m src.methods.experiment --deployment remote --launcher-role client
"""
# native python modules
from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import gc
import json
import sys
import tempfile
import threading
from pathlib import Path

# data types
from typing import Any, Awaitable, Callable, Dict, List, Optional

# scientific stack
import numpy as np
import pandas as pd

# local modules
from src.analytic.jackson import build_rho_grid
from src.analytic.metrics import aggregate_net, check_reqs
from src.experiment.client import ClientCfg
from src.experiment.client import ClientSimulator
from src.experiment.client import build_ramp_cfg
from src.experiment.launcher import ExperimentLauncher
from src.experiment.services import derive_seed
from src.io import (NetCfg,
                    calibration_age_hours,
                    calibration_band_us,
                    calibration_floor_us,
                    load_latest_calibration,
                    load_method_cfg,
                    load_profile)


_ROOT = Path(__file__).resolve().parents[2]
_RESULTS_DIR = _ROOT / "data" / "results" / "experiment"

# deployment modes recognised by the experiment runner; mirrors the SvcRegistry / ExperimentLauncher enum
_VALID_DEPLOYMENTS = ("local", "loopback_aliased", "remote")

# Hours after which a calibration is considered stale (warning only)
_CALIB_STALE_HOURS: float = 24.0


def _resolve_baseline(*,
                      skip: bool,
                      verbose: bool = True) -> Optional[Dict[str, Any]]:
    """*_resolve_baseline()* load the most recent host calibration; enforces the pre-run noise-floor gate.

    Args:
        skip (bool): bypass the gate; returns `None` with a loud warning.
        verbose (bool): when False, suppress stale / skip warnings.

    Returns:
        Optional[Dict[str, Any]]: parsed calibration envelope, or `None` when skipped.

    Raises:
        RuntimeError: when `skip=False` and no calibration file exists for the current host.
    """
    if skip:
        if verbose:
            _msg = "WARNING: --skip-calibration; raw latencies are not host-adjusted."
            print(_msg)
        return None

    _env = load_latest_calibration()
    if _env is None:
        _msg = "No host calibration; run `python -m src.methods.calibration` "
        _msg += "or pass --skip-calibration."
        raise RuntimeError(_msg)
    _age = calibration_age_hours(_env)
    if verbose and _age > _CALIB_STALE_HOURS:
        print(f"WARNING: calibration {_age:.1f} h old (>{_CALIB_STALE_HOURS:.0f} h); consider re-running.")
    return _env


def _build_baseline_block(envelope: Optional[Dict[str, Any]]
                          ) -> Dict[str, Any]:
    """*_build_baseline_block()* summarise a calibration envelope for the result envelope.

    Stored alongside every experiment run so downstream reporting can apply the `reported = measured - loopback_median +/- jitter_p99` convention without re-reading the calibration JSON.

    Args:
        envelope (Optional[Dict[str, Any]]): calibration envelope, or `None` when the gate was skipped.

    Returns:
        Dict[str, Any]: summary block with `baseline_ref`, `loopback_median_us`, `jitter_p99_us`, `age_hours`, `applied`.
    """
    if envelope is None:
        return {
            "baseline_ref": None,
            "loopback_median_us": 0.0,
            "jitter_p99_us": 0.0,
            "age_hours": None,
            "applied": False,
        }
    _ref = envelope.get("output_path")
    _floor = calibration_floor_us(envelope)
    _band = calibration_band_us(envelope)
    _age = calibration_age_hours(envelope)
    return {
        "baseline_ref": _ref,
        "loopback_median_us": _floor,
        "jitter_p99_us": _band,
        "age_hours": _age,
        "applied": True,
    }


@contextlib.contextmanager
def _windows_timer_resolution(period_ms: int = 1):
    """*_windows_timer_resolution()* boost Windows system-timer resolution for the duration of the block.

    On Windows, `asyncio.sleep` is bounded by the global system timer
    (default ~15 ms), so very short interarrivals oversleep and the client
    can never reach high target rates. `winmm.timeBeginPeriod(1)` lowers
    the global timer floor to 1 ms for the lifetime of the call (paired
    with `timeEndPeriod` on exit), giving asyncio.sleep ~1 ms granularity.

    Recipe from https://stackoverflow.com/q/77895160 (asyncio.sleep
    precision on Windows). No-op on non-Windows platforms.

    Args:
        period_ms (int): requested timer floor in milliseconds. The OS clamps this to the supported range (typically 1-15 ms).

    Yields:
        None: contextmanager body produces no value; entering the block raises the timer resolution, exiting restores it.
    """
    if sys.platform != "win32":
        yield
        return

    try:
        _winmm = ctypes.WinDLL("winmm")
    except (OSError, AttributeError):
        # winmm unavailable -> fall back to default resolution
        yield
        return

    _winmm.timeBeginPeriod(int(period_ms))
    try:
        yield
    finally:
        _winmm.timeEndPeriod(int(period_ms))


def _build_svc_df_from_logs(cfg: NetCfg,
                            log_dir: Path,
                            duration_s: float) -> pd.DataFrame:
    """*_build_svc_df_from_logs()* build a per-service metrics DataFrame from the flushed CSV logs via operational analysis (Denning & Buzen 1978).

    Every quantity is a direct measurement over the observation window `T`; no Markovian assumption (Poisson arrivals, exponential service, steady state, ergodicity) is required. The operational identities used (cf. `notes/operational_analysis.md` Table I):

        - **lambda** = `A / T` (arrival rate from logged invocations)
        - **X** (throughput) = `C / T` (completion rate)
        - **U_local** (alias `rho`) = `B_local / (T * c)` where `B_local = sum(local_end_ts - start_ts)` is local busy time excluding any downstream dispatch await; the M/M/c/K-comparable utilisation.
        - **R_local** (alias `W`) = mean(`local_end_ts - recv_ts`); local response time used for analytic / stochastic / dimensional cross-checks.
        - **Wq** (queue wait) = mean(`start_ts - recv_ts`); positive only when admission gating (`SvcCtx.sem`) makes requests wait.
        - **L** = `X * W`            (Little's law on local response time)
        - **Lq** = `X * Wq`          (Little's law on queue wait)
        - **U_total** (alias `rho_total`) = `B_total / (T * c)` where `B_total = sum(end_ts - start_ts)` includes the full downstream subtree; matches the client-perceived end-to-end utilisation.
        - **W_total** = mean(`end_ts - recv_ts`); client-perceived end-to-end response time used for Camara R2 (response time <= 26 ms) validation.
        - **L_total** = `X * W_total`            (system-wide in-flight by Little's law)

    Terminal atomics never publish `mark_local_end()` so `local_end_ts == end_ts` for them; local and total views coincide. Composites and dispatching atomics publish `mark_local_end()` right before the dispatch await, so `local_end_ts < end_ts` and the two views differ by the downstream wait.

    Two failure modes stay separated:

        - `epsilon`: Bernoulli business failure `count(200 AND success=False) / count(200)`. Directly comparable to the profile's `_setpoint` for epsilon (what R1 validates).
        - `buffer_reject_rate`: `count(503) / count(all)`. Capacity overflow, not a reliability signal.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        log_dir (Path): directory carrying `<service>.csv` files.
        duration_s (float): observation window length `T`. Used as the denominator for X / U / lambda; should be the wall-clock duration the measurement covers.

    Returns:
        pd.DataFrame: one row per artifact with the analytic-schema columns plus `buffer_reject_rate`.

    Raises:
        pandas.errors.EmptyDataError: when a per-service CSV exists but is empty (zero rows including header). Missing CSVs are tolerated and produce zero-filled rows.
    """
    _rows: List[Dict[str, Any]] = []

    for _idx, _a in enumerate(cfg.artifacts):
        _fname = _a.key.replace("{", "_").replace("}", "_").replace(",", "_")
        _csv = log_dir / f"{_fname}.csv"

        _lam = 0.0
        _rho = 0.0
        _L = 0.0
        _Lq = 0.0
        _W = 0.0
        _Wq = 0.0
        _rho_total = 0.0
        _L_total = 0.0
        _W_total = 0.0
        _eps = 0.0
        _bfr = 0.0

        if _csv.exists():
            _df = pd.read_csv(_csv)
            _n = len(_df)

            # pandas reads success="True"/"False" as object-dtype; astype(bool) is wrong, coerce via str.lower().eq("true")
            _succ_col = _df["success"]
            if _succ_col.dtype != bool:
                _succ_bool = _succ_col.astype(str).str.lower().eq("true")
            else:
                _succ_bool = _succ_col
            _df = _df.assign(success=_succ_bool)

            # split by failure mode
            _completed = _df[_df["status_code"] == 200]
            _business_fails = _completed[~_completed["success"]]
            _infra_fails = _df[_df["status_code"] != 200]

            # operational arrival rate: A / T (every logged row is an arrival)
            if duration_s > 0:
                _lam = _n / duration_s
            else:
                _lam = 0.0

            # epsilon is business-level only; compares to profile's setpoint
            if len(_completed) > 0:
                _eps = len(_business_fails) / len(_completed)
            else:
                _eps = 0.0

            # buffer_reject_rate tracks infrastructure overflow separately
            if _n > 0:
                _bfr = len(_infra_fails) / _n
            else:
                _bfr = 0.0

            # timing from successful completions only (failed ones have no meaningful response time). The local view (`rho / L / W`) brackets only the local work via `local_end_ts` and is the M/M/c/K-comparable observable; the total view (`rho_total / L_total / W_total`) brackets the whole subtree via `end_ts` and matches the client-perceived end-to-end response time used for Camara R2 validation. For terminal atomics that never dispatch, `local_end_ts == end_ts` so the two views coincide.
            _succ = _completed[_completed["success"]]
            if len(_succ) > 0 and duration_s > 0:
                _start = pd.to_numeric(_succ["start_ts"], errors="coerce")
                _local_end = pd.to_numeric(_succ["local_end_ts"], errors="coerce")
                _end = pd.to_numeric(_succ["end_ts"], errors="coerce")
                _recv = pd.to_numeric(_succ["recv_ts"], errors="coerce")

                # local response time R_local = mean(local_end - recv); queue wait Wq = mean(start - recv); total response time R_total = mean(end - recv)
                _W = float(np.nanmean(_local_end - _recv))
                _Wq = float(np.nanmean(_start - _recv))
                _W_total = float(np.nanmean(_end - _recv))

                # operational U = B / (T*c). Local B excludes downstream dispatch wait; total B includes it. Identity U = X*S holds for both with the matching service-time interpretation; no PASTA needed.
                _B_local = float(np.nansum(_local_end - _start))
                _B_total = float(np.nansum(_end - _start))
                _c = max(int(_a.c), 1)
                _rho = _B_local / (duration_s * _c)
                _rho_total = _B_total / (duration_s * _c)

                # X = C / T; use in Little's law so failed completions don't inflate L
                _X = len(_succ) / duration_s
                _L = _X * _W
                _Lq = _X * _Wq
                _L_total = _X * _W_total

        _rows.append({
            "node": _idx,
            "key": _a.key,
            "name": _a.name,
            "type": _a.type_,
            "lambda": _lam,
            "mu": float(_a.mu),
            "c": int(_a.c),
            "K": int(_a.K),
            "rho": _rho,
            "L": _L,
            "Lq": _Lq,
            "W": _W,
            "Wq": _Wq,
            "rho_total": _rho_total,
            "L_total": _L_total,
            "W_total": _W_total,
            "epsilon": _eps,
            "buffer_reject_rate": _bfr,
        })

    return pd.DataFrame(_rows)


async def _run_async(cfg: NetCfg,
                     method_cfg: Dict[str, Any],
                     adp: str,
                     log_dir: Path,
                     dpl: str = "local",
                     launcher_role: str = "all") -> Dict[str, Any]:
    """*_run_async()* drive one adaptation end-to-end through the launch -> snapshot -> ramp -> flush sequence.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        method_cfg (Dict[str, Any]): experiment method config.
        adp (str): adaptation label (`baseline` / `s1` / `s2` / `aggregate`).
        log_dir (Path): directory that receives the per-service CSVs and the config snapshot.

    Returns:
        Dict[str, Any]: ramp output plus `duration_s` and `service_log_counts`.

    Raises:
        Exception: any error raised by `ExperimentLauncher` startup, `ClientSimulator.run_ramp()`, `_lnc.snapshot_config`, or `_lnc.flush_logs` propagates unmodified so the caller's replicate loop can decide whether to retry or abort.
    """
    # 1 ms timer resolution for the lifetime of this run; no-op off-Windows
    with _windows_timer_resolution(1):
        async with ExperimentLauncher(cfg=cfg,
                                      method_cfg=method_cfg,
                                      adaptation=adp,
                                      deployment=dpl,
                                      launcher_role=launcher_role) as _lnc:
            # client config derived from method_cfg + launcher's kind-weights
            _seed = int(method_cfg["seed"])
            _sizes_by_kind = dict(method_cfg.get("request_size_bytes", {}))
            # scalar fallback for tests with no sizes-by-kind map; default = analyse_request size
            _req_size = int(_sizes_by_kind.get("analyse_request", 256))

            # rho_grid -> rates via Jackson solver; rates and rho_grid are mutually exclusive (validate_ramp enforces)
            _ramp_block = dict(method_cfg["ramp"])
            _rho_grid_meta: List[Dict[str, Any]] = []
            if _ramp_block.get("rho_grid"):
                _grid = build_rho_grid(cfg, list(_ramp_block["rho_grid"]))
                _ramp_block["rates"] = [float(_lz) for (_, _lz, _) in _grid]
                _ramp_block.pop("rho_grid", None)
                _rho_grid_meta = [
                    {"rho_target": float(_r),
                     "lambda_z_inverted": float(_lz),
                     "bottleneck_artifact_idx": int(_b)}
                    for (_r, _lz, _b) in _grid
                ]

            _client_cfg = ClientCfg(
                entry_service="TAS_{1}",
                seed=_seed,
                request_size_bytes=_req_size,
                request_sizes_by_kind=_sizes_by_kind,
                kind_weights=dict(_lnc.kind_weights),
                ramp=build_ramp_cfg(_ramp_block),
            )
            _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)

            # emit config.json BEFORE the ramp starts so a crash leaves the snapshot describing what was about to run
            _td = dict(method_cfg.get("request_size_bytes", {}))
            _lnc.snapshot_config(log_dir,
                                 extras={
                                     "seed": _seed,
                                     "request_size_bytes": _req_size,
                                     "request_size_bytes_by_kind": _td,
                                     "ramp": method_cfg.get("ramp", {}),
                                     "entry_service": "TAS_{1}",
                                 })

            _ramp_out = await _sim.run_ramp()
            _counts = _lnc.flush_logs(log_dir)
            # surface log-buffer overflow so the top-level envelope can fail loudly on non-zero
            _drops = _lnc.collect_drop_counts()

    # thread rho_grid per-point metadata back into each probe so downstream knows which rho-target it was anchored to
    if _rho_grid_meta:
        for _probe, _meta in zip(_ramp_out["probes"], _rho_grid_meta):
            _probe.update(_meta)

    # total wall-clock duration across all probes
    _duration = float(sum(_p.get("duration_s", 0.0)
                          for _p in _ramp_out["probes"]))
    _ans = {
        "probes": _ramp_out["probes"],
        "saturation_rate": _ramp_out["saturation_rate"],
        "stopped_reason": _ramp_out["stopped_reason"],
        "client_effective_rate": _ramp_out.get("client_effective_rate", 0.0),
        "duration_s": _duration,
        "service_log_counts": _counts,
        "log_drop_counts": _drops,
    }

    return _ans


def _run_async_safe(
    coro_factory: Callable[[], Awaitable[Dict[str, Any]]],
) -> Dict[str, Any]:
    """*_run_async_safe()* drive an awaitable from a sync caller, even when an event loop is already running (Jupyter, IPython, calibration's rate sweep).

    `asyncio.run()` raises `RuntimeError: asyncio.run() cannot be called from a running event loop` whenever an ambient loop is alive. This helper detects that case and dispatches `coro_factory()` to a fresh `ProactorEventLoop` (Windows) / `SelectorEventLoop` (POSIX) on a daemon worker thread, then joins. With no ambient loop it falls back to the simpler `asyncio.run` path so CLI invocations stay unchanged.

    Mirrors the trick `src.methods.calibration._run_probes_in_dedicated_loop` already uses for the high-fd-count probe path, but kept local to this module so the experiment runner has no calibration import dependency.

    Args:
        coro_factory: zero-arg callable returning the coroutine to run. Re-invoked from inside the worker thread so the coroutine binds to the worker-thread loop.

    Raises:
        Exception: re-raises any exception that fired inside the worker thread.

    Returns:
        Dict[str, Any]: the awaitable's resolved result.
    """
    try:
        asyncio.get_running_loop()
        _ambient_loop = True
    except RuntimeError:
        _ambient_loop = False

    if not _ambient_loop:
        return asyncio.run(coro_factory())

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
                _result_box[0] = _loop.run_until_complete(coro_factory())
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


def run(adp: Optional[str] = None,
        prf: Optional[str] = None,
        scn: Optional[str] = None,
        wrt: bool = True,
        method_cfg: Optional[Dict[str, Any]] = None,
        skip_calibration: bool = False,
        verbose: bool = True,
        dpl: Optional[str] = None,
        launcher_role: Optional[str] = None) -> Dict[str, Any]:
    """*run()* execute the architectural experiment for one (profile, scenario) pair.

    Enforces the per-host calibration gate: a noise-floor calibration for the current host must exist under `data/results/experiment/calibration/` before the run starts, or `skip_calibration=True` must be set to bypass with a warning. The resolved baseline is attached to the result envelope as the `baseline` block so downstream reporting can apply the `reported = measured - loopback_median +/- jitter_p99` convention.

    Output paths: `data/results/experiment/<deployment>/<scenario>/<profile>/...` with `<deployment>` in `local` / `loopback_aliased` / `remote`.

    Args:
        adp (Optional[str]): adaptation value; one of `baseline`, `s1`, `s2`, `aggregate`.
        prf (Optional[str]): profile stem (`dflt` / `opti`).
        scn (Optional[str]): explicit scenario name.
        wrt (bool): if True, write artifacts under `data/results/experiment/<deployment>/<scenario>/`. Defaults to True.
        method_cfg (Optional[Dict[str, Any]]): inline config override; used by `_QUICK_CFG` tests to skip the JSON read.
        skip_calibration (bool): when True, bypass the calibration gate; a warning is printed and `baseline.applied` is False on the result.
        verbose (bool): when False, suppress the calibration stale / skip warnings; metric output is unaffected.
        dpl (Optional[str]): deployment mode override; `None` reads `method_cfg["deployment"]` (default `"local"`). Recognised: `"local"` / `"loopback_aliased"` / `"remote"`. Non-local modes require the real-uvicorn launcher (`notes/distribute.md` G5); the in-process ASGI launcher only supports `local` until then.
        launcher_role (Optional[str]): subset of services this driver is responsible for spawning; `None` reads `method_cfg["launcher_role"]` (default `"all"`). Recognised: `"all"` / `"client"` / `"composite"` / `"atomic"` / `"composite-atomic"`.

    Returns:
        Dict[str, Any]: result envelope with `config`, `method_config`, `nodes`, `network`, `requirements`, `probes`, `saturation_rate`, `stopped_reason`, `client_effective_rate`, `log_drop_counts`, `replicates`, `baseline`, `paths`, `deployment`.

    Raises:
        RuntimeError: when `skip_calibration` is False and no calibration exists for the current host.
        ValueError: when `dpl` is not one of the recognised deployment modes.
    """
    _baseline_env = _resolve_baseline(skip=skip_calibration, verbose=verbose)
    _baseline_block = _build_baseline_block(_baseline_env)

    _cfg = load_profile(adaptation=adp, profile=prf, scenario=scn)
    if method_cfg is not None:
        _mcfg = method_cfg
    else:
        _mcfg = load_method_cfg("experiment")
    _adp = adp or "baseline"

    # deployment + launcher_role: explicit param > method_cfg > default
    if dpl is not None:
        _dpl = str(dpl)
    else:
        _dpl = str(_mcfg.get("deployment", "local"))
    if _dpl not in _VALID_DEPLOYMENTS:
        raise ValueError(
            f"dpl={_dpl!r} not recognised; valid modes are "
            f"{_VALID_DEPLOYMENTS}")
    if launcher_role is not None:
        _role = str(launcher_role)
    else:
        _role = str(_mcfg.get("launcher_role", "all"))

    # per-replicate seed derived from root_seed + 'rep_<k>'; R=1 keeps flat log-dir layout
    _replications = int(_mcfg.get("replications", 1))
    _root_seed = int(_mcfg.get("seed", 0))
    _replicates: List[Dict[str, Any]] = []

    for _k in range(_replications):
        if _replications == 1:
            _rep_seed = _root_seed
        else:
            _rep_seed = int(derive_seed(_root_seed, f"rep_{_k}"))
        _rep_mcfg = dict(_mcfg)
        _rep_mcfg["seed"] = _rep_seed

        if wrt:
            # deployment axis splits the artifact tree: local/, loopback_aliased/, remote/
            _base_dir = _RESULTS_DIR / _dpl / _cfg.scenario / _cfg.profile
            if _replications == 1:
                _log_dir = _base_dir
            else:
                _log_dir = _base_dir / f"rep_{_k}"
            _log_dir.mkdir(parents=True, exist_ok=True)
            _run_out = _run_async_safe(lambda: _run_async(_cfg,
                                                          _rep_mcfg,
                                                          _adp,
                                                          _log_dir,
                                                          _dpl,
                                                          _role))
            _nds = _build_svc_df_from_logs(_cfg,
                                           _log_dir,
                                           _run_out["duration_s"])
        else:
            with tempfile.TemporaryDirectory() as _tmp_str:
                _log_dir = Path(_tmp_str)
                _run_out = _run_async_safe(
                    lambda: _run_async(_cfg,
                                       _rep_mcfg,
                                       _adp,
                                       _log_dir,
                                       _dpl,
                                       _role))
                _nds = _build_svc_df_from_logs(_cfg,
                                               _log_dir,
                                               _run_out["duration_s"])

        _net = aggregate_net(_nds)
        _req = check_reqs(_nds)
        if wrt:
            _rep_log_dir = str(_log_dir)
        else:
            _rep_log_dir = None
        _replicates.append({
            "replicate_id": _k,
            "seed": _rep_seed,
            "nodes": _nds,
            "network": _net,
            "requirements": _req,
            "probes": _run_out["probes"],
            "saturation_rate": _run_out["saturation_rate"],
            "stopped_reason": _run_out["stopped_reason"],
            "client_effective_rate": _run_out.get(
                "client_effective_rate", 0.0),
            "log_drop_counts": _run_out.get("log_drop_counts", {}),
            "log_dir": _rep_log_dir,
        })

    # top-level fields = replicate 0 for back-compat with flat-envelope consumers; cross-replicate aggregation lives in 07-comparison.ipynb
    _first = _replicates[0]

    _paths: Dict[str, str] = {}
    if wrt:
        _run_out_first = {
            "probes": _first["probes"],
            "saturation_rate": _first["saturation_rate"],
            "stopped_reason": _first["stopped_reason"],
        }
        _paths = _write_results(_cfg, _mcfg, _first["nodes"],
                                _first["network"], _first["requirements"],
                                _run_out_first,
                                baseline=_baseline_block,
                                deployment=_dpl)

    _ans = {
        "config": _cfg,
        "method_config": _mcfg,
        "nodes": _first["nodes"],
        "network": _first["network"],
        "requirements": _first["requirements"],
        "probes": _first["probes"],
        "saturation_rate": _first["saturation_rate"],
        "stopped_reason": _first["stopped_reason"],
        "client_effective_rate": _first.get("client_effective_rate", 0.0),
        "log_drop_counts": _first.get("log_drop_counts", {}),
        "replicates": _replicates,
        "baseline": _baseline_block,
        "paths": _paths,
        "deployment": _dpl,
        "launcher_role": _role,
    }

    # P1.2 invariant: log-buffer overflow == lost observations; warn loud so the operator notices
    if verbose and _ans["log_drop_counts"]:
        print(f"WARNING: per-service log buffer overflowed: "
              f"{_ans['log_drop_counts']}. Raise `SvcCtx.log_maxlen` "
              "or shorten the probe window.")

    return _ans


def _write_results(cfg: NetCfg,
                   method_cfg: Dict[str, Any],
                   nds: pd.DataFrame,
                   net: pd.DataFrame,
                   req: dict,
                   run_out: Dict[str, Any],
                   baseline: Optional[Dict[str, Any]] = None,
                   deployment: str = "local") -> Dict[str, str]:
    """*_write_results()* serialise the run envelope to `<results>/<deployment>/<scenario>/<profile>.json`.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        method_cfg (Dict[str, Any]): method config; copied verbatim into the envelope.
        nds (pd.DataFrame): per-service metrics frame.
        net (pd.DataFrame): network aggregate (one row).
        req (dict): R1 / R2 / R3 verdict dict.
        run_out (Dict[str, Any]): async runtime output (probes, saturation, counts).
        baseline (Optional[Dict[str, Any]]): calibration summary block from `_build_baseline_block`.
        deployment (str): `local` / `loopback_aliased` / `remote`; segment in the output path.

    Returns:
        Dict[str, str]: on-disk paths keyed by `profile` and `requirements`.
    """
    _out_dir = _RESULTS_DIR / deployment / cfg.scenario
    _out_dir.mkdir(parents=True, exist_ok=True)

    # strip per-probe `records` (not JSON-serialisable; per-service CSVs cover the same data)
    _probes_out: List[Dict[str, Any]] = []
    for _p in run_out["probes"]:
        _slim = {_k: _v for _k, _v in _p.items() if _k != "records"}
        _probes_out.append(_slim)

    _doc = {
        "profile": cfg.profile,
        "scenario": cfg.scenario,
        "label": cfg.label,
        "method": "experiment",
        "method_config": method_cfg,
        "deployment": deployment,
        "baseline": baseline or {"applied": False,
                                 "baseline_ref": None,
                                 "loopback_median_us": 0.0,
                                 "jitter_p99_us": 0.0,
                                 "age_hours": None},
        "network": net.iloc[0].to_dict(),
        "nodes": nds.to_dict(orient="records"),
        "probes": _probes_out,
        "saturation_rate": run_out["saturation_rate"],
        "stopped_reason": run_out["stopped_reason"],
        "routing": cfg.routing.tolist(),
        "lambda_z": cfg.build_lam_z_vec().tolist(),
    }

    _profile_path = _out_dir / f"{cfg.profile}.json"
    with _profile_path.open("w", encoding="utf-8") as _fh:
        json.dump(_doc, _fh, indent=4, ensure_ascii=False)

    _req_path = _out_dir / "requirements.json"
    with _req_path.open("w", encoding="utf-8") as _fh:
        json.dump(req, _fh, indent=4, ensure_ascii=False)

    _ans = {"profile": str(_profile_path.relative_to(_ROOT)),
            "requirements": str(_req_path.relative_to(_ROOT))}
    return _ans


def main() -> None:
    """*main()* CLI entry point.

    Parses flags, calls `run()`, and prints a one-screen summary plus the paths of any written files.

    Side Effects:
        Prints summary lines to stdout. When `--no-write` is NOT set, writes `<deployment>/<scenario>/<profile>.json` and `<deployment>/<scenario>/requirements.json` under `data/results/experiment/`, plus per-service CSV logs in the same scenario directory.
    """
    _parser = argparse.ArgumentParser(
        description="Architectural experiment for CS-01 TAS.")

    _parser.add_argument("--adaptation",
                         choices=["baseline", "s1", "s2", "aggregate"],
                         default=None,
                         help="adaptation state")
    _parser.add_argument("--profile",
                         choices=["dflt", "opti"],
                         default=None,
                         help="explicit profile file stem")
    _parser.add_argument("--scenario",
                         default=None,
                         help="explicit scenario name")
    _parser.add_argument("--no-write",
                         action="store_true",
                         help="skip writing result files")
    _parser.add_argument("--skip-calibration",
                         action="store_true",
                         help=("bypass the pre-run calibration gate; "
                               "a warning is printed and the baseline "
                               "is NOT subtracted from reported latencies"))
    _parser.add_argument("--deployment",
                         choices=list(_VALID_DEPLOYMENTS),
                         default=None,
                         help=("deployment mode override; defaults to "
                               "method_cfg['deployment'] (typically 'local'). "
                               "Non-local modes require launch_services.py."))
    _parser.add_argument("--launcher-role",
                         choices=["all", "client", "composite", "atomic",
                                  "composite-atomic"],
                         default=None,
                         help=("subset of services this driver spawns; "
                               "only meaningful in non-local deployments"))

    _args = _parser.parse_args()

    _result = run(adp=_args.adaptation,
                  prf=_args.profile,
                  scn=_args.scenario,
                  wrt=not _args.no_write,
                  skip_calibration=_args.skip_calibration,
                  dpl=_args.deployment,
                  launcher_role=_args.launcher_role)

    _cfg = _result["config"]
    _net = _result["network"].iloc[0]
    _req = _result["requirements"]

    print(f"profile={_cfg.profile}  scenario={_cfg.scenario}")
    print(f"label: {_cfg.label}")
    _base = _result.get("baseline", {})
    if _base.get("applied"):
        _floor_ms = float(_base["loopback_median_us"]) / 1000.0
        _band_ms = float(_base["jitter_p99_us"]) / 1000.0
        _age = _base.get("age_hours")
        print(f"baseline: loopback_median={_floor_ms:.3f}ms  "
              f"jitter_p99={_band_ms:.3f}ms  "
              f"age={_age:.1f}h  "
              f"ref={_base.get('baseline_ref')}")
        print("reported = measured - loopback_median +/- jitter_p99")
    else:
        print("baseline: NOT APPLIED (--skip-calibration)")
    print(f"  nodes={int(_net['nodes'])}  "
          f"avg_rho={_net['avg_rho']:.4f}  "
          f"max_rho={_net['max_rho']:.4f}  "
          f"W_net={_net['W_net']:.6f}s")

    print("requirements:")
    for _k, _v in _req.items():
        if _v["pass"]:
            _status = "PASS"
        else:
            _status = "FAIL"
        _val = _v["value"]
        if isinstance(_val, (int, float)):
            _val_str = f"{_val:.6g}"
        else:
            _val_str = "n/a"
        print(f"  {_k}: {_status}  ({_v['metric']}={_val_str})")

    print("ramp probes:")
    for _p in _result["probes"]:
        print(f"  rate={_p['rate']:>8.1f}  n={_p['total']:>4d}  "
              f"infra_fail={_p['infra_fail_rate']:.3f}  "
              f"biz_fail={_p['business_fail_rate']:.3f}  "
              f"stopped={_p['stopped_reason']}")
    if _result["saturation_rate"] is not None:
        print(f"saturation at rate={_result['saturation_rate']}")

    if _result["paths"]:
        for _k, _p in _result["paths"].items():
            print(f"  wrote {_k}: {_p}")


if __name__ == "__main__":
    main()
