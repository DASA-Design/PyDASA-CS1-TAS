# -*- coding: utf-8 -*-
"""
Module test_metrics.py
======================

Sanity checks for the network-wide aggregator and the R1 / R2 / R3
verdict logic in `src.analytic.metrics`.

Each class groups tests by the contract under verification:

    - **TestAggregateNetwork**: the aggregation math on small, hand-computable per-node frames (throughput, weighted means, sums, zero-lambda guard).
    - **TestCheckRequirements**: R1 / R2 / R3 verdicts against the Camara 2023 thresholds, including override kwargs and the per-node `epsilon` fallback path.

# TODO: add a regression case against the full 13-node baseline frame  once a fixture/snapshot is available.
"""
# native python modules
# (none)

# scientific stack
import pandas as pd

# testing framework
import pytest

# module under test
from src.analytic.metrics import (
    aggregate_network,
    check_requirements,
)


# Helper: build a minimal per-node frame with the columns the aggregator
# and the verdict logic actually touch. Centralised so individual tests
# only override what they care about.
def _make_nodes(rows):
    """*_make_nodes()* builds a per-node DataFrame from a list of dicts, filling in sensible defaults for any column a caller omits.

    Args:
        rows (list[dict]): per-node column overrides.

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

    def test_totals_and_max(self):
        """*test_totals_and_max()* sums (L, Lq, lambda) and arithmetic/worst-case (rho, mu) match hand calculations."""
        # two nodes: lambda=10+30=40, rho max=0.8, L sum=3, Lq sum=1.4
        _nodes = _make_nodes([
            {"lambda": 10.0, "mu": 50.0, "rho": 0.2,
             "L": 1.0, "Lq": 0.4},
            {"lambda": 30.0, "mu": 50.0, "rho": 0.8,
             "L": 2.0, "Lq": 1.0},
        ])
        _agg = aggregate_network(_nodes).iloc[0]

        # Structural metrics
        assert _agg["nodes"] == 2
        assert _agg["total_throughput"] == pytest.approx(40.0)

        # Utilization statistics
        assert _agg["avg_rho"] == pytest.approx(0.5)
        assert _agg["max_rho"] == pytest.approx(0.8)
        assert _agg["avg_mu"] == pytest.approx(50.0)

        # Queue length sums
        assert _agg["L_net"] == pytest.approx(3.0)
        assert _agg["Lq_net"] == pytest.approx(1.4)

    def test_weighted_w_net(self):
        """*test_weighted_w_net()* W_net is the throughput-weighted mean of W, not the arithmetic mean.

        With lambdas [10, 30] and W values [0.1, 0.5] the weighted mean is (10*0.1 + 30*0.5) / 40 = 16 / 40 = 0.4.
        """
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.1, "Wq": 0.05},
            {"lambda": 30.0, "W": 0.5, "Wq": 0.25},
        ])
        _agg = aggregate_network(_nodes).iloc[0]

        # throughput-weighted means of W and Wq
        assert _agg["W_net"] == pytest.approx(0.40)
        assert _agg["Wq_net"] == pytest.approx(0.20)

    def test_zero_lambda_branch(self):
        """*test_zero_lambda_branch()* when every per-node lambda is 0 the weighted-mean formula would be 0 / 0; the aggregator must short-circuit to 0 without raising."""
        _nodes = _make_nodes([
            {"lambda": 0.0, "W": 1.0, "Wq": 1.0},
            {"lambda": 0.0, "W": 2.0, "Wq": 2.0},
        ])
        _agg = aggregate_network(_nodes).iloc[0]

        # idle network => no measured waits
        assert _agg["total_throughput"] == pytest.approx(0.0)
        assert _agg["W_net"] == pytest.approx(0.0)
        assert _agg["Wq_net"] == pytest.approx(0.0)


class TestCheckRequirements:
    """**TestCheckRequirements** verifies the R1 / R2 / R3 verdicts under the Camara 2023 thresholds (R1 < 0.03 percent failure rate,
    R2 < 26 ms response time)."""

    def test_all_pass_under_threshold(self):
        """*test_all_pass_under_threshold()* well-behaved network: zero failures, fast responses => R1, R2, R3 all pass."""
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.005},
            {"lambda": 20.0, "W": 0.010},
        ])
        _req = check_requirements(_nodes)

        assert _req["R1"]["pass"] is True
        assert _req["R2"]["pass"] is True
        assert _req["R3"]["pass"] is True

    def test_r2_fail_triggers_r3_fail(self):
        """*test_r2_fail_triggers_r3_fail()* a single node over the 26 ms response-time threshold fails R2, and R3 must follow."""
        # W = 50 ms, well above the 26 ms threshold
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.050}])
        _req = check_requirements(_nodes)

        assert _req["R1"]["pass"] is True
        assert _req["R2"]["pass"] is False
        # R3 is a conjunction of R1 and R2
        assert _req["R3"]["pass"] is False

    def test_r1_fail_from_epsilon_column(self):
        """*test_r1_fail_from_epsilon_column()* when the frame carries per-node `epsilon`, the default failure rate comes from its mean; a mean above 0.03 percent must fail R1."""
        # 1 percent mean failure rate >> 0.03 percent threshold
        _nodes = _make_nodes([
            {"lambda": 10.0, "W": 0.001},
            {"lambda": 10.0, "W": 0.001},
        ])
        _nodes["epsilon"] = [0.01, 0.01]
        _req = check_requirements(_nodes)

        assert _req["R1"]["pass"] is False
        assert _req["R2"]["pass"] is True
        assert _req["R3"]["pass"] is False

    def test_override_kwargs_win(self):
        """*test_override_kwargs_win()* explicit `failure_rate` / `response_time` kwargs override the defaults even when the frame carries an `epsilon` column or nonzero waits."""
        # the frame itself would say R1 pass, R2 pass
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _nodes["epsilon"] = [0.0]

        # but we force a failing failure_rate and a failing response_time
        _req = check_requirements(
            _nodes,
            failure_rate=0.05,      # 5 percent => R1 fails
            response_time=0.100,    # 100 ms   => R2 fails
        )

        assert _req["R1"]["value"] == pytest.approx(0.05)
        assert _req["R1"]["pass"] is False
        assert _req["R2"]["value"] == pytest.approx(0.100)
        assert _req["R2"]["pass"] is False

    def test_cost_recorded_but_not_thresholded(self):
        """*test_cost_recorded_but_not_thresholded()* R3.value carries whatever `cost` the caller passes in; R3.threshold is always None because R3 is a ranking concern, not a hard gate."""
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_requirements(_nodes, cost=42.0)

        assert _req["R3"]["value"] == pytest.approx(42.0)
        assert _req["R3"]["threshold"] is None
        # R3 still passes because R1 and R2 pass on this frame
        assert _req["R3"]["pass"] is True

    def test_verdict_schema(self):
        """*test_verdict_schema()* every verdict dict must expose the full seven-key schema so downstream writers can serialize them uniformly."""
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_requirements(_nodes)

        # every verdict keeps the full schema (metric/value/threshold/
        # operator/units/pass/notes); operator + units come from the
        # reference JSON and flow through unchanged.
        _expected_keys = {
            "metric", "value", "threshold",
            "operator", "units", "pass", "notes",
        }
        for _k in ("R1", "R2", "R3"):
            assert set(_req[_k].keys()) == _expected_keys


class TestThresholdsFromReference:
    """**TestThresholdsFromReference** verifies that the R1 / R2 thresholds consumed by `check_requirements()` match exactly the values declared in `data/reference/baseline.json` (single source of truth), and that the `operator` / `units` metadata flows through into each verdict."""

    def test_r1_threshold_matches_reference_json(self):
        """*test_r1_threshold_matches_reference_json()* the R1 threshold in every verdict must equal the value written in `data/reference/baseline.json`."""
        from src.io import load_reference

        _ref = load_reference("baseline")["requirements"]
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_requirements(_nodes)

        # verdict threshold == JSON threshold (single source of truth)
        assert _req["R1"]["threshold"] == pytest.approx(_ref["R1"]["threshold"])
        # metadata also flows through (no hardcoded strings)
        assert _req["R1"]["operator"] == _ref["R1"]["operator"]
        assert _req["R1"]["units"] == _ref["R1"]["units"]
        assert _req["R1"]["notes"] == _ref["R1"]["notes"]

    def test_r2_threshold_matches_reference_json(self):
        """*test_r2_threshold_matches_reference_json()* same contract for the R2 (response-time) target."""
        from src.io import load_reference

        _ref = load_reference("baseline")["requirements"]
        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_requirements(_nodes)

        assert _req["R2"]["threshold"] == pytest.approx(_ref["R2"]["threshold"])
        assert _req["R2"]["operator"] == _ref["R2"]["operator"]
        assert _req["R2"]["units"] == _ref["R2"]["units"]

    def test_r3_threshold_is_null_in_reference(self):
        """*test_r3_threshold_is_null_in_reference()* R3 is a ranking concern; its threshold must be `null` in the JSON and `None` in the verdict."""
        from src.io import load_reference

        _ref = load_reference("baseline")["requirements"]
        assert _ref["R3"]["threshold"] is None

        _nodes = _make_nodes([{"lambda": 10.0, "W": 0.001}])
        _req = check_requirements(_nodes)
        assert _req["R3"]["threshold"] is None
