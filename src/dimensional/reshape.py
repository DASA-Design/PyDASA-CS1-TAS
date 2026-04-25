# -*- coding: utf-8 -*-
"""
Module reshape.py
=================

Result-envelope reshapers for the dimensional method. Turn the per-artifact dict produced by `src.methods.dimensional.run` into the flat pandas shapes the `src.view` plotter family consumes (`plot_nd_diffmap`, `plot_net_delta`, `plot_yoly_chart`, `plot_yoly_arts_charts`, ...).

Public API:
    - `coefs_to_nodes(result)` per-node DataFrame with one row per artifact and columns `key`, `theta`, `sigma`, `eta`, `phi` (only those coefficients that were derived).
    - `coefs_to_net(result, agg="mean")` single-row DataFrame of network-wide aggregates across artifacts.
    - `compute_coefs_delta(nds_dflt, nds_other, *, pct=True)` the fractional change frame used by `plot_nd_diffmap` / `plot_net_delta`.
    - `aggregate_arch_coefs(result, tag="TAS")` PACS-iter2-style architecture-level aggregate (sum first, divide after).
    - `aggregate_sweep_to_arch(sweep_data, tag="TAS")` collapse per-artifact sweep arrays into flat architecture-level arrays.
    - `compute_net_delta(net_dflt, net_other, *, pct=True)` network-wide delta frame.

*IMPORTANT:* in `coefs_to_nodes` / `coefs_to_net` / `compute_coefs_delta` coefficient names drop the artifact subscript (the symbol `\\theta_{TAS_{1}}` becomes column `theta`) so plotters see uniform column names across artifacts; `aggregate_arch_coefs` and `aggregate_sweep_to_arch` keep the subscript (their output already represents a single architecture-level entity tagged once).
"""
# native python modules
from __future__ import annotations

# data types
from typing import Any, Dict, List

# scientific stack
import numpy as np
import pandas as pd


# short-name map: PACS LaTeX coefficient keys -> flat pandas column names
_COEF_NAMES = ("theta", "sigma", "eta", "phi")


def _safe_div(num: float, den: float) -> float:
    """*_safe_div()* divide `num` by `den` with a zero-denominator guard.

    Args:
        num (float): numerator.
        den (float): denominator. Non-positive (zero or negative) values short-circuit to 0.0.

    Returns:
        float: `num / den` when `den > 0`, else `0.0`. Avoids the four-line `if/else` repeat that the architecture-level aggregator would otherwise carry per coefficient.
    """
    if den > 0:
        return num / den
    return 0.0


def _per_combo_mean(sweep_data: Dict[str, Dict[str, np.ndarray]],
                    art_keys: List[str],
                    sym_template: str) -> np.ndarray:
    """*_per_combo_mean()* average a per-artifact array (e.g. `c_{<art>}`, `\\mu_{<art>}`, `K_{<art>}`) across the artifact axis at every sweep point.

    Used in `aggregate_sweep_to_arch` because uniform `(mu_factor, c, K)` overrides per combo make every artifact's value identical at a given sweep index; the mean equals any-artifact value but is a defensive choice.

    Args:
        sweep_data (Dict[str, Dict[str, np.ndarray]]): nested sweep output (artifact_key -> per-combo block).
        art_keys (List[str]): artifact key list to iterate.
        sym_template (str): str.format-style template with a `{art}` placeholder. Pass with literal-brace escaping for the LaTeX subscript braces, e.g. `"c_{{{art}}}"`, `"\\\\mu_{{{art}}}"`, `"K_{{{art}}}"`. The `{art}` token is substituted with each artifact key when looking up the per-block array.

    Returns:
        np.ndarray: mean across artifacts at every sweep index; shape matches the per-artifact arrays.
    """
    _stack = np.stack([sweep_data[_k][sym_template.format(art=_k)]
                       for _k in art_keys])
    return np.mean(_stack, axis=0)


def _extract_coef_column(full_sym: str) -> str:
    """*_extract_coef_column()* extract the short coefficient name (e.g. `theta`) from a PACS-form symbol like `\\theta_{TAS_{1}}`.

    Args:
        full_sym (str): coefficient symbol as stored in the orchestrator result.

    Returns:
        str: the short name (one of `theta`, `sigma`, `eta`, `phi`, ...); returns the stem after the leading backslash if no match.
    """
    # strip the leading backslash and split off the first subscript brace
    _stem = full_sym.lstrip("\\").split("_", 1)[0]
    return _stem


def coefs_to_nodes(result: Dict[str, Any]) -> pd.DataFrame:
    """*coefs_to_nodes()* flattens per-artifact coefficients into a per-node DataFrame.

    Args:
        result (Dict[str, Any]): result dict returned by `src.methods.dimensional.run`.

    Returns:
        pd.DataFrame: one row per artifact with columns `key`, `name`, `type`, and one per derived coefficient (`theta`, `sigma`, `eta`, `phi`).
    """
    _rows: List[dict] = []

    # walk artifacts in declared order to preserve topology alignment
    for _k, _a in result["artifacts"].items():
        _row = {"key": _k, "name": _a["name"], "type": _a["type"]}

        # flatten each derived coefficient to a short column name
        for _sym, _co in _a["coefficients"].items():
            _row[_extract_coef_column(_sym)] = float(_co["setpoint"])

        _rows.append(_row)

    return pd.DataFrame(_rows)


def coefs_to_net(result: Dict[str, Any],
                 *,
                 agg: str = "mean") -> pd.DataFrame:
    """*coefs_to_net()* aggregates coefficient values across artifacts into a single-row network frame.

    Args:
        result (Dict[str, Any]): result dict returned by `src.methods.dimensional.run`.
        agg (str): aggregation function name; one of `"mean"`, `"median"`, `"max"`, `"min"`. Defaults to `"mean"`.

    Raises:
        ValueError: If `agg` is not one of the supported reducer names.

    Returns:
        pd.DataFrame: single-row frame with `nodes` (count) and one column per derived coefficient carrying the aggregate value.
    """
    # guard against typos in the reducer name
    _fn_lt = {
        "mean": np.mean,
        "median": np.median,
        "max": np.max,
        "min": np.min
    }

    if agg not in _fn_lt:
        _msg = f"unknown aggregator {agg!r}; expected one of {list(_fn_lt)}"
        raise ValueError(_msg)

    # reuse the per-node frame so the reducer sees a single numeric column
    _nds = coefs_to_nodes(result)
    _row: Dict[str, float] = {"nodes": float(len(_nds))}
    for _c in _COEF_NAMES:
        if _c in _nds.columns:
            _row[_c] = float(_fn_lt[agg](_nds[_c]))
    return pd.DataFrame([_row])


def compute_coefs_delta(nds_dflt: pd.DataFrame,
                        nds_other: pd.DataFrame,
                        *,
                        pct: bool = True,
                        cname: str = "key") -> pd.DataFrame:
    """*compute_coefs_delta()* computes the per-node coefficient delta between two scenarios.

    Args:
        nds_dflt (pd.DataFrame): baseline per-node frame (reference).
        nds_other (pd.DataFrame): adapted per-node frame (subject).
        pct (bool): if True (default), return fractional change `(other - dflt) / |dflt|`; if False, return absolute change `other - dflt`.
        cname (str): column holding the node identifier. Defaults to `"key"`.

    Returns:
        pd.DataFrame: per-node delta frame with `key` and the shared coefficient columns. Only nodes present in BOTH frames are included; the order follows `nds_dflt`. This lets callers compare a 13-node baseline against a 16-node aggregate (the extra swap-slot nodes are silently dropped).
    """
    # intersect node sets; preserve nds_dflt order so the output aligns with the baseline topology
    _other_keys = set(nds_other[cname])
    _keys_common: List[str] = []
    for _k in nds_dflt[cname]:
        if _k in _other_keys:
            _keys_common.append(_k)

    # restrict to the columns that both frames share (handles partial specs)
    _metrics: List[str] = []
    for _c in _COEF_NAMES:
        _in_dflt = _c in nds_dflt.columns
        _in_other = _c in nds_other.columns
        if _in_dflt and _in_other:
            _metrics.append(_c)

    # index both frames by node key so we can look up each row directly
    _d_idx = nds_dflt.set_index(cname)
    _o_idx = nds_other.set_index(cname)

    _out = pd.DataFrame({cname: _keys_common})
    for _m in _metrics:
        _d = _d_idx.loc[_keys_common, _m].to_numpy(dtype=float)
        _o = _o_idx.loc[_keys_common, _m].to_numpy(dtype=float)
        # fractional delta protected against zero reference values
        _denom = np.where(_d == 0, 1.0, np.abs(_d))
        if pct:
            _out[_m] = (_o - _d) / _denom
        else:
            _out[_m] = _o - _d

    return _out


def aggregate_arch_coefs(result: Dict[str, Any],
                         *,
                         tag: str = "TAS") -> pd.DataFrame:
    """*aggregate_arch_coefs()* compute one architecture-level coefficient set by summing raw per-node variables first and dividing after; the PACS-iter2 aggregation pattern.

    This answers *"what is the TAS as a WHOLE doing?"* rather than *"what is the typical node doing?"*. The per-node `coefs_to_net` averages pre-computed per-node coefficients; this one sums raw L, K, lambda, ... across every artifact in the network and derives ONE theta / sigma / eta / phi / epsilon at the architecture level.

        - theta_arch = (sum L_i) / (sum K_i)
        - sigma_arch = (sum lambda_i * W_i) / (sum K_i)
        - eta_arch   = (sum chi_i * K_i) / (sum mu_i * c_i)
        - phi_arch   = (sum M_act_i) / (sum M_buf_i)
        - epsilon_arch = 1 - prod(1 - epsilon_i)

    Args:
        result (Dict[str, Any]): result dict returned by `src.methods.dimensional.run`. Must carry `config` (a `NetCfg`) so raw per-artifact variable setpoints can be read. Each artifact's `vars` block must carry the literal keys `L_{<key>}`, `K_{<key>}`, `W_{<key>}`, `\\lambda_{<key>}`, `\\chi_{<key>}`, `\\mu_{<key>}`, `c_{<key>}`, `M_{act_{<key>}}`, `M_{buf_{<key>}}`, `\\epsilon_{<key>}` (PACS variable schema).
        tag (str): architecture subscript to use in the output column keys. Defaults to `"TAS"` so columns become `\\theta_{TAS}`, `\\sigma_{TAS}`, ..., matching the PACS iter2 `\\theta_{PACS}` convention one-for-one.

    Returns:
        pd.DataFrame: single-row frame with `nodes` (count) plus `\\theta_{<tag>}`, `\\sigma_{<tag>}`, `\\eta_{<tag>}`, `\\phi_{<tag>}`, `\\epsilon_{<tag>}`.

    Raises:
        KeyError: when an artifact's `vars` block lacks one of the expected setpoints (any of L, K, W, lambda, chi, mu, c, M_act, M_buf, epsilon).
    """
    _cfg = result["config"]
    _arts = _cfg.artifacts

    # accumulators across every artifact in the resolved NetCfg
    _sum_L = 0.0
    _sum_K = 0.0
    _sum_lamW = 0.0
    _sum_chi_K = 0.0
    _sum_mu_c = 0.0
    _sum_m_act = 0.0
    _sum_m_buf = 0.0
    _prod_1_minus_eps = 1.0

    # walk artifacts in declared order; one setpoint read per variable
    for _a in _arts:
        _key = _a.key
        _v = _a.vars

        # raw per-node setpoints (these are already seeded from analytic)
        _L = float(_v[f"L_{{{_key}}}"]["_setpoint"])
        _K = float(_v[f"K_{{{_key}}}"]["_setpoint"])
        _W = float(_v[f"W_{{{_key}}}"]["_setpoint"])
        _lam = float(_v[f"\\lambda_{{{_key}}}"]["_setpoint"])
        _chi = float(_v[f"\\chi_{{{_key}}}"]["_setpoint"])
        _mu = float(_v[f"\\mu_{{{_key}}}"]["_setpoint"])
        _c = float(_v[f"c_{{{_key}}}"]["_setpoint"])
        _m_act = float(_v[f"M_{{act_{{{_key}}}}}"]["_setpoint"])
        _m_buf = float(_v[f"M_{{buf_{{{_key}}}}}"]["_setpoint"])
        _eps = float(_v[f"\\epsilon_{{{_key}}}"]["_setpoint"])

        _sum_L += _L
        _sum_K += _K
        _sum_lamW += _lam * _W
        _sum_chi_K += _chi * _K
        _sum_mu_c += _mu * _c
        _sum_m_act += _m_act
        _sum_m_buf += _m_buf
        _prod_1_minus_eps *= (1.0 - _eps)

    # derive architecture-level coefficients (zero-denominator guard via _safe_div)
    _theta_arch = _safe_div(_sum_L, _sum_K)
    _sigma_arch = _safe_div(_sum_lamW, _sum_K)
    _eta_arch = _safe_div(_sum_chi_K, _sum_mu_c)
    _phi_arch = _safe_div(_sum_m_act, _sum_m_buf)
    _eps_arch = 1.0 - _prod_1_minus_eps

    # assemble the single-row envelope; keys follow the PACS-style subscript
    _row = {
        "nodes": float(len(_arts)),
        f"\\theta_{{{tag}}}": _theta_arch,
        f"\\sigma_{{{tag}}}": _sigma_arch,
        f"\\eta_{{{tag}}}": _eta_arch,
        f"\\phi_{{{tag}}}": _phi_arch,
        f"\\epsilon_{{{tag}}}": _eps_arch,
    }
    return pd.DataFrame([_row])


def aggregate_sweep_to_arch(sweep_data: Dict[str, Dict[str, np.ndarray]],
                            *,
                            tag: str = "TAS") -> Dict[str, np.ndarray]:
    """*aggregate_sweep_to_arch()* collapses per-artifact sweep arrays (from `sweep_arch`) into flat architecture-level arrays via PACS-iter2 aggregation applied point-by-point.

    Expects the per-node arrays to be aligned across artifacts (same row = same whole-network sweep point), as produced by `sweep_arch`.

    Aggregation at each sweep index `k`:

        - theta_arch[k] = (sum_i L_i[k]) / (sum_i K_i[k])
        - sigma_arch[k] = (sum_i lambda_i[k] * W_i[k]) / (sum_i K_i[k])
        - eta_arch[k]   = (sum_i chi_i[k] * K_i[k]) / (sum_i mu_i[k] * c_i[k])
        - phi_arch[k]   = (sum_i M_act_i[k]) / (sum_i M_buf_i[k])
        - lambda_arch[k] = sum_i lambda_i[k]             # total traffic through the network

    Args:
        sweep_data (Dict[str, Dict[str, np.ndarray]]): nested output from `sweep_arch`. Every per-artifact block must carry `\\theta_{X}`, `\\sigma_{X}`, `\\eta_{X}`, `c_{X}`, `\\mu_{X}`, `K_{X}`, `\\lambda_{X}` arrays of the same length.
        tag (str): architecture subscript applied to the flat output keys. Defaults to `"TAS"` so outputs are `\\theta_{TAS}`, `\\sigma_{TAS}`, ....

    Returns:
        Dict[str, np.ndarray]: flat dict keyed by full LaTeX symbol with `tag` subscript. Shape-compatible with `src.view.plot_yoly_chart` and `src.view.plot_system_behaviour` (they look up by semantic prefix).
    """
    _art_keys = list(sweep_data.keys())
    if not _art_keys:
        # empty sweep -> empty arrays
        _empty = np.asarray([], dtype=float)
        return {f"\\theta_{{{tag}}}": _empty, f"\\sigma_{{{tag}}}": _empty,
                f"\\eta_{{{tag}}}": _empty, f"\\phi_{{{tag}}}": _empty,
                f"c_{{{tag}}}": _empty, f"\\mu_{{{tag}}}": _empty,
                f"K_{{{tag}}}": _empty, f"\\lambda_{{{tag}}}": _empty}

    # one artifact decides the sweep length; sweep_arch guarantees alignment across artifacts
    _first = _art_keys[0]
    _n = len(sweep_data[_first][f"\\theta_{{{_first}}}"])

    # point-by-point accumulators
    _sum_L = np.zeros(_n)
    _sum_K = np.zeros(_n)
    _sum_lamW = np.zeros(_n)
    _sum_chi_K = np.zeros(_n)
    _sum_mu_c = np.zeros(_n)
    _sum_lam = np.zeros(_n)

    for _k in _art_keys:
        _block = sweep_data[_k]
        _theta = _block[f"\\theta_{{{_k}}}"]
        _sigma = _block[f"\\sigma_{{{_k}}}"]
        _eta = _block[f"\\eta_{{{_k}}}"]
        _K = _block[f"K_{{{_k}}}"]
        _c = _block[f"c_{{{_k}}}"]
        _mu = _block[f"\\mu_{{{_k}}}"]
        _lam = _block[f"\\lambda_{{{_k}}}"]

        # reconstruct raw node vars (L, lam*W, chi*K) from stored ratios so we can sum point-by-point
        _L = _theta * _K
        _lam_W = _sigma * _K
        _chi_K = _eta * _mu * _c

        _sum_L += _L
        _sum_K += _K
        _sum_lamW += _lam_W
        _sum_chi_K += _chi_K
        _sum_mu_c += _mu * _c
        _sum_lam += _lam

    # guard against zero denominators on unstable / empty slices via per-element where-clamp
    _K_safe = np.where(_sum_K > 0, _sum_K, 1.0)
    _muc_safe = np.where(_sum_mu_c > 0, _sum_mu_c, 1.0)
    _theta_arch = np.where(_sum_K > 0, _sum_L / _K_safe, 0.0)
    _sigma_arch = np.where(_sum_K > 0, _sum_lamW / _K_safe, 0.0)
    _eta_arch = np.where(_sum_mu_c > 0, _sum_chi_K / _muc_safe, 0.0)
    # phi = M_act/M_buf = (L*delta)/(K*delta) = L/K = theta under the CS-01 TAS schema
    _phi_arch = _theta_arch

    # uniform (mu_factor, c, K) override per combo means mean == any-artifact value
    _c_mean = _per_combo_mean(sweep_data, _art_keys, "c_{{{art}}}")
    _mu_mean = _per_combo_mean(sweep_data, _art_keys, "\\mu_{{{art}}}")
    _K_mean = _per_combo_mean(sweep_data, _art_keys, "K_{{{art}}}")
    _ans = {
        f"\\theta_{{{tag}}}": _theta_arch,
        f"\\sigma_{{{tag}}}": _sigma_arch,
        f"\\eta_{{{tag}}}": _eta_arch,
        f"\\phi_{{{tag}}}": _phi_arch,
        f"c_{{{tag}}}": _c_mean,
        f"\\mu_{{{tag}}}": _mu_mean,
        f"K_{{{tag}}}": _K_mean,
        f"\\lambda_{{{tag}}}": _sum_lam,
    }
    return _ans


def compute_net_delta(net_dflt: pd.DataFrame,
                      net_other: pd.DataFrame,
                      *,
                      pct: bool = True) -> pd.DataFrame:
    """*compute_net_delta()* computes the network-wide coefficient delta between two scenarios.

    Args:
        net_dflt (pd.DataFrame): baseline single-row network frame, typically the output of `coefs_to_net`.
        net_other (pd.DataFrame): adapted single-row network frame; same shape as `net_dflt`. Both must be single-row; only the first row (`.iloc[0]`) is read.
        pct (bool): if True (default), return fractional change; if False, return absolute change.

    Returns:
        pd.DataFrame: single-row frame with one column per shared coefficient.
    """
    # work only with shared coefficient columns, ignore `nodes` etc.
    _metrics: List[str] = []
    for _c in _COEF_NAMES:
        _in_dflt = _c in net_dflt.columns
        _in_other = _c in net_other.columns
        if _in_dflt and _in_other:
            _metrics.append(_c)

    _row: Dict[str, float] = {}
    for _m in _metrics:
        _d = float(net_dflt[_m].iloc[0])
        _o = float(net_other[_m].iloc[0])
        if _d != 0:
            _denom = abs(_d)
        else:
            _denom = 1.0
        if pct:
            _row[_m] = (_o - _d) / _denom
        else:
            _row[_m] = _o - _d

    return pd.DataFrame([_row])
