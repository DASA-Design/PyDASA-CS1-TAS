# -*- coding: utf-8 -*-
"""
Module metrics.py
=================

Network-wide aggregates and R1 / R2 / R3 validation for the analytic method of the TAS case study.

Two layers, kept separate so the aggregation math can be unit-tested independently of the validation thresholds:

    - `aggregate_net(nodes)` reduces the per-node DataFrame into a single network-wide row (same semantics as the old `calculate_net_metrics` in `__OLD__/src/model/analytical.py`).
    - `check_reqs(nodes, ...)` evaluates the R1 / R2 / R3 targets against the thresholds declared in a reference file (default: `data/reference/baseline.json`, which carries the Camara 2023 values):

        R1  failure rate   <= 0.03 %   (Availability)
        R2  response time  <= 26 ms    (Performance)
        R3  cost           minimise subject to (R1 and R2)

*IMPORTANT:* thresholds are NOT hardcoded in this module; they live in `data/reference/<name>.json` so the case-study ground truth can be edited without touching Python. R3 carries no hard threshold; it is a ranking concern, not a pass / fail. The returned dict's `R3.pass` is `True` whenever both R1 and R2 hold. Downstream ranking across runs is left to the `comparison` method.

# TODO: wire a real cost model (from the service catalogue) and use it to rank runs under the R1 and R2 feasibility set.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, Optional

# scientific stack
import numpy as np
import pandas as pd

# local modules
from src.io import load_reference


def aggregate_net(nodes: pd.DataFrame) -> pd.DataFrame:
    """*aggregate_net()* reduces the per-node metrics frame into a single network-wide row.

    Args:
        nodes (pd.DataFrame): per-node metrics as produced by `solve_network()`. Required columns: `lambda`, `mu`, `rho`, `L`, `Lq`, `W`, `Wq`.

    Returns:
        pd.DataFrame: a single-row frame with the columns:

            - `nodes` (int): number of nodes summarised.
            - `total_throughput` (float): sum of per-node `lambda`.
            - `avg_mu` (float): arithmetic mean of service rates.
            - `avg_rho` (float): arithmetic mean of utilizations.
            - `max_rho` (float): worst-case saturation across nodes.
            - `L_net` (float): sum of L across nodes.
            - `Lq_net` (float): sum of Lq across nodes.
            - `W_net` (float): throughput-weighted mean of W.
            - `Wq_net` (float): throughput-weighted mean of Wq.
    """
    # pull the per-node arrival rates once for the weighted means
    _lambdas = nodes["lambda"].to_numpy(dtype=float)
    _total_lambda = float(_lambdas.sum())

    # throughput-weighted means of W and Wq; guard against a fully idle network to avoid 0 / 0
    if _total_lambda > 0:
        _numer_w = np.sum(nodes["W"].to_numpy() * _lambdas)
        _numer_wq = np.sum(nodes["Wq"].to_numpy() * _lambdas)
        _w_net = float(_numer_w / _total_lambda)
        _wq_net = float(_numer_wq / _total_lambda)
    # otherwise, no flow anywhere: network-wide waits collapse to 0
    else:
        _w_net = 0.0
        _wq_net = 0.0

    # assemble the single aggregated row
    _row = {
        "nodes": len(nodes),
        "total_throughput": _total_lambda,
        "avg_mu": float(nodes["mu"].mean()),
        "avg_rho": float(nodes["rho"].mean()),
        "max_rho": float(nodes["rho"].max()),
        "L_net": float(nodes["L"].sum()),
        "Lq_net": float(nodes["Lq"].sum()),
        "W_net": _w_net,
        "Wq_net": _wq_net,
    }
    return pd.DataFrame([_row])


def check_reqs(
    nodes: pd.DataFrame,
    failure_rate: Optional[float] = None,
    response_time: Optional[float] = None,
    cost: Optional[float] = None,
    reference: str = "baseline",
) -> Dict[str, Dict[str, Any]]:
    """*check_reqs()* evaluates the R1 / R2 / R3 targets against the thresholds declared in a reference file, using either caller-supplied values or values derived from the per-node frame.

    Thresholds come from `data/reference/<reference>.json` (default `baseline.json`, which carries the Camara 2023 values). When the `failure_rate` / `response_time` kwargs are omitted, the defaults are derived as follows:

        - `failure_rate` from per-node `epsilon` (mean) if that column is present on `nodes`; otherwise assumed 0.0 (analytic model without faults).
        - `response_time` from the throughput-weighted network `W` returned by `aggregate_net()`.
        - `cost` is not derivable from analytic-only results; callers pass it in from the service catalogue, or accept `None` (in which case the R3 value is recorded as `None` but the pass verdict still follows R1 and R2).

    Args:
        nodes (pd.DataFrame): per-node metrics frame.
        failure_rate (Optional[float]): override for the network-wide failure rate. Defaults to None.
        response_time (Optional[float]): override for the network-wide response time in seconds. Defaults to None.
        cost (Optional[float]): network-wide cost, recorded as-is. Defaults to None.
        reference (str): reference file stem in `data/reference/` to pull thresholds from. Defaults to `"baseline"`.

    Returns:
        Dict[str, Dict[str, Any]]: verdicts keyed by `R1`, `R2`, `R3`. Each verdict carries `metric`, `value`, `threshold`, `operator`, `units`, `pass`, and `notes`.
    """
    # load the reference thresholds and per-requirement metadata
    _ref = load_reference(reference)
    _reqs = _ref["requirements"]

    # derive the failure rate: explicit override > per-node column > 0
    _fail_rate = failure_rate
    if _fail_rate is None and "epsilon" in nodes.columns:
        _fail_rate = float(nodes["epsilon"].mean())
    if _fail_rate is None:
        _fail_rate = 0.0

    # derive the response time: explicit override > throughput-weighted W
    _resp = response_time
    if _resp is None:
        _agg = aggregate_net(nodes)
        _resp = float(_agg["W_net"].iloc[0])

    # evaluate each hard-threshold requirement
    _r1_pass = bool(_fail_rate <= _reqs["R1"]["threshold"])
    _r2_pass = bool(_resp <= _reqs["R2"]["threshold"])
    # R3 has no hard threshold; it passes iff R1 and R2 both hold
    _r3_pass = _r1_pass and _r2_pass

    # pack the per-requirement measured value and pass flag
    _measured = {
        "R1": (_fail_rate, _r1_pass),
        "R2": (_resp, _r2_pass),
        "R3": (cost, _r3_pass),
    }

    # assemble the verdict dict; metadata (operator, units, notes) flows through from the reference file so it stays single-sourced
    _verdicts: Dict[str, Dict[str, Any]] = {}
    for _k, (_val, _ok) in _measured.items():
        _spec = _reqs[_k]
        _verdicts[_k] = {
            "metric": _spec["metric"],
            "value": _val,
            "threshold": _spec["threshold"],
            "operator": _spec["operator"],
            "units": _spec["units"],
            "pass": _ok,
            "notes": _spec["notes"],
        }

    return _verdicts
