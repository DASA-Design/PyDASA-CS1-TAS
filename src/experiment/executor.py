# -*- coding: utf-8 -*-
"""
Module experiment/executor.py
=============================

Cell driver: pairs `TasArchitecture` and `TasUser` for one `(profile, scenario, adaptation)`, runs the configured ramp end-to-end, and reports back. Also owns the cartesian-grid sweep behind the yoly notebooks and the operational-analysis helper that turns flushed CSVs into a per-service metrics frame.

Public API:
    - `execute_one` drive one cell end-to-end through `launch -> snapshot -> ramp -> flush`.
    - `execute_sweep` walk a `(mu_factor, c, K)` cartesian grid; one cell per combo; drops combos at the saturation cap.
    - `build_svc_df_from_logs` per-service metrics from flushed CSV logs (Denning & Buzen 1978; see `notes/operational_analysis.md`).

Layering: consumed by `methods/experiment.py`; never imports UP. OS-boundary helpers live in `src.experiment.runtime`.
"""
# native python modules
from __future__ import annotations

import copy
import tempfile
from dataclasses import replace
from pathlib import Path

# data types
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

# scientific stack
import numpy as np
import pandas as pd

# local modules
from src.analytic.jackson import build_rho_grid
from src.experiment.architecture import TasArchitecture
from src.experiment.client import ClientCfg
from src.experiment.runtime import run_async_safe, windows_timer_resolution
from src.experiment.users import TasUser
from src.io import ArtifactSpec, NetCfg, load_client_cfg


def _resolve_rates(cfg: NetCfg,
                   ramp_block: Dict[str, Any]
                   ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """*_resolve_rates()* expand `rho_grid` (Jackson inversion) or `anchor: "lambda_z"` (read entry artifact) into explicit `rates`; pure passthrough when neither key is set.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        ramp_block (Dict[str, Any]): the `method_cfg["ramp"]` block.

    Returns:
        Tuple[Dict[str, Any], List[Dict[str, Any]]]: ramp block with `rates` filled in (`rho_grid` / `anchor` / `entry_artifact` stripped); per-point metadata, empty when no expansion happened.
    """
    _block = dict(ramp_block)
    _meta: List[Dict[str, Any]] = []
    if _block.get("rho_grid"):
        _grid = build_rho_grid(cfg, list(_block["rho_grid"]))
        _block["rates"] = [float(_lz) for (_, _lz, _) in _grid]
        _block.pop("rho_grid", None)
        _meta = [
            {"rho_target": float(_r),
             "lambda_z_inverted": float(_lz),
             "bottleneck_artifact_idx": int(_b)}
            for (_r, _lz, _b) in _grid
        ]
    elif _block.get("anchor") == "lambda_z":
        _entry = str(_block.get("entry_artifact", "TAS_{1}"))
        _lam_z = _read_artifact_lambda_z(cfg, _entry)
        _block["rates"] = [_lam_z]
        _block.pop("anchor", None)
        _block.pop("entry_artifact", None)
        _meta = [{"anchor": "lambda_z",
                  "entry_artifact": _entry,
                  "lambda_z_used": _lam_z}]
    return _block, _meta


def _read_artifact_lambda_z(cfg: NetCfg, entry: str) -> float:
    """*_read_artifact_lambda_z()* seeded external arrival rate of one entry artifact.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        entry (str): artifact key (e.g. ``"TAS_{1}"``).

    Returns:
        float: `lambda_z` in req/s.

    Raises:
        KeyError: when `entry` is not present in `cfg.artifacts`.
    """
    for _a in cfg.artifacts:
        if _a.key == entry:
            return float(_a.lambda_z)
    _msg = f"entry artifact {entry!r} not in cfg.artifacts"
    raise KeyError(_msg)


def _build_client_cfg(method_cfg: Dict[str, Any],
                      arch: TasArchitecture,
                      ramp_block: Dict[str, Any]) -> ClientCfg:
    """*_build_client_cfg()* materialise the `ClientCfg` for this cell.

    Args:
        method_cfg (Dict[str, Any]): experiment method config (seed + per-kind sizes).
        arch (TasArchitecture): live prototype component (kind_prob consumed).
        ramp_block (Dict[str, Any]): ramp block AFTER `_resolve_rates` has expanded any rho_grid.

    Returns:
        ClientCfg: ready to thread into a `TasUser`.
    """
    _resolved_cfg = dict(method_cfg)
    _resolved_cfg["ramp"] = ramp_block
    return load_client_cfg(_resolved_cfg, kind_prob=dict(arch.kind_prob))


# --- single-cell entry point ----------------------------------------------


async def execute_one(cfg: NetCfg,
                      method_cfg: Dict[str, Any],
                      adp: str,
                      log_dir: Path,
                      dpl: str = "localhost",
                      launcher_role: str = "all") -> Dict[str, Any]:
    """*execute_one()* drive one cell end-to-end through launch, snapshot, ramp, flush.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        method_cfg (Dict[str, Any]): experiment method config.
        adp (str): adaptation label (`baseline` / `s1` / `s2` / `aggregate`).
        log_dir (Path): directory for the per-service CSVs and the config snapshot.
        dpl (str): deployment mode (`localhost` / `multiprocess` / `remote`).
        launcher_role (str): which services this launcher hosts.

    Returns:
        Dict[str, Any]: ramp envelope plus `duration_s`, `service_log_counts`, `log_drop_counts`.

    Raises:
        Exception: errors from `TasArchitecture` / `TasUser.run_ramp` / `flush_logs` / `snapshot_config` propagate unmodified so the caller can retry or abort.
    """
    # 1 ms timer resolution for the lifetime of this run; no-op off-Windows.
    with windows_timer_resolution(1):
        async with TasArchitecture(cfg=cfg,
                                   method_cfg=method_cfg,
                                   adaptation=adp,
                                   deployment=dpl,
                                   launcher_role=launcher_role) as _arch:
            if _arch.client is None or _arch.registry is None:
                _msg = "TasArchitecture.__aenter__ did not populate client / registry"
                raise RuntimeError(_msg)
            _ramp_block, _rho_grid_meta = _resolve_rates(
                cfg, dict(method_cfg["ramp"]))
            _patched_method_cfg = dict(method_cfg)
            _patched_method_cfg["ramp"] = _ramp_block

            # emit config.json BEFORE the ramp starts so a crash leaves the snapshot describing what was about to run.
            _seed = int(method_cfg["seed"])
            _sizes_by_kind = dict(method_cfg.get("request_size_bytes", {}))
            _req_size = int(_sizes_by_kind.get("analyse_request", 256))
            _arch.snapshot_config(log_dir,
                                  extras={
                                      "seed": _seed,
                                      "request_size_bytes": _req_size,
                                      "request_size_bytes_by_kind": _sizes_by_kind,
                                      "ramp": method_cfg.get("ramp", {}),
                                      "entry_service": "TAS_{1}",
                                  })

            async with TasUser(client=_arch.client,
                               registry=_arch.registry,
                               method_cfg=_patched_method_cfg,
                               kind_prob=dict(_arch.kind_prob)) as _user:
                _ramp_out = await _user.run_ramp()
            _counts = _arch.flush_logs(log_dir)
            # surface log-buffer overflow so the top-level envelope can fail loudly on non-zero.
            _drops = _arch.collect_drop_counts()

    # thread rho_grid per-point metadata back into each probe so downstream knows which rho-target it was anchored to.
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


# --- log post-processing --------------------------------------------------


def build_svc_df_from_logs(cfg: NetCfg,
                           log_dir: Path,
                           duration_s: float) -> pd.DataFrame:
    """*build_svc_df_from_logs()* per-service metrics frame from flushed CSV logs via operational analysis (no Markovian assumption; every quantity is a direct measurement over window `T`).

    Identities used (cf. `notes/operational_analysis.md` Table I):

        - **lambda** = `A / T` (arrival rate from logged invocations).
        - **X** = `C / T` (throughput, completion rate).
        - **U_local** (`rho`) = `B_local / (T * c)`; M/M/c/K-comparable, excludes downstream wait.
        - **R_local** (`W`) = mean(`local_end_ts - recv_ts`); used for analytic / stochastic / dimensional cross-checks.
        - **Wq** = mean(`start_ts - recv_ts`); positive only when admission gating makes requests wait.
        - **L** = `X * W`, **Lq** = `X * Wq` (Little's law on local response, on queue wait).
        - **U_total** (`rho_total`) = `B_total / (T * c)`; client-perceived end-to-end utilisation.
        - **W_total** = mean(`end_ts - recv_ts`); used for Camara R2 (W <= 26 ms) validation.
        - **L_total** = `X * W_total` (system-wide in-flight).

    Failure modes split: `epsilon` = `count(200 AND success=False) / count(200)` is business-level (compares to profile setpoint); `buffer_reject_rate` = `count(503) / count(all)` is capacity overflow.

    Args:
        cfg (NetCfg): resolved profile + scenario.
        log_dir (Path): directory carrying `<service>.csv` files.
        duration_s (float, seconds): observation window `T`.

    Returns:
        pd.DataFrame: one row per artifact with the analytic-schema columns plus `buffer_reject_rate`.

    Raises:
        pandas.errors.EmptyDataError: when a per-service CSV exists but is empty (zero rows including header). Missing CSVs produce zero-filled rows.
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

            # timing from successful completions only; local view brackets local work via local_end_ts (M/M/c/K-comparable), total view brackets the whole subtree via end_ts (client-perceived).
            _succ = _completed[_completed["success"]]
            if len(_succ) > 0 and duration_s > 0:
                _start = pd.to_numeric(_succ["start_ts"], errors="coerce")
                _local_end = pd.to_numeric(_succ["local_end_ts"], errors="coerce")
                _end = pd.to_numeric(_succ["end_ts"], errors="coerce")
                _recv = pd.to_numeric(_succ["recv_ts"], errors="coerce")

                # local response R_local = mean(local_end - recv); queue wait Wq = mean(start - recv); total response R_total = mean(end - recv).
                _W = float(np.nanmean(_local_end - _recv))
                _Wq = float(np.nanmean(_start - _recv))
                _W_total = float(np.nanmean(_end - _recv))

                # operational U = B / (T*c); local B excludes downstream wait, total B includes it.
                _B_local = float(np.nansum(_local_end - _start))
                _B_total = float(np.nansum(_end - _start))
                _c = max(int(_a.c), 1)
                _rho = _B_local / (duration_s * _c)
                _rho_total = _B_total / (duration_s * _c)

                # X = C / T; use in Little's law so failed completions don't inflate L.
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


# --- sweep helpers --------------------------------------------------------


def _override_artifact(art: ArtifactSpec,
                       *,
                       mu: float,
                       c_int: int,
                       K_int: int) -> ArtifactSpec:
    """*_override_artifact()* return a copy of `art` with mu / c / K setpoints overridden inside its vars block.

    Args:
        art (ArtifactSpec): source spec.
        mu (float, req/s): new service-rate setpoint.
        c_int (int, server count): new c-permit setpoint.
        K_int (int, buffer capacity): new K-gate setpoint.

    Returns:
        ArtifactSpec: new spec carrying the overridden setpoints; the vars dict is deep-copied so per-combo mutations do not leak back into the caller's NetCfg.
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
        mu_factor (float, unitless): multiplicative scale applied to each artifact's seeded mu.
        c_int (int, server count): uniform c-permit override across every node.
        K_int (int, buffer capacity): uniform K-gate override across every node.

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
        Dict[str, Dict[str, List[float]]]: nested empty-list accumulators ready for `.append`.
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


def _iter_grid(mu_factors: Iterable[float],
               c_vals: Iterable[int],
               K_vals: Iterable[int]
               ) -> Iterator[Tuple[float, int, int]]:
    """*_iter_grid()* yield `(mu_factor, c_int, K_int)` combos, skipping any with `K < c` (an unfeasible buffer / server combination).

    Args:
        mu_factors (Iterable[float]): mu-scale multipliers.
        c_vals (Iterable[int]): server counts.
        K_vals (Iterable[int]): buffer capacities.

    Yields:
        Tuple[float, int, int]: one feasible combo per yield.
    """
    for _mf in mu_factors:
        for _c in c_vals:
            _c_int = int(_c)
            for _K in K_vals:
                _K_int = int(_K)
                if _K_int < _c_int:
                    continue
                yield float(_mf), _c_int, _K_int


def _run_one_combo(cfg_combo: NetCfg,
                   method_cfg: Dict[str, Any],
                   adp: str) -> Optional[pd.DataFrame]:
    """*_run_one_combo()* launch the mesh once for `cfg_combo`, run the ramp, build the per-node DataFrame from the flushed logs.

    Args:
        cfg_combo (NetCfg): per-combo overridden configuration.
        method_cfg (Dict[str, Any]): experiment method config (ramp + sizes + seed).
        adp (str): adaptation label.

    Returns:
        Optional[pd.DataFrame]: per-node DataFrame on success; `None` on launch / ramp failure so the sweep can skip the combo.
    """
    with tempfile.TemporaryDirectory() as _tmp_str:
        _log_dir = Path(_tmp_str)
        try:
            _run_out = run_async_safe(
                lambda: execute_one(cfg_combo,
                                    method_cfg,
                                    adp,
                                    _log_dir))
        except (RuntimeError, OSError, ConnectionError):
            # mesh launch / ramp failure -> skip this combo so genuine bugs still propagate
            return None
        _nds = build_svc_df_from_logs(cfg_combo,
                                      _log_dir,
                                      _run_out["duration_s"])
    return _nds


def _derive_combo_coefs(row: pd.Series,
                        art: ArtifactSpec,
                        c_int: int,
                        K_int: int) -> Optional[Dict[str, float]]:
    """*_derive_combo_coefs()* derive theta / sigma / eta / phi (plus c / mu / K / lambda bookkeeping) for one artifact-combo pair.

    Coefficient definitions (Route B, measured):

        - theta = L / K
        - sigma = lambda * W / K
        - eta   = chi * K / (mu * c) where chi = lambda * (1 - epsilon)
        - phi   = (L * delta) / (K * delta); reduces to L/K under constant payload

    Idle / failed measurements (`lambda <= 0` or `L <= 0`) return `None` so the sweep skips them; payload `delta` defaults to 1 kB when the artifact has no `d_{<key>}` variable.

    Args:
        row (pd.Series): per-node DataFrame row for this artifact (from `build_svc_df_from_logs`).
        art (ArtifactSpec): artifact spec; supplies mu and the `d_{<key>}` payload.
        c_int (int, server count): combo's c override.
        K_int (int, buffer capacity): combo's K override.

    Returns:
        Optional[Dict[str, float]]: coefficient point keyed by full LaTeX symbol; `None` when the row is idle.
    """
    _lam = float(row["lambda"])
    _L = float(row["L"])
    _W = float(row["W"])
    _eps = float(row["epsilon"])
    _mu = float(art.mu)

    # idle / failed measurements have no coefficient signal
    if _lam <= 0 or _L <= 0:
        return None

    # per-artifact per-request payload (kB); 1 kB fallback when missing
    _d_sym = f"d_{{{art.key}}}"
    if _d_sym in art.vars:
        _delta_kB = float(art.vars[_d_sym]["_setpoint"])
    else:
        _delta_kB = 1.0

    _chi = _lam * (1.0 - _eps)
    _theta = _L / K_int
    _sigma = _lam * _W / float(K_int)
    _eta = _chi * K_int / (_mu * c_int)
    # phi = M_act/M_buf with explicit delta; reduces to L/K under constant payload (sanity-check)
    _m_act = _L * _delta_kB
    _m_buf = K_int * _delta_kB
    if _m_buf > 0:
        _phi = _m_act / _m_buf
    else:
        _phi = float("nan")

    _k = art.key
    return {
        f"\\theta_{{{_k}}}": _theta,
        f"\\sigma_{{{_k}}}": _sigma,
        f"\\eta_{{{_k}}}": _eta,
        f"\\phi_{{{_k}}}": _phi,
        f"c_{{{_k}}}": float(c_int),
        f"\\mu_{{{_k}}}": _mu,
        f"K_{{{_k}}}": float(K_int),
        f"\\lambda_{{{_k}}}": _lam,
    }


# --- sweep entry point ----------------------------------------------------


def execute_sweep(cfg: NetCfg,
                  sweep_grid: Dict[str, Any],
                  *,
                  method_cfg: Dict[str, Any],
                  adp: str = "baseline",
                  util_threshold: float = 0.95
                  ) -> Dict[str, Dict[str, np.ndarray]]:
    """*execute_sweep()* prototype-driven whole-network sweep; same shape as `src.dimensional.networks.sweep_arch` but each combo launches the FastAPI mesh instead of solving M/M/c/K.

    Per combo: override mu / c / K, run the ramp, build the per-node frame from flushed logs, drop the whole combo if any node hits the saturation cap, derive theta / sigma / eta / phi for each artifact (idle nodes skipped).

    Args:
        cfg (NetCfg): resolved network configuration (profile + scenario).
        sweep_grid (Dict[str, Any]): grid from `data/config/method/experiment.json::sweep_grid`. Required keys: `mu_factor`, `c`, `K`. Optional: `util_threshold` (overrides the kwarg).
        method_cfg (Dict[str, Any]): per-combo runs reuse its `ramp`, `seed`, `request_size_bytes`.
        adp (str): adaptation label (`baseline` / `s1` / `s2` / `aggregate`).
        util_threshold (float): drop combos with any per-node rho at or above this.

    Returns:
        Dict[str, Dict[str, np.ndarray]]: nested `{artifact_key: per_artifact_sweep}`; matches `src.dimensional.networks.sweep_arch` so the same plotters consume both.

    Raises:
        ValueError: when `cfg` carries zero artifacts.
        KeyError: when `method_cfg` lacks one of the keys consumed by `execute_one` (`ramp`, `seed`, `request_size_bytes`).
    """
    _util = float(sweep_grid.get("util_threshold", util_threshold))
    _mu_factors = sweep_grid.get("mu_factor", [1.0])
    _c_vals = sweep_grid.get("c", [1])
    _K_vals = sweep_grid.get("K", [10])

    _art_keys = [_a.key for _a in cfg.artifacts]
    _per_art = _empty_per_art(_art_keys)

    for _mf, _c_int, _K_int in _iter_grid(_mu_factors, _c_vals, _K_vals):
        _cfg_combo = _override_cfg(cfg,
                                   mu_factor=_mf,
                                   c_int=_c_int,
                                   K_int=_K_int)

        _nds = _run_one_combo(_cfg_combo, method_cfg, adp)
        if _nds is None:
            continue

        # combo-wide stability gate: drop the whole combo if any node saturated
        if (_nds["rho"] >= _util).any():
            continue

        for _a in _cfg_combo.artifacts:
            _row = _nds.loc[_nds["key"] == _a.key]
            if _row.empty:
                continue
            _row = _row.iloc[0]

            _coefs = _derive_combo_coefs(_row, _a, _c_int, _K_int)
            if _coefs is None:
                continue

            _block = _per_art[_a.key]
            for _sym, _val in _coefs.items():
                _block[_sym].append(_val)

    _out: Dict[str, Dict[str, np.ndarray]] = {}
    for _k, _block in _per_art.items():
        _out[_k] = {_s: np.asarray(_v, dtype=float) for _s, _v in _block.items()}
    return _out
