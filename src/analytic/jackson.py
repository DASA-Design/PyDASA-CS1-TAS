# -*- coding: utf-8 -*-
"""
Module jackson.py
=================

Jackson open-network solver for the analytic method of the TAS case
study. Three layers, kept separate so each can be unit-tested
independently:

    - `solve_jackson_lambdas(P, lambda_z)` — pure linear solve of `(I - P^T) lamb = lamb_z`, returning the per-node effective arrival rates.
    - `solve_network(cfg)` — takes a resolved `NetworkConfig`, builds a `Queue` per artifact with the Jackson-solved `lamb`, calls `calculate_metrics()`, and returns a pandas DataFrame with one row per node.
    - **ρ-indexed helpers** (`per_artifact_lambdas`, `per_artifact_rhos`, `lambda_z_for_rho`, `build_rho_grid`) — inverse direction used by the experiment orchestrator to drive the ρ-indexed operating-point grid. Since Jackson is linear in λ_z, the inversion is one division.

*IMPORTANT:* the routing matrix in `cfg.routing` is stored with
`row = source, col = dest`, so it is transposed before solving the
linear system.

# TODO: add flow-conservation and row-stochasticity sanity checks on `P` before dispatching to `numpy.linalg.solve`.
"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations

# data types
from typing import List, Sequence, Tuple, Union

# scientific stack
import numpy as np
import pandas as pd

# local modules
from src.analytic.queues import Queue
from src.io.config import NetworkConfig


def solve_jackson_lambdas(P: Union[np.ndarray, List[float]],
                          lambda_zero: Union[np.ndarray, List[float]]) -> np.ndarray:
    """*solve_jackson_lambdas()* solves the Jackson traffic equations `(I - P^T) lamb = lamb_z` for the per-node effective arrival rates.

    Args:
        P (Union[np.ndarray, List[float]]): `(n, n)` routing probability matrix. `P[i, j]` is the probability of routing from node `i` to node `j`.
        lambda_zero (Union[np.ndarray, List[float]]): `(n,)` vector of external arrivals per node ($\\lambda_z$).

    Returns:
        np.ndarray: `(n,)` array of per-node effective arrival rate ($\\lambda$).
    """
    # coerce inputs to float arrays (accept lists too)
    _P = np.asarray(P, dtype=float)
    _lz = np.asarray(lambda_zero, dtype=float)

    # build the identity of matching shape and solve the linear system
    _I = np.eye(_P.shape[0])
    _lambdas = np.linalg.solve(_I - _P.T, _lz)
    return _lambdas


def solve_network(cfg: NetworkConfig) -> pd.DataFrame:
    """*solve_network()* solves the open Jackson network for the given scenario and returns per-node metrics as a pandas DataFrame.

    For each of the n-artifacts in `cfg`, creates a `Queue` with its declared `type` / $\\mu$ / $c$ / $K$, injects the Jackson-solved $\\lambda$, and calls `calculate_metrics()`. Stops with a clear error if any node comes out unstable ($\\rho \\geq 1$).

    Args:
        cfg (NetworkConfig): resolved network configuration for one (profile, scenario) pair. Provides artifacts, external arrivals, and the routing matrix.

    Raises:
        ValueError: If one or more nodes are unstable under the Jackson-solved arrival rates.

    Returns:
        pd.DataFrame: one row per artifact with columns `node`, `key`, `name`, `type`, `lambda`, `mu`, `c`, `K`, `rho`, `L`, `Lq`, `W`, `Wq`.
    """
    # solve the traffic equations once for the whole network
    _lambdas = solve_jackson_lambdas(cfg.routing, cfg.lambda_z_vector())

    # accumulators for per-node rows and any unstable nodes found
    _rows: List[dict] = []
    _unstable: List[tuple] = []

    # walk artifacts in declared order; the index is the node id
    for _i, _a in enumerate(cfg.artifacts):
        # build the queue with the Jackson-solved arrival rate
        _q = Queue(
            model=_a.type_,
            lamb=float(_lambdas[_i]),
            mu=_a.mu,
            c_max=_a.c,
            K_max=_a.K,
        )
        _q.calculate_metrics()

        # track nodes that come out unstable (rho >= 1)
        if _q.rho >= 1.0:
            _unstable.append((_a.key, _q.rho))

        # record the per-node row for the output DataFrame
        _rows.append({
            "node": _i,
            "key": _a.key,
            "name": _a.name,
            "type": _a.type_,
            "lambda": _lambdas[_i],
            "mu": _a.mu,
            "c": _a.c,
            "K": _a.K,
            "rho": _q.rho,
            "L": _q.avg_len,
            "Lq": _q.avg_len_q,
            "W": _q.avg_wait,
            "Wq": _q.avg_wait_q,
        })

    # fail loud if any node is unstable; report every offender at once
    if _unstable:
        _details = ", ".join(f"{_k}: rho={_r:.4f}" for _k, _r in _unstable)
        _msg = f"unstable nodes in scenario {cfg.scenario!r}: "
        _msg += _details
        raise ValueError(_msg)

    return pd.DataFrame(_rows)


# --- ρ-indexed helpers (experiment orchestrator drives the grid in ρ, ----
# --- the apparatus consumes λ; Jackson linearity makes the inverse one ---
# --- division, so a single probe identifies the bottleneck + scaling). ---


def per_artifact_lambdas(cfg: NetworkConfig,
                         lambda_z: float) -> np.ndarray:
    """*per_artifact_lambdas()* effective arrival rate per artifact at the given scalar entry rate.

    Scales the profile's `lambda_z_vector()` (the entry-distribution of
    λ_z across artifacts) by the scalar `lambda_z` so callers can sweep
    the entry rate without editing the profile, then delegates to
    `solve_jackson_lambdas` for the forward solve.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        lambda_z (float): total external arrival rate at the network entry.

    Returns:
        np.ndarray: per-artifact λ_i in artifact-declaration order.
    """
    _lam_z_vec = np.asarray(cfg.lambda_z_vector(), dtype=float)
    _total = float(_lam_z_vec.sum())
    if _total <= 0:
        # profile has no external arrivals declared; treat the first
        # artifact as the entry
        _entry_vec = np.zeros_like(_lam_z_vec)
        _entry_vec[0] = float(lambda_z)
    else:
        _entry_vec = _lam_z_vec * (float(lambda_z) / _total)
    return solve_jackson_lambdas(np.asarray(cfg.routing, dtype=float),
                                 _entry_vec)


def per_artifact_rhos(cfg: NetworkConfig,
                      lambda_z: float) -> np.ndarray:
    """*per_artifact_rhos()* per-artifact utilisation at the given entry rate.

    `ρ_i = λ_i / (c_i · μ_i)`. Returns `+inf` for any artifact with
    zero capacity (not present in well-formed profiles).

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        lambda_z (float): total external arrival rate at the network entry.

    Returns:
        np.ndarray: per-artifact ρ in artifact-declaration order.
    """
    _lams = per_artifact_lambdas(cfg, lambda_z)
    _capacity = np.array([float(_a.c) * float(_a.mu) for _a in cfg.artifacts])
    with np.errstate(divide="ignore", invalid="ignore"):
        _rhos = np.where(_capacity > 0, _lams / _capacity, np.inf)
    return _rhos


def lambda_z_for_rho(cfg: NetworkConfig,
                     rho_target: float,
                     *,
                     probe_lambda_z: float = 1.0
                     ) -> Tuple[float, int, float]:
    """*lambda_z_for_rho()* solve for the entry λ_z that makes the bottleneck artifact hit `rho_target`.

    Since Jackson is linear in λ_z, one probe at any positive rate is
    enough to identify the bottleneck (artifact with the highest ρ per
    unit λ_z) and the linear scaling factor.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        rho_target (float): desired bottleneck utilisation in (0, 1).
        probe_lambda_z (float): any positive probe rate; only used to identify the per-unit-λ bottleneck.

    Raises:
        ValueError: if `rho_target` is outside `(0, 1)` or no artifact has positive capacity.

    Returns:
        Tuple[float, int, float]: `(lambda_z, bottleneck_index, rho_per_unit_lambda_z)`.
    """
    if not 0.0 < rho_target < 1.0:
        raise ValueError(f"rho_target must be in (0, 1), got {rho_target}")
    _rhos = per_artifact_rhos(cfg, probe_lambda_z)
    if not np.all(np.isfinite(_rhos)):
        raise ValueError("at least one artifact has non-finite ρ; check μ and c")
    _bottleneck = int(np.argmax(_rhos))
    _per_unit = float(_rhos[_bottleneck]) / float(probe_lambda_z)
    if _per_unit <= 0:
        raise ValueError("bottleneck ρ per unit λ_z is non-positive; check routing")
    _lam_z = float(rho_target) / _per_unit
    return _lam_z, _bottleneck, _per_unit


def build_rho_grid(cfg: NetworkConfig,
                   rho_grid: Sequence[float]
                   ) -> Sequence[Tuple[float, float, int]]:
    """*build_rho_grid()* map a ρ-indexed operating-point grid to the corresponding λ_z values.

    Args:
        cfg (NetworkConfig): resolved profile + scenario.
        rho_grid (Sequence[float]): target bottleneck utilisations.

    Returns:
        Sequence[Tuple[float, float, int]]: list of `(rho_target, lambda_z, bottleneck_index)`.
    """
    _out: List[Tuple[float, float, int]] = []
    for _rho in rho_grid:
        _lam_z, _bottle, _ = lambda_z_for_rho(cfg, float(_rho))
        _out.append((float(_rho), float(_lam_z), int(_bottle)))
    return _out
