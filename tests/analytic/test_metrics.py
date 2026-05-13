# -*- coding: utf-8 -*-
"""
Module test_metrics.py
======================

Sanity checks for the network-wide aggregator and the R1 / R2 verdict logic in `src.analytic.metrics`.

    - **TestAggregateNetwork** the aggregation math on small, hand-computable per-node frames (throughput, weighted means, sums, zero-lambda guard).
    - **TestCheckRequirements** R1 / R2 verdicts against the Camara 2023 thresholds, including override kwargs and the per-node `epsilon` fallback path.
    - **TestThresholdsFromReference** the verdict's threshold / operator / units come from `data/reference/baseline.json` (single source of truth).
"""
# data types
from typing import Any, Dict, List

# scientific stack
import pandas as pd

# testing framework
import pytest

# modules under test
from src.analytic.metrics import (aggregate_net,
                                  check_reqs)
from src.io import load_reference


def _make_nodes(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    """*_make_nodes()* per-node DataFrame from a list of dicts; sensible defaults fill any column the caller omits.

    Args:
        rows (List[Dict[str, Any]]): per-node column overrides.

    Returns:
        pd.DataFrame: per-node metrics frame ready for aggregation.
    """
    _defaults = {
        "lambda": 0.0,
        "mu": 1.0,
        "c": 1,
        "K": None,
        "rho": 0.0,
        "L": 0.0,
        "Lq": 0.0,
        "W": 0.0,
        "Wq": 0.0,
    }
    _filled = [{**_defaults, **_r} for _r in rows]
    return pd.DataFrame(_filled)


class TestAggregateNetwork:
    """**TestAggregateNetwork** verifies that the per-node to network-wide reduction matches hand-computed expectations on small frames."""

    def test_totals_and_max(self) -> None:
        """*test_totals_and_max()* `nodes == 2`, `total_throughput == 40.0`, `avg_rho == 0.5`, `max_rho == 0.8`, `avg_mu == 50.0`, `L_net == 3.0`, `Lq_net == 1.4`."""
        _nodes = _make_nodes([
            {"lambda": 10.0, "mu": 50.0, "rho": 0.2,
             "L": 1.0, "Lq": 0.4},
            {"lambda": 30.0, "mu": 50.0, "rho": 0.8,
             "L": 2.0, "Lq": 1.0},
        ])
        _agg = aggregate_net(_nodes).iloc[0]
        assert _agg["nodes"] == 2
        assert _agg["total_throughput"] == pytest.approx(40.0)
        assert _agg["avg_rho"] == pytest.approx(0.5)
        assert _agg["max_rho"] == pytest.approx(0.8)
        assert _agg["avg_mu"] == pytest.approx(50.0)
        assert _agg["L_net"] == pytest.approx(3.0)
        assert _agg["Lq_net"] == pytest.approx(1.4)

    def test_weighted_w_net(self) -> None:
        """*test_weighted_w_net()* `W_net == (10*0.1 + 30*0.5) / 40 == 0.4`; `Wq_net == (10*0.05 + 30*0.25) / 40 == 0.2`."""
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.1, "Wq": 0.05},
            {"lambda": 30.0, "W": 0.5, "Wq": 0.25},
        ])
        _agg = aggregate_net(_nodes).iloc[0]
        assert _agg["W_net"] == pytest.approx(0.40)
        assert _agg["Wq_net"] == pytest.approx(0.20)

    def test_zero_lambda_branch(self) -> None:
        """*test_zero_lambda_branch()* every-zero-lambda short-circuits the weighted-mean formula: `total_throughput == 0`, `W_net == 0`, `Wq_net == 0`. No `0 / 0` raised."""
        _nodes = _make_nodes([
            {"lambda": 0.0, "W": 1.0, "Wq": 1.0},
            {"lambda": 0.0, "W": 2.0, "Wq": 2.0},
        ])
        _agg = aggregate_net(_nodes).iloc[0]
        assert _agg["total_throughput"] == pytest.approx(0.0)
        assert _agg["W_net"] == pytest.approx(0.0)
        assert _agg["Wq_net"] == pytest.approx(0.0)


class TestCheckRequirements:
    """**TestCheckRequirements** verifies the R1 / R2 verdicts under the Camara 2023 thresholds (R1 < 0.03 percent failure rate, R2 < 26 ms response time)."""

    def test_all_pass_under_threshold(self) -> None:
        """*test_all_pass_under_threshold()* zero failures + sub-26 ms response on every node -> `R1.pass` and `R2.pass` both True."""
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.005},
            {"lambda": 20.0, "W": 0.010},
        ])
        _req = check_reqs(_nodes)
        assert _req["R1"]["pass"] is True
        assert _req["R2"]["pass"] is True

    def test_r2_fail_under_high_w(self) -> None:
        """*test_r2_fail_under_high_w()* W=50 ms (above the 26 ms threshold) -> `R2.pass is False`."""
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.050}])
        _req = check_reqs(_nodes)
        assert _req["R1"]["pass"] is True
        assert _req["R2"]["pass"] is False

    def test_r1_fail_from_epsilon_column(self) -> None:
        """*test_r1_fail_from_epsilon_column()* per-node `epsilon` mean of 0.05 (5 percent, above the 1 percent Weyns 2015 R1 threshold) -> `R1.pass is False`."""
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.001},
            {"lambda": 10.0, "W": 0.001},
        ])
        _nodes["epsilon"] = [0.05, 0.05]
        _req = check_reqs(_nodes)
        assert _req["R1"]["pass"] is False
        assert _req["R2"]["pass"] is True

    def test_override_kwargs_win(self) -> None:
        """*test_override_kwargs_win()* explicit `failure_rate=0.05` and `response_time=0.100` override the frame-derived defaults; both verdicts fail."""
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _nodes["epsilon"] = [0.0]
        _req = check_reqs(_nodes,
                          failure_rate=0.05,
                          response_time=0.100)
        assert _req["R1"]["value"] == pytest.approx(0.05)
        assert _req["R1"]["pass"] is False
        assert _req["R2"]["value"] == pytest.approx(0.100)
        assert _req["R2"]["pass"] is False

    def test_verdict_schema(self) -> None:
        """*test_verdict_schema()* every verdict's keys are exactly `{metric, value, threshold, operator, units, pass, notes}`; `operator` + `units` come from the reference JSON and flow through unchanged."""
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_reqs(_nodes)
        _expected_keys = {
            "metric", "value", "threshold",
            "operator", "units", "pass", "notes",
        }
        for _k in ("R1", "R2"):
            assert set(_req[_k].keys()) == _expected_keys


class TestThresholdsFromReference:
    """**TestThresholdsFromReference** the R1 / R2 thresholds and metadata in every verdict come from `data/reference/baseline.json` (single source of truth)."""

    def test_r1_threshold_matches_reference_json(self) -> None:
        """*test_r1_threshold_matches_reference_json()* `_req["R1"]["threshold"] == _ref["R1"]["threshold"]` and operator / units / notes match the reference JSON verbatim."""
        _ref = load_reference("baseline")["requirements"]
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_reqs(_nodes)
        assert _req["R1"]["threshold"] == pytest.approx(_ref["R1"]["threshold"])
        assert _req["R1"]["operator"] == _ref["R1"]["operator"]
        assert _req["R1"]["units"] == _ref["R1"]["units"]
        assert _req["R1"]["notes"] == _ref["R1"]["notes"]

    def test_r2_threshold_matches_reference_json(self) -> None:
        """*test_r2_threshold_matches_reference_json()* `_req["R2"]["threshold"] == _ref["R2"]["threshold"]` and operator / units flow through."""
        _ref = load_reference("baseline")["requirements"]
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_reqs(_nodes)
        assert _req["R2"]["threshold"] == pytest.approx(_ref["R2"]["threshold"])
        assert _req["R2"]["operator"] == _ref["R2"]["operator"]
        assert _req["R2"]["units"] == _ref["R2"]["units"]

    def test_reference_has_only_r1_r2(self) -> None:
        """*test_reference_has_only_r1_r2()* the reference JSON exposes exactly `{R1, R2}` (R3 was retired); `check_reqs` returns verdicts for that same set."""
        _ref = load_reference("baseline")["requirements"]
        assert set(_ref.keys()) == {"R1", "R2"}
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_reqs(_nodes)
        assert set(_req.keys()) == {"R1", "R2"}
