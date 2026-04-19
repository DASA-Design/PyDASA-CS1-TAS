# -*- coding: utf-8 -*-
"""
Module reshape.py
=================

Result-envelope reshapers for the dimensional method. Turn the per-artifact
dict produced by `src.methods.dimensional.run` into the flat pandas shapes
the existing `src.view.qn_diagram` plotters consume.

    - `coefficients_to_nodes(result)` returns a per-node DataFrame with one row per artifact and columns `key`, `theta`, `sigma`, `eta`, `phi` (only those coefficients that were derived).
    - `coefficients_to_network(result, agg="mean")` returns a single-row DataFrame of network-wide aggregates across artifacts.
    - `coefficients_delta(nds_dflt, nds_other, *, pct=True)` returns the fractional change frame used by `plot_nd_diffmap` / `plot_net_delta`.

*IMPORTANT:* coefficient names drop the artifact subscript here (e.g. the
symbol `\\theta_{TAS_{1}}` becomes the column `theta`) so the plotters see
uniform column names across artifacts.
"""
# native python modules
from __future__ import annotations

# data types
from typing import Any, Dict, List

# scientific stack
import numpy as np
import pandas as pd


# short-name mapping from the PACS LaTeX symbols used in coefficient keys
# to flat pandas column names
_COEF_NAMES = ("theta", "sigma", "eta", "phi")


def _coef_column(full_sym: str) -> str:
    """*_coef_column()* extracts the short coefficient name (e.g. `theta`) from a PACS-form symbol like `\\theta_{TAS_{1}}`.

    Args:
        full_sym (str): coefficient symbol as stored in the orchestrator result.

    Returns:
        str: the short name (one of `theta`, `sigma`, `eta`, `phi`, ...); returns the stem after the leading backslash if no match.
    """
    # strip the leading backslash and split off the first subscript brace
    _stem = full_sym.lstrip("\\").split("_", 1)[0]
    return _stem


def coefficients_to_nodes(result: Dict[str, Any]) -> pd.DataFrame:
    """*coefficients_to_nodes()* flattens per-artifact coefficients into a per-node DataFrame.

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
            _row[_coef_column(_sym)] = float(_co["setpoint"])

        _rows.append(_row)

    return pd.DataFrame(_rows)


def coefficients_to_network(result: Dict[str, Any],
                            *,
                            agg: str = "mean") -> pd.DataFrame:
    """*coefficients_to_network()* aggregates coefficient values across artifacts into a single-row network frame.

    Args:
        result (Dict[str, Any]): result dict returned by `src.methods.dimensional.run`.
        agg (str): aggregation function name; one of `"mean"`, `"median"`, `"max"`, `"min"`. Defaults to `"mean"`.

    Raises:
        ValueError: If `agg` is not one of the supported reducer names.

    Returns:
        pd.DataFrame: single-row frame with `nodes` (count) and one column per derived coefficient carrying the aggregate value.
    """
    # guard against typos in the reducer name
    _fn_lt = {"mean": np.mean,
              "median": np.median,
              "max": np.max,
              "min": np.min}
    if agg not in _fn_lt:
        _msg = f"unknown aggregator {agg!r}; expected one of {list(_fn_lt)}"
        raise ValueError(_msg)

    # reuse the per-node frame so the reducer sees a single numeric column
    _nds = coefficients_to_nodes(result)
    _row: Dict[str, float] = {"nodes": float(len(_nds))}
    for _c in _COEF_NAMES:
        if _c in _nds.columns:
            _row[_c] = float(_fn_lt[agg](_nds[_c]))
    return pd.DataFrame([_row])


def coefficients_delta(nds_dflt: pd.DataFrame,
                       nds_other: pd.DataFrame,
                       *,
                       pct: bool = True,
                       cname: str = "key") -> pd.DataFrame:
    """*coefficients_delta()* computes the per-node coefficient delta between two scenarios.

    Args:
        nds_dflt (pd.DataFrame): baseline per-node frame (reference).
        nds_other (pd.DataFrame): adapted per-node frame (subject).
        pct (bool): if True (default), return fractional change `(other - dflt) / |dflt|`; if False, return absolute change `other - dflt`.
        cname (str): column holding the node identifier. Defaults to `"key"`.

    Returns:
        pd.DataFrame: per-node delta frame with `key` and the shared coefficient columns. Only nodes present in BOTH frames are included; the order follows `nds_dflt`. This lets callers compare a 13-node baseline against a 16-node aggregate (the extra swap-slot nodes are silently dropped).
    """
    # intersect node sets; preserve nds_dflt order so the output row
    # order is deterministic and aligns with the baseline topology
    _keys_common = [_k for _k in nds_dflt[cname]
                    if _k in set(nds_other[cname])]

    # restrict to the columns that both frames share (handles partial specs)
    _metrics = [_c for _c in _COEF_NAMES
                if _c in nds_dflt.columns and _c in nds_other.columns]

    # index both frames by node key so we can look up each row directly
    _d_idx = nds_dflt.set_index(cname)
    _o_idx = nds_other.set_index(cname)

    _out = pd.DataFrame({cname: _keys_common})
    for _m in _metrics:
        _d = _d_idx.loc[_keys_common, _m].to_numpy(dtype=float)
        _o = _o_idx.loc[_keys_common, _m].to_numpy(dtype=float)
        # fractional delta protected against zero reference values
        _denom = np.where(_d == 0, 1.0, np.abs(_d))
        _out[_m] = (_o - _d) / _denom if pct else (_o - _d)

    return _out


def network_delta(net_dflt: pd.DataFrame,
                  net_other: pd.DataFrame,
                  *,
                  pct: bool = True) -> pd.DataFrame:
    """*network_delta()* computes the network-wide coefficient delta between two scenarios.

    Args:
        net_dflt (pd.DataFrame): baseline single-row network frame.
        net_other (pd.DataFrame): adapted single-row network frame.
        pct (bool): if True (default), return fractional change; if False, return absolute change.

    Returns:
        pd.DataFrame: single-row frame with one column per shared coefficient.
    """
    # work only with shared coefficient columns, ignore `nodes` etc.
    _metrics = [_c for _c in _COEF_NAMES
                if _c in net_dflt.columns and _c in net_other.columns]

    _row: Dict[str, float] = {}
    for _m in _metrics:
        _d = float(net_dflt[_m].iloc[0])
        _o = float(net_other[_m].iloc[0])
        _denom = abs(_d) if _d != 0 else 1.0
        _row[_m] = (_o - _d) / _denom if pct else (_o - _d)

    return pd.DataFrame([_row])
