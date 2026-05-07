# -*- coding: utf-8 -*-
"""
Module dimensional/dasa_sweep.py
================================

Multi-combo Route-B DASA-profile sweep across `(c, K, mu_factor)`. For each combo: spin up a fresh vernier with the combo spec, ramp `lambda` from `lambda_factor_min*mu` to `util_threshold*mu*c` across `lambda_steps` deterministic target rates, drive each step for `max_probe_window_s` seconds, aggregate latencies into a synthetic `handler_scaling`-shaped block, and feed that to `derive_calib_coefs` (sibling in this package). Returns nested `{combo_tag: per_combo_card}` matching the shape `src.view.plot_yoly_chart` consumes.

Lives in `src/dimensional/` because the multi-combo sweep is a dimensional-method sensitivity study (not a host-floor probe). Sibling to:

- `dasaprof.py::derive_calib_coefs`: single-host dim card from a calibration envelope.
- `coefficients.py::derive_coefs`: TAS-architecture Pi-indexed coefficient derivation.

Public API:
    - `run_calib_sweep(envelope, sweep_grid, write, verbose)`: drive every `(c, K, mu_factor)` combo and return the nested per-combo dim cards.
"""
# native python modules
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# scientific stack
import numpy as np

# web stack
from fastapi import FastAPI

# local modules
from src.calibration.envelope import _CALIB_ROOT, _normalise_host
from src.calibration.hoststats import _build_probe_body
from src.calibration.rate import _drive_lambda_step
from src.dimensional.dasaprof import derive_calib_coefs
from src.experiment.instances import make_gauge_factory
from src.experiment.runtime import UvicornThread, run_async_safe
from src.experiment.services import SvcSpec


# defaults; the orchestrator (Stage C9 thin shim in `src/methods/calibration.py`) passes JSON-loaded values explicitly
_DEFAULT_PORT: int = 8765
_DEFAULT_READY_TIMEOUT_S: float = 2.0
_DEFAULT_PAYLOAD_SIZE_BYTES: int = 128000
_DEFAULT_INTER_COMBO_DELAY_S: float = 3.0
_DEFAULT_PROBE_WINDOW_S: float = 1.5


def _build_vernier_app_for_combo(c_srv: int,
                                 K: int,
                                 mu: float,
                                 epsilon: float,
                                 payload_size_bytes: int,
                                 tag: str) -> FastAPI:
    """*_build_vernier_app_for_combo()* build a vernier app with explicit per-combo `(c, K, mu, epsilon)` knobs.

    The host-floor gauge in `src.calibration.hoststats` forces `mu = epsilon = 0` and reads `(c, K)` from the first JSON entries; the multi-combo sweep needs to override every knob per combo, so this helper accepts them as arguments and routes through `make_gauge_factory` for spawn-friendliness.

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
                    mem_per_buffer=int(payload_size_bytes * K
                                       * SvcSpec.MEM_HEADROOM_FACTOR))
    _factory = make_gauge_factory(_spec, payload_size_bytes=payload_size_bytes)
    return _factory()


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
                           ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
                           lambda_min_req_per_s: Optional[float] = None,
                           lambda_max_req_per_s: Optional[float] = None,
                           ) -> Dict[str, Dict[str, float]]:
    """*_drive_one_combo()* stand up a vernier with the combo spec, ramp lambda, return synthetic handler_scaling.

    Each lambda step keys the result by `int(round(target_rate * window_s))` (the count of arrivals dispatched in the probe window) so downstream `derive_calib_coefs` can read `n` per level the same way it reads `n_con_usr` from the host-floor block. Uvicorn lifecycle is fully contained: spawn, ready-poll, drive, shutdown.

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
        tag (str): combo's LaTeX-subscript artifact name; encoding `CALIBc<c>K<K>m<int(mu_factor*100)>`. Axes concatenated without dots / underscores because sympy's LaTeX parser treats `.` as multiplication and `_` as a nested subscript marker.
        port (int): TCP port for this combo's uvicorn (caller picks dynamically).
        ready_timeout_s (float): seconds to wait for uvicorn readiness.
        lambda_min_req_per_s (Optional[float]): absolute lower clamp on the ramp.
        lambda_max_req_per_s (Optional[float]): absolute upper clamp on the ramp.

    Returns:
        Dict[str, Dict[str, float]]: synthetic handler_scaling block, one entry per lambda step. Empty when the clamped band collapses (`_lam_hi <= _lam_lo`).
    """
    _app = _build_vernier_app_for_combo(c_srv=c_srv,
                                        K=K,
                                        mu=mu_combo,
                                        epsilon=0.0,
                                        payload_size_bytes=payload_size_bytes,
                                        tag=tag)
    _server = UvicornThread(_app, port=port)
    _server.start()
    _result: Dict[str, Dict[str, float]] = {}
    try:
        _server.wait_ready(timeout_s=ready_timeout_s)
        _body = _build_probe_body(payload_size_bytes)
        _lam_lo = float(lambda_factor_min) * float(mu_combo)
        _lam_hi = float(util_threshold) * float(mu_combo) * float(c_srv)
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
            _level = max(int(round(float(_lam) * float(probe_window_s))), 1)
            _result[str(_level)] = _stats
    finally:
        _server.shutdown()
    return _result


def _resolve_sweep_grid(sweep_grid: Optional[Dict[str, Any]]
                        ) -> Dict[str, Any]:
    """*_resolve_sweep_grid()* return the explicit sweep_grid argument or fall back to JSON config.

    The fallback reads `data/config/method/calibration.json::sweep_grid` lazily so this module's import surface stays light.

    Args:
        sweep_grid (Optional[Dict[str, Any]]): explicit grid override; None falls back to JSON.

    Returns:
        Dict[str, Any]: resolved grid; empty dict when neither source provides one.
    """
    if sweep_grid is not None:
        return dict(sweep_grid)
    from src.io import load_method_cfg  # noqa: WPS433
    _cfg = load_method_cfg("calibration")
    return dict(_cfg.get("sweep_grid", {}))


def _build_sweep_output_path(profile: Dict[str, Any],
                             stamp: Optional[str] = None) -> Path:
    """*_build_sweep_output_path()* build the per-host sweep envelope path under `data/results/calibration/localhost/<host>_<ts>_sweep.json`.

    Mirrors the host-envelope path shape (Q-B locked) with a `_sweep` suffix on the stem so the file pairs cleanly with the host envelope it was derived from.

    Args:
        profile (Dict[str, Any]): host profile dict (`hostname` field consulted).
        stamp (Optional[str]): timestamp; defaults to `datetime.now().strftime("%Y%m%d_%H%M%S")`.

    Returns:
        Path: resolved per-host sweep path.
    """
    _host = _normalise_host(profile.get("hostname"))
    if stamp is None:
        _stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        _stamp = str(stamp)
    return _CALIB_ROOT / "localhost" / f"{_host}_{_stamp}_sweep.json"


def run_calib_sweep(envelope: Dict[str, Any],
                    sweep_grid: Optional[Dict[str, Any]] = None,
                    *,
                    write: bool = True,
                    verbose: bool = True) -> Dict[str, Dict[str, Any]]:
    """*run_calib_sweep()* drive vernier across `(c, K, mu_factor)` and derive the dim card per combo.

    For each combo: spin up a fresh vernier, ramp lambda, aggregate latencies into a synthetic `handler_scaling`-shaped block, and feed that to `src.dimensional.dasaprof.derive_calib_coefs`. Per-combo `mu` resolves through `_resolve_mu_anchor` (explicit `sweep_grid.mu_anchor_req_per_s` first, then the named `mu_anchor_source`). Inter-combo waits read `inter_combo_delay_s` from the JSON config so uvicorn rebinds and TIME_WAIT drains cleanly between combos.

    Args:
        envelope (Dict[str, Any]): host calibration envelope; carries `loopback.median_us` (default mu anchor) and `host_profile` (output path).
        sweep_grid (Optional[Dict[str, Any]]): cartesian grid; falls back to `calibration.json::sweep_grid` when None. Required keys: `mu_factor` (List[float]), `c` (List[int]), `K` (List[int]), `lambda_steps` (int), `lambda_factor_min` (float), `util_threshold` (float). Optional: `mu_anchor_req_per_s`, `mu_anchor_source`, `max_probe_window_s`, `lambda_min_req_per_s`, `lambda_max_req_per_s`.
        write (bool): persist the result envelope under `data/results/calibration/localhost/<host>_<ts>_sweep.json`.
        verbose (bool): print one progress line per combo.

    Returns:
        Dict[str, Dict[str, Any]]: nested `{combo_tag: per_combo_card}`. Each per-combo block carries the same keys as `derive_calib_coefs` returns. Empty dict when the envelope lacks `loopback`, the grid is empty, or the mu anchor cannot be resolved.
    """
    _grid = _resolve_sweep_grid(sweep_grid)
    if not _grid:
        return {}

    _mu_anchor, _mu_source = _resolve_mu_anchor(envelope, _grid)
    if _mu_anchor <= 0.0:
        return {}

    _payload_bytes = int(_DEFAULT_PAYLOAD_SIZE_BYTES)
    _inter_combo_s = float(_DEFAULT_INTER_COMBO_DELAY_S)
    _probe_window_s = float(_grid.get("max_probe_window_s",
                                      _DEFAULT_PROBE_WINDOW_S))
    _mu_factors = [float(_v) for _v in _grid.get("mu_factor", [1.0])]
    _cs = [int(_v) for _v in _grid.get("c", [1])]
    _Ks = [int(_v) for _v in _grid.get("K", [50])]
    _lambda_steps = int(_grid.get("lambda_steps", 20))
    _lambda_factor_min = float(_grid.get("lambda_factor_min", 0.05))
    _util_threshold = float(_grid.get("util_threshold", 0.95))
    _lambda_min_abs = _grid.get("lambda_min_req_per_s")
    _lambda_max_abs = _grid.get("lambda_max_req_per_s")
    if _lambda_min_abs is not None:
        _lambda_min_abs = float(_lambda_min_abs)
    if _lambda_max_abs is not None:
        _lambda_max_abs = float(_lambda_max_abs)

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
                    _mu_factor_tag = int(round(float(_mu_factor) * 100))
                    _tag = f"CALIBc{_c_val}K{_K_val}m{_mu_factor_tag}"
                    if verbose:
                        print(f"  [{_combo_idx}/{_total}] {_tag} "
                              f"mu={_mu_combo:.1f} req/s ...", flush=True)
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
                            print("      band collapsed (mu*c below lambda_min); skipping",
                                  flush=True)
                        continue
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
                            print("      empty card; skipping", flush=True)
                        continue
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
                    if _combo_idx < _total and _inter_combo_s > 0.0:
                        await asyncio.sleep(_inter_combo_s)
        return _out

    _sweep = run_async_safe(_orchestrate)  # type: ignore[arg-type]

    if write and _sweep:
        _profile = envelope.get("host_profile") or {}
        _path = _build_sweep_output_path(_profile)
        _path.parent.mkdir(parents=True, exist_ok=True)
        _envelope_out: Dict[str, Any] = {
            "host_profile": _profile,
            "mu_anchor_req_per_s": float(_mu_anchor),
            "mu_anchor_source": _mu_source,
            "sweep_grid": _grid,
            "combos": _sweep,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_envelope_out, _fh, indent=2, default=str)
        if verbose:
            print(f"  wrote: {_path}", flush=True)

    return _sweep
