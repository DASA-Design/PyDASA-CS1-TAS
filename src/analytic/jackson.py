# -*- coding: utf-8 -*-
"""
Module jackson.py
=================

Jackson open-network solver for the analytic method of the TAS case
study. Two layers, kept separate so the linear-algebra core can be
unit-tested without pulling in `NetworkConfig`:

    - `solve_jackson_lambdas(P, lambda_z)` solves the traffic equations `(I - P^T) lamb = lamb_z`, returning the effective per-node arrival rates.
    - `solve_network(cfg)` takes a resolved `NetworkConfig`, builds a `Queue` per artifact with the Jackson-solved `lamb`, calls `calculate_metrics()`, and returns a pandas DataFrame with one row per node.

*IMPORTANT:* the routing matrix in `cfg.routing` is stored with
`row = source, col = dest`, so it is transposed before solving the
linear system.

# TODO: add flow-conservation and row-stochasticity sanity checks on `P` before dispatching to `numpy.linalg.solve`.
"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations

# data types
from typing import List, Union

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
