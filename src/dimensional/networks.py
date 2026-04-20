# -*- coding: utf-8 -*-
"""
Module networks.py
==================

Configuration-sweep helpers for the dimensional method's yoly notebook.

Each artifact has a fixed arrival rate (the seeded `\\lambda` from the
analytic solver). We sweep the design knobs `(mu, c, K)` per the grid
declared in `data/config/method/dimensional.json::sweep_grid`, solve the
M/M/c/K queue at every combination, and derive the four operationally
meaningful coefficients directly:

    - theta = L / K           (Occupancy)
    - sigma = lambda * W / L  (Stall, ~1 in steady state)
    - eta   = chi * K / (mu * c) (Effective-yield)
    - phi   = M_act / M_buf   (Memory-use, collapses to theta under L*delta / K*delta)

Unstable points (rho >= `util_threshold`) are dropped so the resulting
coefficient cloud only contains feasible designs.

    - `sweep_artifact(artifact_key, vars_block, sweep_grid, ...)` returns one artifact's sweep as a dict of arrays keyed by full LaTeX symbols.
    - `sweep_network(cfg, sweep_grid, ...)` runs `sweep_artifact` for every node in a `NetworkConfig` and returns the nested dict consumed by `src.view.dc_charts.plot_yoly_arts_*`.

*IMPORTANT:* the sweep is deterministic (not Monte Carlo). For stochastic
sampling go through `src.methods.dimensional` + the dimensional notebook.
"""
# native python modules
from __future__ import annotations

# data types
from typing import Any, Dict, Iterable, List

# scientific stack
import numpy as np

# local modules
from src.analytic.queues import Queue
from src.io import NetworkConfig


# default utilisation cap; points with rho at or above this are dropped
_UTIL_THLD_DEFAULT = 0.95


def _setpoint(vars_block: Dict[str, Dict[str, Any]],
              prefix: str,
              artifact_key: str) -> float:
    """*_setpoint()* returns the `_setpoint` of a variable identified by `<prefix>_{<artifact_key>}`.

    Args:
        vars_block (Dict[str, Dict[str, Any]]): per-artifact `vars` dict.
        prefix (str): LaTeX symbol prefix (e.g. `"\\lambda"`, `"\\mu"`, `"K"`).
        artifact_key (str): artifact identifier in LaTeX subscript form.

    Raises:
        KeyError: If no matching variable is present.

    Returns:
        float: the setpoint value (cast to float).
    """
    _sym = f"{prefix}_{{{artifact_key}}}"
    if _sym not in vars_block:
        raise KeyError(f"missing {_sym} on artifact vars block")
    return float(vars_block[_sym]["_setpoint"])


def sweep_artifact(artifact_key: str,
                   vars_block: Dict[str, Dict[str, Any]],
                   sweep_grid: Dict[str, Any],
                   *,
                   util_threshold: float = _UTIL_THLD_DEFAULT,
                   model: str = "M/M/c/K") -> Dict[str, np.ndarray]:
    """*sweep_artifact()* sweeps the `(mu, c, K)` design grid AND ramps `lambda` for each combo, returning trace-shaped coefficient curves.

    For each cartesian combination of `(mu_factor, c, K)`:

    1. `mu = mu_factor * mu_setpoint`.
    2. Pick a maximum `lambda` that keeps the queue stable: `lambda_max = util_threshold * mu * c` (the textbook cap for M/M/c/K).
    3. Linearly ramp `lambda` from `lambda_factor_min * lambda_max` to `lambda_max` in `lambda_steps` increments.
    4. Solve M/M/c/K at every step; derive `theta`, `sigma`, `eta`, `phi` directly.
    5. Drop steps where the solver's reported `rho` exceeds the cap (numerical safety).

    The result is one TRACE per `(mu, c, K)` combo (not a single dot), so the
    yoly cloud is a set of curves through coefficient space.

    Args:
        artifact_key (str): artifact identifier in LaTeX subscript form (e.g. `"TAS_{1}"`).
        vars_block (Dict[str, Dict[str, Any]]): the artifact's `vars` dict from the profile JSON. Must carry `\\lambda`, `\\mu`, `\\epsilon`, `\\delta` setpoints (all under the artifact subscript).
        sweep_grid (Dict[str, Any]): grid declared in `data/config/method/dimensional.json::sweep_grid`. Keys: `mu_factor`, `c`, `K`, `lambda_steps`, `lambda_factor_min`.
        util_threshold (float): drop points with `rho >= util_threshold`. Defaults to `0.95`.
        model (str): queue model passed to the `Queue` factory. Defaults to `"M/M/c/K"`.

    Raises:
        KeyError: If any required variable is missing on the artifact block.

    Returns:
        Dict[str, np.ndarray]: arrays keyed by full LaTeX symbol. Same length across keys; one entry per stable trace point.
    """
    # baselines
    _mu_base = _setpoint(vars_block, "\\mu", artifact_key)
    _eps = _setpoint(vars_block, "\\epsilon", artifact_key)

    # lambda iteration parameters from the sweep grid (with safe defaults)
    _n_steps = int(sweep_grid.get("lambda_steps", 30))
    _lam_min_frac = float(sweep_grid.get("lambda_factor_min", 0.05))

    # accumulators (lists for now; converted to ndarrays at the end)
    _theta_lt: List[float] = []
    _sigma_lt: List[float] = []
    _eta_lt: List[float] = []
    _phi_lt: List[float] = []
    _c_lt: List[float] = []
    _mu_lt: List[float] = []
    _K_lt: List[float] = []
    _lam_lt: List[float] = []

    # walk the cartesian grid; the order is (mu, c, K, lambda_step) for repeatability
    for _mf in sweep_grid.get("mu_factor", [1.0]):
        _mu = float(_mu_base) * float(_mf)
        for _c in sweep_grid.get("c", [1]):
            _c_int = int(_c)
            for _K in sweep_grid.get("K", [10]):
                _K_int = int(_K)
                # K must be >= c for M/M/c/K to be defined
                if _K_int < _c_int:
                    continue

                # textbook stability cap: lambda_max = util_threshold * mu * c
                _lam_max = util_threshold * _mu * _c_int
                _lam_min = _lam_max * _lam_min_frac
                _lambdas = np.linspace(_lam_min, _lam_max, _n_steps)

                # ramp lambda; each step contributes one trace point
                for _lam in _lambdas:
                    try:
                        _q = Queue(model=model,
                                   lamb=float(_lam),
                                   mu=_mu,
                                   c_max=_c_int,
                                   K_max=_K_int)
                        _q.calculate_metrics()
                    except Exception:
                        continue

                    if _q.rho >= util_threshold:
                        continue

                    _L = float(_q.avg_len)
                    _W = float(_q.avg_wait)
                    if _L <= 0:
                        continue

                    _chi = float(_lam) * (1.0 - _eps)
                    _theta = _L / _K_int
                    _sigma = float(_lam) * _W / _L
                    _eta = _chi * _K_int / (_mu * _c_int)
                    # phi = M_act / M_buf = (L * delta) / (K * delta) = L / K
                    _phi = _L / _K_int

                    _theta_lt.append(_theta)
                    _sigma_lt.append(_sigma)
                    _eta_lt.append(_eta)
                    _phi_lt.append(_phi)
                    _c_lt.append(float(_c_int))
                    _mu_lt.append(_mu)
                    _K_lt.append(float(_K_int))
                    _lam_lt.append(float(_lam))

    # subscripted symbol map ready for the dc_charts plotters
    return {
        f"\\theta_{{{artifact_key}}}": np.asarray(_theta_lt, dtype=float),
        f"\\sigma_{{{artifact_key}}}": np.asarray(_sigma_lt, dtype=float),
        f"\\eta_{{{artifact_key}}}": np.asarray(_eta_lt, dtype=float),
        f"\\phi_{{{artifact_key}}}": np.asarray(_phi_lt, dtype=float),
        f"c_{{{artifact_key}}}": np.asarray(_c_lt, dtype=float),
        f"\\mu_{{{artifact_key}}}": np.asarray(_mu_lt, dtype=float),
        f"K_{{{artifact_key}}}": np.asarray(_K_lt, dtype=float),
        f"\\lambda_{{{artifact_key}}}": np.asarray(_lam_lt, dtype=float),
    }


def sweep_network(cfg: NetworkConfig,
                  sweep_grid: Dict[str, List[float]],
                  *,
                  util_threshold: float = _UTIL_THLD_DEFAULT,
                  model: str = "M/M/c/K",
                  artifact_filter: Iterable[str] = ()
                  ) -> Dict[str, Dict[str, np.ndarray]]:
    """*sweep_network()* runs `sweep_artifact` for every artifact of a resolved `NetworkConfig` and returns the nested cloud dict consumed by `src.view.dc_charts.plot_yoly_arts_*`.

    Args:
        cfg (NetworkConfig): resolved network configuration for one (profile, scenario) pair.
        sweep_grid (Dict[str, List[float]]): grid declared in `data/config/method/dimensional.json::sweep_grid`.
        util_threshold (float): per-artifact stability cap. Defaults to `0.95`.
        model (str): queue model passed to the `Queue` factory. Defaults to `"M/M/c/K"`.
        artifact_filter (Iterable[str]): optional subset of artifact keys to include. Empty `()` means all.

    Returns:
        Dict[str, Dict[str, np.ndarray]]: nested `{artifact_key: per_artifact_sweep}`. Per-artifact dict matches `sweep_artifact`'s return shape.
    """
    # pre-compute the filter set so the per-loop check is O(1)
    _filter = set(artifact_filter)

    _out: Dict[str, Dict[str, np.ndarray]] = {}
    for _a in cfg.artifacts:
        if _filter and _a.key not in _filter:
            continue

        _out[_a.key] = sweep_artifact(_a.key,
                                      _a.vars,
                                      sweep_grid,
                                      util_threshold=util_threshold,
                                      model=model)
    return _out
