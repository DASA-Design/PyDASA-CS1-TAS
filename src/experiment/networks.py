# -*- coding: utf-8 -*-
"""
Module networks.py
==================

Configuration-sweep helper for the experimental method's yoly-experimental notebook.

Mirror of `src.dimensional.networks.sweep_arch` in shape, but each sweep point spins up the FastAPI mesh and measures real per-node metrics instead of solving the M/M/c/K closed form. Returns the same nested `{artifact_key: {full_symbol: ndarray}}` shape, so `aggregate_sweep_to_arch`, `plot_yoly_chart`, `plot_system_behaviour`, and the per-node grid plotters work unchanged.

Only one sweep:

    - `sweep_arch_exp(cfg, sweep_grid, *, method_cfg, adp)` walks the `(mu_factor, c, K)` grid; at each combo it overrides every node's mu / c / K, launches the mesh once, and collects one coefficient point per artifact from the aggregated `nodes` DataFrame.

Coefficients (same closed form as `src.dimensional.networks`):

    - theta = L / K              (Occupancy)
    - sigma = lambda * W / L     (Stall, Little's-law identity)
    - eta   = chi * K / (mu * c) (Effective-yield)
    - phi   = L / K              (Memory-use, collapses to theta in CS-01 TAS schema)

*IMPORTANT:* each sweep point is one full mesh launch + ramp; budget ~30 s
per combo. Use a small grid (3 mu_factors x 2 c x 2 K = 12 combos minimum)
unless you have hours to spare.
"""
# native python modules
from __future__ import annotations

import asyncio
import copy
import tempfile
from dataclasses import replace
from pathlib import Path

# data types
from typing import Any, Dict, Iterable, List

# scientific stack
import numpy as np

# local modules
from src.io import ArtifactSpec, NetCfg


def _override_artifact(art: ArtifactSpec,
                       *,
                       mu: float,
                       c_int: int,
                       K_int: int) -> ArtifactSpec:
    """*_override_artifact()* return a copy of `art` with mu / c / K setpoints overridden inside its vars block.

    The frozen `ArtifactSpec` is rebuilt via `dataclasses.replace`; the vars
    dict is deep-copied so per-combo mutations do not leak back into the
    caller's NetCfg.

    Args:
        art (ArtifactSpec): source spec.
        mu (float): new mu setpoint.
        c_int (int): new c setpoint.
        K_int (int): new K setpoint.

    Returns:
        ArtifactSpec: new spec carrying the overridden setpoints.
    """
    _vars = copy.deepcopy(art.vars)
    _key = art.key

    _mu_sym = f"\\mu_{{{_key}}}"
    _c_sym = f"c_{{{_key}}}"
    _K_sym = f"K_{{{_key}}}"

    if _mu_sym in _vars:
        _vars[_mu_sym]["_setpoint"] = float(mu)
    if _c_sym in _vars:
        _vars[_c_sym]["_setpoint"] = int(c_int)
    if _K_sym in _vars:
        _vars[_K_sym]["_setpoint"] = int(K_int)

    return replace(art, vars=_vars)


def _override_cfg(cfg: NetCfg,
                  *,
                  mu_factor: float,
                  c_int: int,
                  K_int: int) -> NetCfg:
    """*_override_cfg()* rebuild `cfg` with per-node mu scaled by `mu_factor` and uniform c / K overrides.

    Args:
        cfg (NetCfg): source resolved network configuration.
        mu_factor (float): multiplicative scale applied to each artifact's seeded mu.
        c_int (int): uniform server-count override across every node.
        K_int (int): uniform capacity override across every node.

    Returns:
        NetCfg: new configuration carrying the overridden artifact specs.
    """
    _new_arts: List[ArtifactSpec] = []
    for _a in cfg.artifacts:
        _mu = float(_a.mu) * float(mu_factor)
        _new_arts.append(_override_artifact(_a,
                                            mu=_mu,
                                            c_int=c_int,
                                            K_int=K_int))
    return replace(cfg, artifacts=_new_arts)


def _empty_per_art(art_keys: Iterable[str]) -> Dict[str, Dict[str, List[float]]]:
    """*_empty_per_art()* allocate the per-artifact accumulator skeleton.

    Args:
        art_keys (Iterable[str]): artifact identifiers in LaTeX subscript form.

    Returns:
        Dict[str, Dict[str, List[float]]]: nested empty-list accumulators.
    """
    _per_art: Dict[str, Dict[str, List[float]]] = {}
    for _k in art_keys:
        _per_art[_k] = {
            f"\\theta_{{{_k}}}": [],
            f"\\sigma_{{{_k}}}": [],
            f"\\eta_{{{_k}}}": [],
            f"\\phi_{{{_k}}}": [],
            f"c_{{{_k}}}": [],
            f"\\mu_{{{_k}}}": [],
            f"K_{{{_k}}}": [],
            f"\\lambda_{{{_k}}}": [],
        }
    return _per_art


def sweep_arch_exp(cfg: NetCfg,
                   sweep_grid: Dict[str, Any],
                   *,
                   method_cfg: Dict[str, Any],
                   adp: str = "baseline",
                   util_threshold: float = 0.95
                   ) -> Dict[str, Dict[str, np.ndarray]]:
    """*sweep_arch_exp()* prototype-driven whole-network sweep; mirrors `src.dimensional.networks.sweep_arch` but launches the FastAPI mesh per combo instead of solving M/M/c/K.

    For each `(mu_factor, c, K)` combo in `sweep_grid`:

    1. Override every node's mu / c / K via `_override_cfg`.
    2. Spin up the mesh inside a temp log dir and run the configured ramp
       (`method_cfg.ramp.rates`) end-to-end.
    3. Build the per-node DataFrame from the flushed CSV logs.
    4. Per artifact: derive theta / sigma / eta / phi from L, W, lambda,
       epsilon, mu, c, K. Skip nodes where lambda or L collapsed to 0
       (idle artifacts produce no measurement).
    5. Drop combos where any node hit `rho >= util_threshold` so the cloud
       only contains feasible designs (matches the dimensional convention).

    Args:
        cfg (NetCfg): resolved network configuration (profile + scenario).
        sweep_grid (Dict[str, Any]): grid declared in `data/config/method/experiment.json::sweep_grid`. Required keys: `mu_factor`, `c`, `K`. Optional: `util_threshold` (overrides the kwarg).
        method_cfg (Dict[str, Any]): experiment method config; the per-combo run reuses its `ramp` block, `seed`, and `request_size_bytes`.
        adp (str): adaptation label passed to the launcher (`baseline` / `s1` / `s2` / `aggregate`). Defaults to `"baseline"`.
        util_threshold (float): drop combos with any per-node rho at or above this. Defaults to `0.95`.

    Returns:
        Dict[str, Dict[str, np.ndarray]]: nested `{artifact_key: per_artifact_sweep}`. Per-artifact dict shape matches `src.dimensional.networks.sweep_arch` so the same plotters consume both.
    """
    # local import: src.methods.experiment depends on src.experiment, so
    # importing it at module-top would create a circular import
    from src.methods.experiment import _build_svc_df_from_logs, _run_async

    # resolve thresholds + grid knobs (kwarg wins over grid value when set)
    _util = float(sweep_grid.get("util_threshold", util_threshold))
    _mu_factors = sweep_grid.get("mu_factor", [1.0])
    _c_vals = sweep_grid.get("c", [1])
    _K_vals = sweep_grid.get("K", [10])

    # per-node accumulators (lists now, ndarrays at return time)
    _art_keys = [_a.key for _a in cfg.artifacts]
    _per_art = _empty_per_art(_art_keys)

    # walk the (mu_factor, c, K) grid; one combo per (sub-)point in the cloud
    for _mf in _mu_factors:
        for _c in _c_vals:
            _c_int = int(_c)
            for _K in _K_vals:
                _K_int = int(_K)
                if _K_int < _c_int:
                    continue

                # rebuild cfg with the per-combo overrides; the launcher
                # reads mu / c / K via ArtifactSpec properties so the
                # mutated vars block is what the mesh actually deploys
                _cfg_combo = _override_cfg(cfg,
                                           mu_factor=float(_mf),
                                           c_int=_c_int,
                                           K_int=_K_int)

                # one launch per combo; logs land in a throwaway temp dir
                with tempfile.TemporaryDirectory() as _tmp_str:
                    _log_dir = Path(_tmp_str)
                    try:
                        _run_out = asyncio.run(_run_async(_cfg_combo,
                                                          method_cfg,
                                                          adp,
                                                          _log_dir))
                    except Exception:
                        # mesh launch / ramp failure -> skip this combo
                        continue
                    _nds = _build_svc_df_from_logs(_cfg_combo,
                                                   _log_dir,
                                                   _run_out["duration_s"])

                # combo-wide stability gate: drop the whole combo if any
                # node saturated, mirroring the dimensional sweep's
                # first-node-to-saturate convention
                if (_nds["rho"] >= _util).any():
                    continue

                # one coefficient point per artifact for this combo
                for _a in _cfg_combo.artifacts:
                    _row = _nds.loc[_nds["key"] == _a.key]
                    if _row.empty:
                        continue
                    _row = _row.iloc[0]

                    _lam = float(_row["lambda"])
                    _L = float(_row["L"])
                    _W = float(_row["W"])
                    _eps = float(_row["epsilon"])
                    _mu = float(_a.mu)

                    # idle / failed measurements have no coefficient signal
                    if _lam <= 0 or _L <= 0:
                        continue

                    _chi = _lam * (1.0 - _eps)
                    _theta = _L / _K_int
                    _sigma = _lam * _W / _L
                    _eta = _chi * _K_int / (_mu * _c_int)
                    _phi = _L / _K_int

                    _k = _a.key
                    _per_art[_k][f"\\theta_{{{_k}}}"].append(_theta)
                    _per_art[_k][f"\\sigma_{{{_k}}}"].append(_sigma)
                    _per_art[_k][f"\\eta_{{{_k}}}"].append(_eta)
                    _per_art[_k][f"\\phi_{{{_k}}}"].append(_phi)
                    _per_art[_k][f"c_{{{_k}}}"].append(float(_c_int))
                    _per_art[_k][f"\\mu_{{{_k}}}"].append(_mu)
                    _per_art[_k][f"K_{{{_k}}}"].append(float(_K_int))
                    _per_art[_k][f"\\lambda_{{{_k}}}"].append(_lam)

    # cast accumulators to ndarrays for plotter compatibility
    _out: Dict[str, Dict[str, np.ndarray]] = {}
    for _k, _block in _per_art.items():
        _out[_k] = {_s: np.asarray(_v, dtype=float) for _s, _v in _block.items()}
    return _out
