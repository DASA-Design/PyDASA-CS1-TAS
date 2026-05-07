# -*- coding: utf-8 -*-
"""
Module dimensional/dasaprof.py
==============================

Route-B DASA profile (dimensional card) derived from calibration measurements rather than from M/M/c/K predictions. The four operational coefficients (theta = L/K, sigma = lambda*W/K, eta = chi*K/(c*mu), phi = M_act/M_buf) are evaluated row-wise across per-`n_con_usr` measurement arrays via PyDASA's `MonteCarloSimulation(mode="DATA")`.

This module is the dimensional-layer home for the calibration card. It lives alongside `engine.py` (`build_engine`) and `coefficients.py` (`derive_coefs`) because the card IS a dimensional-method output: calibration provides the observables, the dimensional layer owns the coefficient derivation. Sibling-with-derive_coefs distinction:

- `coefficients.py::derive_coefs`: TAS-architecture path. Reads specs from `data/config/method/dimensional.json` with `{pi[i]}` placeholders that resolve to the engine's Pi-group keys in declaration order.
- `dasaprof.py::derive_calib_coefs`: calibration-artifact path. Builds `pydasa.Coefficient` objects directly with `_pi_expr` written in base variables, robust to Pi-group ordering shifts because the calibration's variable set + FDU count differ from the TAS topology.

Public API:
    - `derive_calib_coefs(envelope, payload_size_bytes, tag, K_values)`: top-level entry; returns the dim-card dict that downstream consumers stamp onto the calibration envelope under the `dimensional_card` key.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# scientific stack
import numpy as np


# default backlog when the envelope lacks `args.uvicorn_backlog` (legacy single-K cards)
_DEFAULT_UVICORN_BACKLOG = 16384

# default subscript tag for output coefficient symbols
_CALIB_DIM_TAG = "CALIB"


def _build_calib_observables(handler_scaling: Dict[str, Dict[str, float]],
                             loopback: Dict[str, float],
                             *,
                             payload_size_bytes: int,
                             uvicorn_backlog: int,
                             c_srv: int,
                             ) -> Dict[str, np.ndarray]:
    """*_build_calib_observables()* extract per-`n_con_usr` measurement arrays from a calibration envelope.

    Aggregates the measured response-time medians at each `n_con_usr` level into the operational quantities the M/M/c/K Variable schema expects (lambda, mu, c, K, L, W, Wq, M_act, M_buf, chi). Each array has one entry per level, ordered by ascending `n_con_usr`. Used to populate `Variable._data` arrays so PyDASA's MonteCarloSimulation can evaluate coefficient expressions row-wise.

    Args:
        handler_scaling (Dict[str, Dict[str, float]]): envelope's `handler_scaling` block; keys are `n_con_usr` as strings, values hold `median_us` and distribution stats.
        loopback (Dict[str, float]): envelope's `loopback` block; `median_us` supplies the idle-service reference.
        payload_size_bytes (int): per-request body size in bytes; populates `M_act`, `M_buf`. When 0, the memory-usage coefficient `phi` reduces to a degenerate 0/0 and is post-processed to NaN.
        uvicorn_backlog (int): system capacity `K`.
        c_srv (int): service-side parallel-handler count (always 1 for the calibration service).

    Returns:
        Dict[str, np.ndarray]: arrays keyed by short symbolic name (`n`, `lam`, `mu`, `chi`, `c`, `K`, `L`, `W`, `Wq`, `M_act`, `M_buf`, `reject_rate`); all share length N (number of `n_con_usr` levels).
    """
    _r_median_us = float(loopback.get("median_us", 0.0))
    if _r_median_us <= 0.0:
        _mu_scalar = 0.0
    else:
        _mu_scalar = 1e6 / _r_median_us
    _k_capacity = int(uvicorn_backlog)

    _levels: List[int] = []
    for _k in handler_scaling.keys():
        _levels.append(int(_k))
    _levels.sort()

    _n_arr: List[int] = []
    _r_arr: List[float] = []
    _reject_rate_arr: List[float] = []
    for _n in _levels:
        _stats = handler_scaling.get(str(_n), {})
        _median_us = float(_stats.get("median_us", 0.0))
        _n_arr.append(int(_n))
        _r_arr.append(_median_us * 1e-6)
        _reject_rate_arr.append(float(_stats.get("reject_rate", 0.0)))

    _n_np = np.asarray(_n_arr, dtype=float)
    _r_np = np.asarray(_r_arr, dtype=float)
    _reject_np = np.asarray(_reject_rate_arr, dtype=float)

    # zero-latency rows -> NaN so downstream divisions stay finite
    _r_safe = np.where(_r_np > 0.0, _r_np, np.nan)
    # X = n / R
    _x = _n_np / _r_safe
    # steady-state arrival = throughput
    _lam = _x
    # closed-loop Little's law gives L = n_con_usr (workload-side demand). The dimensional model is M/M/c/K, which requires L <= K (admitted in-system count). Capping happens downstream in `derive_calib_coefs` once K is finalised.
    _l_load = _n_np
    _r_service = _r_median_us * 1e-6
    _wq = np.maximum(_r_np - _r_service, 0.0)

    _eps = np.zeros_like(_n_np, dtype=float)
    _chi = _lam * (1.0 - _eps)
    _c_np = np.full_like(_n_np, float(c_srv))
    _k_np = np.full_like(_n_np, float(_k_capacity))
    _mu_np = np.full_like(_n_np, float(_mu_scalar))

    # memory side; d in kB. 0 means "degenerate phi" -> NaN row downstream
    _d_kB = float(payload_size_bytes) / 1000.0
    _m_act = _l_load * _d_kB
    _m_buf = _k_np * _d_kB

    return {
        "n": _n_np,
        "lam": _lam,
        "mu": _mu_np,
        "chi": _chi,
        "c": _c_np,
        "K": _k_np,
        "L": _l_load,
        "W": _r_np,
        "Wq": _wq,
        "M_act": _m_act,
        "M_buf": _m_buf,
        "reject_rate": _reject_np,
    }


# calibration-artifact variable schema; M_{a<tag>}/M_{b<tag>} chosen because sympy parses MA_{X} as M*A and breaks aliases; q-suffixed and nested-brace forms (Lq, Wq, M_{act_{X}}) excluded for the same parser reason
_CALIB_VAR_SPECS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    # (short_key, latex_template, dims, units, cat, dist_type)
    ("lam", "\\lambda_{<TAG>}", "S*T^-1", "req/s", "IN", "uniform"),
    ("mu", "\\mu_{<TAG>}", "S*T^-1", "req/s", "CTRL", "uniform"),
    ("chi", "\\chi_{<TAG>}", "S*T^-1", "req/s", "CTRL", "uniform"),
    ("c", "c_{<TAG>}", "S", "req", "IN", "uniform_int"),
    ("K", "K_{<TAG>}", "S", "req", "CTRL", "uniform_int"),
    ("L", "L_{<TAG>}", "S", "req", "CTRL", "uniform"),
    ("W", "W_{<TAG>}", "T", "s", "OUT", "uniform"),
    ("M_act", "M_{a<TAG>}", "D", "kB", "CTRL", "uniform"),
    ("M_buf", "M_{b<TAG>}", "D", "kB", "CTRL", "uniform"),
)


def _calib_var_sym(short: str, tag: str) -> str:
    """*_calib_var_sym()* render a calibration-variable LaTeX symbol from its short key.

    Args:
        short (str): short key (`"lam"`, `"mu"`, `"M_act"`, ...).
        tag (str): artifact subscript tag (e.g. `"CALIB"`).

    Returns:
        str: full LaTeX symbol (e.g. `"\\lambda_{CALIB}"`, `"M_{aCALIB}"`).

    Raises:
        KeyError: when `short` is not in `_CALIB_VAR_SPECS`.
    """
    for _spec in _CALIB_VAR_SPECS:
        if _spec[0] == short:
            return _spec[1].replace("<TAG>", tag)
    _msg = f"unknown calibration variable short key: {short!r}"
    raise KeyError(_msg)


def _build_calib_vars(observables: Dict[str, np.ndarray],
                      *,
                      tag: str) -> Dict[str, Dict[str, Any]]:
    """*_build_calib_vars()* construct a per-artifact PACS Variable dict for the calibration data.

    Each `_CALIB_VAR_SPECS` entry yields one Variable dict shaped to match `pydasa.elements.parameter.Variable.__init__`. The measured array from `observables` populates `_data`; `_setpoint` / `_min` / `_max` / `_mean` are derived as nan-aware reductions over that array so `Variable.calculate_setpoint()` works at deterministic values.

    Args:
        observables (Dict[str, np.ndarray]): output of `_build_calib_observables`.
        tag (str): artifact subscript tag used in the LaTeX symbols.

    Returns:
        Dict[str, Dict[str, Any]]: PACS Variable-dict for the calibration artifact, ready to feed `src.dimensional.build_engine`.
    """
    _vars: Dict[str, Dict[str, Any]] = {}
    for _idx, _spec in enumerate(_CALIB_VAR_SPECS, start=1):
        _short, _template, _dims, _units, _cat, _dist = _spec
        _arr = observables[_short]

        if _arr.size > 0:
            _finite = _arr[np.isfinite(_arr)]
        else:
            _finite = _arr
        if _finite.size > 0:
            _mn = float(np.min(_finite))
            _mx = float(np.max(_finite))
            _mean = float(np.mean(_finite))
            _setp = float(np.median(_finite))
        else:
            _mn = 0.0
            _mx = 0.0
            _mean = 0.0
            _setp = 0.0

        _sym = _calib_var_sym(_short, tag)
        _alias = _sym.replace("\\", "").replace("{", "").replace("}", "").replace(",", "").replace(" ", "_")

        if _mx > _mn:
            _params = {"low": _mn, "high": _mx}
        else:
            _params = {"low": _mn, "high": _mn + 1.0}

        _vars[_sym] = {
            "_sym": _sym,
            "_fwk": "CUSTOM",
            "_alias": _alias,
            "_idx": _idx,
            "_name": f"{tag} {_short}",
            "description": f"Calibration {_short} per n_con_usr level",
            "_cat": _cat,
            "relevant": True,
            "_dims": _dims,
            "_units": _units,
            "_std_units": _units,
            "_setpoint": _setp,
            "_min": _mn,
            "_max": _mx,
            "_mean": _mean,
            "_dist_type": _dist,
            "_dist_params": _params,
            "_depends": [],
            "_data": [float(_v) for _v in _arr.tolist()],
        }
    return _vars


def _run_calib_pipeline(vars_block: Dict[str, Dict[str, Any]],
                        *,
                        n_levels: int,
                        tag: str
                        ) -> Dict[str, np.ndarray]:
    """*_run_calib_pipeline()* drive PyDASA Variable -> Schema -> AnalysisEngine -> Coefficient(...) -> MonteCarloSimulation(DATA) and extract per-level coefficient arrays.

    The four target coefficients (theta, sigma, eta, phi) are constructed as `pydasa.Coefficient` objects directly with `_pi_expr` written in terms of the base CALIB variables, robust against Pi-group ordering shifts vs the TAS profile. `MonteCarloSimulation.run_simulation(mode="DATA")` lambdifies each expression and evaluates it row-wise across the `_data` arrays.

    Args:
        vars_block (Dict[str, Dict[str, Any]]): PACS Variable dict produced by `_build_calib_vars`.
        n_levels (int): number of measurement rows; matches the length of every `_data` array.
        tag (str): artifact subscript tag (`"CALIB"`).

    Returns:
        Dict[str, np.ndarray]: coefficient arrays keyed by full LaTeX symbol (`\\theta_{<tag>}`, `\\sigma_{<tag>}`, `\\eta_{<tag>}`, `\\phi_{<tag>}`); one entry per level.
    """
    # PyDASA + dimensional stack imported lazily so dasaprof's import surface stays light
    from pydasa import Coefficient, MonteCarloSimulation  # noqa: WPS433
    from src.dimensional.engine import build_engine  # noqa: WPS433
    from src.dimensional.schema import build_schema  # noqa: WPS433
    from src.io import load_method_cfg  # noqa: WPS433

    _mcfg = load_method_cfg("dimensional")
    _sch = build_schema(_mcfg["fdus"])
    _eng = build_engine(tag, vars_block, _sch)
    _eng.run_analysis()

    # explicit base-variable LaTeX expressions; no Pi-group indices so robust against Buckingham ordering shifts
    _lam = _calib_var_sym("lam", tag)
    _mu = _calib_var_sym("mu", tag)
    _chi = _calib_var_sym("chi", tag)
    _c = _calib_var_sym("c", tag)
    _K = _calib_var_sym("K", tag)
    _L = _calib_var_sym("L", tag)
    _W = _calib_var_sym("W", tag)
    _MA = _calib_var_sym("M_act", tag)
    _MB = _calib_var_sym("M_buf", tag)

    _coef_specs = (
        ("\\theta", "Occupancy",
         f"\\frac{{{_L}}}{{{_K}}}",
         (_L, _K)),
        ("\\sigma", "Stall",
         f"\\frac{{{_lam}*{_W}}}{{{_K}}}",
         (_lam, _W, _K)),
        ("\\eta", "Effective-yield",
         f"\\frac{{{_chi}*{_K}}}{{{_c}*{_mu}}}",
         (_chi, _K, _c, _mu)),
        ("\\phi", "Memory-usage",
         f"\\frac{{{_MA}}}{{{_MB}}}",
         (_MA, _MB)),
    )

    _der: Dict[str, Any] = {}
    for _sym_pre, _name, _expr, _refs in _coef_specs:
        _full = f"{_sym_pre}_{{{tag}}}"
        _coeff = Coefficient(_sym=_full,
                             _pi_expr=_expr,
                             _fwk="CUSTOM",
                             _variables=dict(_eng.variables),
                             _name=f"{tag} {_name} coefficient",
                             description=f"{_name} ({_full})")
        # Coefficient.__post_init__ resets var_dims when _dim_col is empty; populate after construction so MCS accepts it
        _coeff.var_dims = {_v: 0 for _v in _refs}
        _der[_full] = _coeff

    _mcs = MonteCarloSimulation(
        _variables=_eng.variables,
        _coefficients=_der,
        _experiments=max(int(n_levels), 1),
        _fwk="CUSTOM",
        _cat="DATA",
    )
    _mcs.create_simulations()
    # silence 0/0 RuntimeWarning when payload=0; downstream forces NaN regardless
    with np.errstate(divide="ignore", invalid="ignore"):
        _mcs.run_simulation(iters=max(int(n_levels), 1), mode="DATA")

    _out: Dict[str, np.ndarray] = {}
    for _sym in _der.keys():
        _blk = _mcs._results.get(_sym, {})
        _arr = np.asarray(_blk.get("results", []), dtype=float)
        _out[_sym] = _arr
    return _out


def derive_calib_coefs(envelope: Dict[str, Any],
                       *,
                       payload_size_bytes: int = 0,
                       tag: str = _CALIB_DIM_TAG,
                       K_values: Optional[List[int]] = None) -> Dict[str, Any]:
    """*derive_calib_coefs()* build the dimensional card from a calibration envelope using PyDASA.

    Routes the measured `handler_scaling` + `loopback` arrays through the PyDASA pipeline (Variable dicts -> Schema -> AnalysisEngine -> Coefficient(...) -> MonteCarloSimulation in DATA mode) so theta / sigma / eta / phi are computed by PyDASA's symbolic evaluator, not by hand-rolled arithmetic. Coefficient symbols carry the `_{<tag>}` subscript (default `_{CALIB}`).

    Route B semantics: coefficients are derived from measurements, not from an M/M/c/K prediction. Applies only when both `handler_scaling` and `loopback` are present in the envelope; returns an empty dict otherwise.

    When `K_values` is supplied, the per-`n_con_usr` observables are tiled once per K so the resulting coefficient arrays span the full (n_con_usr, K) cartesian, giving `plot_yoly_chart` multiple K-trajectories instead of a single point. Latency `R(n)` is independent of K (the host probe doesn't manipulate the buffer), so tiling is exact: only `theta = L/K`, `sigma = lambda*W/K`, and `phi = M_act/M_buf` shift across K.

    Args:
        envelope (Dict[str, Any]): calibration envelope (e.g. from `run()` or `load_latest_calibration()`).
        payload_size_bytes (int): body size per request for the phi coefficient; 0 marks phi as NaN to flag the degenerate 0/0 memory case.
        tag (str): LaTeX-subscript tag used in output keys. Default `CALIB`.
        K_values (Optional[List[int]]): K capacities to span. When None, falls back to a single K = `args.uvicorn_backlog` (legacy single-point card). When provided, output arrays have length `len(handler_scaling) * len(K_values)`.

    Returns:
        Dict[str, Any]: coefficient arrays (JSON-serialisable `List[float]`) keyed by LaTeX-subscripted symbol (`\\theta_{<tag>}`, `\\sigma_{<tag>}`, `\\eta_{<tag>}`, `\\phi_{<tag>}`, plus the input-side `c_{<tag>}`, `\\mu_{<tag>}`, `K_{<tag>}`, `\\lambda_{<tag>}`, `n_con_usr_{<tag>}`), and a `meta` sub-dict with provenance. Empty dict when `handler_scaling` or `loopback` is missing.
    """
    _handler = envelope.get("handler_scaling")
    _loop = envelope.get("loopback")
    if not isinstance(_handler, dict) or not isinstance(_loop, dict):
        return {}

    _args_block = envelope.get("args") or {}
    _backlog = int(_args_block.get("uvicorn_backlog",
                                   _DEFAULT_UVICORN_BACKLOG))

    if K_values is None:
        _K_list = [_backlog]
    else:
        _K_list = [int(_k) for _k in K_values]
        if not _K_list:
            _K_list = [_backlog]

    _obs = _build_calib_observables(
        handler_scaling=_handler,
        loopback=_loop,
        payload_size_bytes=payload_size_bytes,
        uvicorn_backlog=_K_list[0],
        c_srv=1,
    )

    if int(_obs["n"].size) == 0:
        return {}

    # tile every per-n array K_count times so each K block spans every n_con_usr level; K + M_buf rebuilt directly from K_list because they're the only quantities that vary across K
    _N_n = int(_obs["n"].size)
    _N_K = len(_K_list)
    if _N_K > 1:
        _obs_tiled: Dict[str, np.ndarray] = {}
        for _key, _val in _obs.items():
            if _key in ("K", "M_buf"):
                continue
            _obs_tiled[_key] = np.tile(np.asarray(_val, dtype=float), _N_K)
        _K_full = np.repeat(np.asarray(_K_list, dtype=float), _N_n)
        _obs_tiled["K"] = _K_full
        _d_kB = float(payload_size_bytes) / 1000.0
        _obs_tiled["M_buf"] = _K_full * _d_kB
        _obs = _obs_tiled

    # cap L at K so the dimensional invariant theta = L/K <= 1 holds; M_act follows because phi = M_act/M_buf must also stay <= 1 by the same invariant.
    _L_arr = np.asarray(_obs["L"], dtype=float)
    _K_arr = np.asarray(_obs["K"], dtype=float)
    _obs["L"] = np.minimum(_L_arr, _K_arr)
    _d_kB = float(payload_size_bytes) / 1000.0
    _obs["M_act"] = _obs["L"] * _d_kB

    _n_levels = int(_obs["n"].size)

    _vars_block = _build_calib_vars(_obs, tag=tag)
    _coef_arrays = _run_calib_pipeline(_vars_block, n_levels=_n_levels, tag=tag)

    # phi is degenerate (0/0) when no payload was supplied; force NaN so the dashboard skips the panel
    _phi_key = f"\\phi_{{{tag}}}"
    if int(payload_size_bytes) <= 0 and _phi_key in _coef_arrays:
        _coef_arrays[_phi_key] = np.full(_n_levels, np.nan, dtype=float)

    # carry the input-side context arrays alongside the coefficients so plot_yoly_chart panel labels stay honest
    _context = {
        f"c_{{{tag}}}": _obs["c"],
        f"\\mu_{{{tag}}}": _obs["mu"],
        f"K_{{{tag}}}": _obs["K"],
        f"\\lambda_{{{tag}}}": _obs["lam"],
        f"n_con_usr_{{{tag}}}": _obs["n"],
        f"n_con_usr_demand_{{{tag}}}": _obs["n"],
        f"reject_rate_{{{tag}}}": _obs.get("reject_rate", np.zeros_like(_obs["n"])),
    }

    _coefs: Dict[str, Any] = {}
    for _k, _v in _coef_arrays.items():
        _coefs[_k] = [float(_x) for _x in np.asarray(_v, dtype=float).tolist()]
    for _k, _v in _context.items():
        _coefs[_k] = [float(_x) for _x in np.asarray(_v, dtype=float).tolist()]

    if _obs["mu"].size > 0:
        _mu_val = float(_obs["mu"][0])
    else:
        _mu_val = 0.0
    _coefs["meta"] = {
        "tag": str(tag),
        "mu_source": "loopback.median_us",
        "mu_req_per_s": _mu_val,
        "c_srv": 1,
        "uvicorn_backlog": _backlog,
        "K_values": _K_list,
        "payload_size_bytes": int(payload_size_bytes),
        "n_con_usr": [int(_n) for _n in np.asarray(_obs["n"], dtype=float).tolist()],
        "pipeline": "pydasa.MonteCarloSimulation(mode=DATA)",
    }
    return _coefs
