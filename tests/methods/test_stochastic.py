# -*- coding: utf-8 -*-
"""
Module test_stochastic.py
=========================

End-to-end sanity checks for the stochastic-method orchestrator in `src.methods.stochastic`, exercised across all four adaptations (`baseline`, `s1`, `s2`, `aggregate`).

Each class groups tests by the contract under verification:

    - **TestStochasticEndToEnd**: every adaptation produces 13 stable nodes and a full R1 / R2 / R3 verdict with the expected schema, and R2 passes at the nominal arrival rate.
    - **TestAnalyticAgreement**: the stochastic DES solution for the baseline must agree with the closed-form analytic solution on the network-wide averages (avg_rho, W_net) within Monte-Carlo tolerance. This is the cross-method sanity that makes the two methods mutually validating.

# TODO: add a stddev-magnitude regression once Welch's method lands (std columns should shrink as horizon_invocations grows).
"""
# native python modules
# (none)

# testing framework
import pytest

# modules under test
from src.methods.analytic import run as run_analytic
from src.methods.stochastic import run as run_stochastic


@pytest.mark.parametrize(
    "adp",
    ["baseline", "s1", "s2", "aggregate"],
)
class TestStochasticEndToEnd:
    """**TestStochasticEndToEnd** verifies that every adaptation solves end-to-end via SimPy DES, produces 13 stable nodes, exposes a full R1 / R2 / R3 verdict, and passes R2 at the nominal 345 req/s arrival rate."""

    def test_runs_and_stable(self, adp):
        """*test_runs_and_stable()* every adaptation returns 13 nodes all of which are stable (rho < 1)."""
        _result = run_stochastic(adp=adp, wrt=False)
        _nds = _result["nodes"]

        # 13 artifacts regardless of adaptation
        assert len(_nds) == 13

        # every node must be stable under the DES-solved rates
        _max_rho = _nds["rho"].max()
        assert _max_rho < 1.0, (
            f"{adp}: max rho={_max_rho:.4f}"
        )

    def test_requirements_shape(self, adp):
        """*test_requirements_shape()* the verdict dict exposes R1, R2, R3 and each carries the writer-critical fields."""
        _result = run_stochastic(adp=adp, wrt=False)
        _req = _result["requirements"]

        assert set(_req.keys()) == {"R1", "R2", "R3"}
        for _k in ("R1", "R2", "R3"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_r2_passes_under_normal_load(self, adp):
        """*test_r2_passes_under_normal_load()* response time must be under 26 ms at nominal arrival rates for every adaptation."""
        _result = run_stochastic(adp=adp, wrt=False)
        _r2 = _result["requirements"]["R2"]
        assert _r2["pass"], (
            f"{adp}: W_net={_r2['value']}"
        )

    def test_std_columns_present(self, adp):
        """*test_std_columns_present()* every stochastic metric has its `_std` companion (uses `reps > 1` from the method config); the CI plotters depend on these."""
        _result = run_stochastic(adp=adp, wrt=False)
        _nds = _result["nodes"]
        for _m in ("rho", "L", "Lq", "W", "Wq"):
            assert f"{_m}_std" in _nds.columns


class TestAnalyticAgreement:
    """**TestAnalyticAgreement** compares the stochastic DES baseline to the closed-form analytic baseline on the network-wide aggregates. The two methods should agree within Monte-Carlo tolerance -- that is the whole point of running both."""

    def test_baseline_avg_rho_close_to_analytic(self):
        """*test_baseline_avg_rho_close_to_analytic()* stochastic avg_rho must be within 5 % of the analytic value."""
        _st = run_stochastic(adp="baseline", wrt=False)
        _an = run_analytic(adp="baseline", wrt=False)

        _st_rho = float(_st["network"].iloc[0]["avg_rho"])
        _an_rho = float(_an["network"].iloc[0]["avg_rho"])
        assert _st_rho == pytest.approx(_an_rho, rel=0.05), (
            f"stochastic avg_rho={_st_rho:.4f} vs "
            f"analytic avg_rho={_an_rho:.4f}"
        )

    def test_baseline_W_net_close_to_analytic(self):
        """*test_baseline_W_net_close_to_analytic()* stochastic W_net must be within 10 % of the analytic value."""
        _st = run_stochastic(adp="baseline", wrt=False)
        _an = run_analytic(adp="baseline", wrt=False)

        _st_w = float(_st["network"].iloc[0]["W_net"])
        _an_w = float(_an["network"].iloc[0]["W_net"])
        assert _st_w == pytest.approx(_an_w, rel=0.10), (
            f"stochastic W_net={_st_w:.6f} vs analytic W_net={_an_w:.6f}"
        )
