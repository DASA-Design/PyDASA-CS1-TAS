# -*- coding: utf-8 -*-
"""
Module test_reshape.py
======================

Shape + semantic checks for the orchestrator-output reshapers:

    - **TestNodeShape**: `coefs_to_nodes` produces one row per artifact with the expected column set.
    - **TestNetworkShape**: `coefs_to_net` produces a single-row frame with the aggregate coefficients.
    - **TestDeltaSemantics**: `coefs_delta` gives zero delta on identical inputs and handles mismatched node sets (e.g. 13-node baseline vs 16-node aggregate).
"""
# testing framework
import pytest

# modules under test
from src.dimensional import (aggregate_arch_coefs,
                             coefs_delta,
                             coefs_to_net,
                             coefs_to_nodes,
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
        _nds = coefs_to_nodes(_dim_baseline)
        assert len(_nds) == 13

    def test_thirteen_rows_on_aggregate(self, _dim_aggregate):
        """aggregate has the same artifact count as baseline; the 3 swap slots replace 3 originals."""
        _nds = coefs_to_nodes(_dim_aggregate)
        assert len(_nds) == 13

    def test_expected_columns_present(self, _dim_baseline):
        _nds = coefs_to_nodes(_dim_baseline)
        assert {"key", "name", "type", "theta", "sigma", "eta", "phi"} <= set(_nds.columns)

    def test_theta_varies_per_artifact_on_baseline(self, _dim_baseline):
        """After seeding from analytic, theta reflects real per-artifact L/K ratios (Jackson-solved L varies); baseline should no longer be uniform."""
        _nds = coefs_to_nodes(_dim_baseline)
        _range = _nds["theta"].max() - _nds["theta"].min()
        assert _range > 0.05, f"theta range {_range} too small; seed may have failed"


class TestNetworkShape:
    """Network aggregate frame has one row and one column per coefficient."""

    def test_single_row(self, _dim_baseline):
        _net = coefs_to_net(_dim_baseline)
        assert len(_net) == 1

    def test_nodes_count_matches(self, _dim_baseline):
        _net = coefs_to_net(_dim_baseline)
        assert _net["nodes"].iloc[0] == 13

    def test_rejects_unknown_aggregator(self, _dim_baseline):
        with pytest.raises(ValueError, match="unknown aggregator"):
            coefs_to_net(_dim_baseline, agg="bogus")

    def test_median_differs_from_mean(self, _dim_baseline):
        """η has a skewed distribution on baseline; median < mean."""
        _mean = coefs_to_net(_dim_baseline, agg="mean")
        _med = coefs_to_net(_dim_baseline, agg="median")
        assert _med["eta"].iloc[0] != pytest.approx(_mean["eta"].iloc[0])


class TestDeltaSemantics:
    """Delta computations handle equal / mismatched node sets correctly."""

    def test_zero_delta_on_identical_inputs(self, _dim_baseline):
        _nds = coefs_to_nodes(_dim_baseline)
        _d = coefs_delta(_nds, _nds)
        for _m in ("theta", "sigma", "eta", "phi"):
            assert all(abs(_d[_m]) < 1e-12)

    def test_aggregate_delta_uses_intersection(self, _dim_baseline, _dim_aggregate):
        """baseline and aggregate each have 13 artifacts; 3 are swapped (MAS_{3}/AS_{3}/DS_{3} -> MAS_{4}/AS_{4}/DS_{1}). The delta frame keeps only the 10 non-swap nodes."""
        _b = coefs_to_nodes(_dim_baseline)
        _a = coefs_to_nodes(_dim_aggregate)
        _d = coefs_delta(_b, _a)
        assert len(_d) == 10

    def test_network_delta_single_row(self, _dim_baseline, _dim_aggregate):
        _nb = coefs_to_net(_dim_baseline)
        _na = coefs_to_net(_dim_aggregate)
        _d = network_delta(_nb, _na)
        assert len(_d) == 1
        assert {"theta", "sigma", "eta", "phi"} <= set(_d.columns)


class TestArchitectureAggregation:
    """PACS-iter2-style variable-level aggregation (sum first, divide after)."""

    def test_single_row_output(self, _dim_baseline):
        _arch = aggregate_arch_coefs(_dim_baseline)
        assert len(_arch) == 1

    def test_default_tag_is_TAS(self, _dim_baseline):
        _arch = aggregate_arch_coefs(_dim_baseline)
        for _coef in ("theta", "sigma", "eta", "phi", "epsilon"):
            assert f"\\{_coef}_{{TAS}}" in _arch.columns

    def test_custom_tag_flows_through(self, _dim_baseline):
        _arch = aggregate_arch_coefs(_dim_baseline, tag="TAS_base")
        assert "\\theta_{TAS_base}" in _arch.columns

    def test_theta_equals_sumL_over_sumK(self, _dim_baseline):
        """theta_arch = (sum L_i) / (sum K_i) across every artifact."""
        _cfg = _dim_baseline["config"]
        _sum_L = sum(float(_a.vars[f"L_{{{_a.key}}}"]["_setpoint"])
                     for _a in _cfg.artifacts)
        _sum_K = sum(float(_a.vars[f"K_{{{_a.key}}}"]["_setpoint"])
                     for _a in _cfg.artifacts)
        _arch = aggregate_arch_coefs(_dim_baseline)
        _theta = float(_arch["\\theta_{TAS}"].iloc[0])
        assert _theta == pytest.approx(_sum_L / _sum_K, rel=1e-9)

    def test_epsilon_uses_cumulative_probability(self, _dim_baseline):
        """epsilon_arch = 1 - prod(1 - epsilon_i). Value derives from the actual per-artifact epsilons."""
        _cfg = _dim_baseline["config"]
        _prod = 1.0
        for _a in _cfg.artifacts:
            _eps_i = float(_a.vars[f"\\epsilon_{{{_a.key}}}"]["_setpoint"])
            _prod *= (1.0 - _eps_i)
        _expected = 1.0 - _prod

        _arch = aggregate_arch_coefs(_dim_baseline)
        _eps = float(_arch["\\epsilon_{TAS}"].iloc[0])
        assert _eps == pytest.approx(_expected, rel=1e-9)

    def test_eta_matches_sum_chi_K_over_sum_mu_c(self, _dim_baseline):
        """eta_arch = (sum chi_i * K_i) / (sum mu_i * c_i); recomputed by hand from the config setpoints."""
        _cfg = _dim_baseline["config"]
        _num = 0.0
        _den = 0.0
        for _a in _cfg.artifacts:
            _chi = float(_a.vars[f"\\chi_{{{_a.key}}}"]["_setpoint"])
            _K = float(_a.vars[f"K_{{{_a.key}}}"]["_setpoint"])
            _mu = float(_a.vars[f"\\mu_{{{_a.key}}}"]["_setpoint"])
            _c = float(_a.vars[f"c_{{{_a.key}}}"]["_setpoint"])
            _num += _chi * _K
            _den += _mu * _c
        _expected = _num / _den

        _arch = aggregate_arch_coefs(_dim_baseline)
        _eta = float(_arch["\\eta_{TAS}"].iloc[0])
        assert _eta == pytest.approx(_expected, rel=1e-9)

    def test_architecture_coefficients_in_range(self, _dim_baseline):
        """Every architecture-level coefficient must sit in a sensible range for a stable baseline."""
        _arch = aggregate_arch_coefs(_dim_baseline)
        _theta = float(_arch["\\theta_{TAS}"].iloc[0])
        _phi = float(_arch["\\phi_{TAS}"].iloc[0])
        _eps = float(_arch["\\epsilon_{TAS}"].iloc[0])
        # occupancy + memory use are ratios in [0, 1]; compound epsilon also in [0, 1]
        assert 0.0 <= _theta <= 1.0
        assert 0.0 <= _phi <= 1.0
        assert 0.0 <= _eps <= 1.0
