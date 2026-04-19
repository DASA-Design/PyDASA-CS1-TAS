# -*- coding: utf-8 -*-
"""
Module test_reshape.py
======================

Shape + semantic checks for the orchestrator-output reshapers:

    - **TestNodeShape**: `coefficients_to_nodes` produces one row per artifact with the expected column set.
    - **TestNetworkShape**: `coefficients_to_network` produces a single-row frame with the aggregate coefficients.
    - **TestDeltaSemantics**: `coefficients_delta` gives zero delta on identical inputs and handles mismatched node sets (e.g. 13-node baseline vs 16-node aggregate).
"""
# testing framework
import pytest

# modules under test
from src.dimensional import (coefficients_delta,
                             coefficients_to_network,
                             coefficients_to_nodes,
                             network_delta)


@pytest.fixture(scope="module")
def _dim_baseline():
    """*_dim_baseline()* cached dimensional run for baseline."""
    from src.methods.dimensional import run
    return run(adp="baseline", wrt=False)


@pytest.fixture(scope="module")
def _dim_aggregate():
    """*_dim_aggregate()* cached dimensional run for aggregate (16 nodes)."""
    from src.methods.dimensional import run
    return run(adp="aggregate", wrt=False)


class TestNodeShape:
    """Per-node frame has one row per artifact with the expected columns."""

    def test_thirteen_rows_on_baseline(self, _dim_baseline):
        _nds = coefficients_to_nodes(_dim_baseline)
        assert len(_nds) == 13

    def test_thirteen_rows_on_aggregate(self, _dim_aggregate):
        """aggregate has the same artifact count as baseline; the 3 swap slots replace 3 originals."""
        _nds = coefficients_to_nodes(_dim_aggregate)
        assert len(_nds) == 13

    def test_expected_columns_present(self, _dim_baseline):
        _nds = coefficients_to_nodes(_dim_baseline)
        assert {"key", "name", "type", "theta", "sigma", "eta", "phi"} <= set(_nds.columns)

    def test_theta_varies_per_artifact_on_baseline(self, _dim_baseline):
        """After seeding from analytic, theta reflects real per-artifact L/K ratios (Jackson-solved L varies); baseline should no longer be uniform."""
        _nds = coefficients_to_nodes(_dim_baseline)
        _range = _nds["theta"].max() - _nds["theta"].min()
        assert _range > 0.05, f"theta range {_range} too small; seed may have failed"


class TestNetworkShape:
    """Network aggregate frame has one row and one column per coefficient."""

    def test_single_row(self, _dim_baseline):
        _net = coefficients_to_network(_dim_baseline)
        assert len(_net) == 1

    def test_nodes_count_matches(self, _dim_baseline):
        _net = coefficients_to_network(_dim_baseline)
        assert _net["nodes"].iloc[0] == 13

    def test_rejects_unknown_aggregator(self, _dim_baseline):
        with pytest.raises(ValueError, match="unknown aggregator"):
            coefficients_to_network(_dim_baseline, agg="bogus")

    def test_median_differs_from_mean(self, _dim_baseline):
        """η has a skewed distribution on baseline; median < mean."""
        _mean = coefficients_to_network(_dim_baseline, agg="mean")
        _med = coefficients_to_network(_dim_baseline, agg="median")
        assert _med["eta"].iloc[0] != pytest.approx(_mean["eta"].iloc[0])


class TestDeltaSemantics:
    """Delta computations handle equal / mismatched node sets correctly."""

    def test_zero_delta_on_identical_inputs(self, _dim_baseline):
        _nds = coefficients_to_nodes(_dim_baseline)
        _d = coefficients_delta(_nds, _nds)
        for _m in ("theta", "sigma", "eta", "phi"):
            assert all(abs(_d[_m]) < 1e-12)

    def test_aggregate_delta_uses_intersection(self, _dim_baseline, _dim_aggregate):
        """baseline and aggregate each have 13 artifacts; 3 are swapped (MAS_{3}/AS_{3}/DS_{3} -> MAS_{4}/AS_{4}/DS_{1}). The delta frame keeps only the 10 non-swap nodes."""
        _b = coefficients_to_nodes(_dim_baseline)
        _a = coefficients_to_nodes(_dim_aggregate)
        _d = coefficients_delta(_b, _a)
        assert len(_d) == 10

    def test_network_delta_single_row(self, _dim_baseline, _dim_aggregate):
        _nb = coefficients_to_network(_dim_baseline)
        _na = coefficients_to_network(_dim_aggregate)
        _d = network_delta(_nb, _na)
        assert len(_d) == 1
        assert {"theta", "sigma", "eta", "phi"} <= set(_d.columns)
