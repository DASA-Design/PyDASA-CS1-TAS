# -*- coding: utf-8 -*-
"""
Module test_stochastic.py
=========================

End-to-end sanity checks for the stochastic-method orchestrator in
`src.methods.stochastic`.

Each class groups tests by the contract under verification:

    - **TestStochasticEndToEnd**: each adaptation solves end-to-end via SimPy DES, produces 13 stable nodes and a full R1 / R2 / R3 verdict with the expected schema.
    - **TestAnalyticAgreement**: the stochastic DES solution for the baseline must agree with the closed-form analytic solution on the network-wide averages (avg_rho, W_net) within Monte-Carlo tolerance. This cross-method sanity makes the two methods mutually validating.

*IMPORTANT:* tests use `_QUICK_CFG` (2 reps x 300 invocations) not the production config (10 reps x 10 000 invocations). This cuts the per-adaptation run time below ~1 second with the trade-off of wider CIs; the rho / W agreement tolerances are loosened to match. To re-run any test at full fidelity just swap `method_cfg=_QUICK_CFG` for `method_cfg=None` in the call.
"""
# testing framework
import pytest

# modules under test
from src.methods.analytic import run as run_analytic
from src.methods.stochastic import run as run_stochastic


# Abbreviated method config used by the stochastic tests. Keeps each
# per-adaptation run under ~1 second while still exercising the full
# pipeline (reps > 1 so `_std` columns populate; warmup > 0 so the
# warm-up filter exercises the interval-straddling branch). A few
# hundred invocations are enough for a sanity-check that the engine
# runs end-to-end; production fidelity lives in `stochastic.json`.
_QUICK_CFG = {
    "method": "stochastic",
    "seed": 42,
    "horizon_invocations": 300,
    "warmup_invocations": 30,
    "replications": 2,
    "confidence_level": 0.95,
    "window_invocations": 30,
    "rsem_target": 0.05,
}


# module-scope fixtures so each adaptation is solved ONCE and reused
# across every assertion that needs it (solve is the expensive step).


@pytest.fixture(scope="module")
def _result_baseline():
    """*_result_baseline()* module-scoped fixture: run the stochastic solver for the `baseline` adaptation once and hand the result dict to every test that needs it."""
    return run_stochastic(adp="baseline", wrt=False, method_cfg=_QUICK_CFG)


@pytest.fixture(scope="module")
def _result_s1():
    """*_result_s1()* same as `_result_baseline`, for the `s1` adaptation."""
    return run_stochastic(adp="s1", wrt=False, method_cfg=_QUICK_CFG)


@pytest.fixture(scope="module")
def _analytic_baseline():
    """*_analytic_baseline()* closed-form baseline, fixture-cached so the cross-method comparison tests share one solve."""
    return run_analytic(adp="baseline", wrt=False)


class TestStochasticEndToEnd:
    """**TestStochasticEndToEnd** verifies that the DES pipeline solves end-to-end, produces 13 stable nodes, exposes the full R1 / R2 / R3 verdict, and attaches `_std` columns for every stochastic metric. Runs on `baseline` and `s1` only, covering both profiles (`dflt` / `opti`), to keep the suite quick."""

    @pytest.fixture(params=["baseline", "s1"])
    def _result(self, request, _result_baseline, _result_s1):
        """*_result()* parametrised indirection so each test body stays fixture-free; returns the right per-adaptation result."""
        return _result_baseline if request.param == "baseline" else _result_s1

    def test_runs_and_stable(self, _result):
        """*test_runs_and_stable()* 13 nodes, all stable (rho < 1)."""
        _nds = _result["nodes"]
        assert len(_nds) == 13

        _max_rho = _nds["rho"].max()
        assert _max_rho < 1.0, f"max rho={_max_rho:.4f}"

    def test_requirements_shape(self, _result):
        """*test_requirements_shape()* the verdict dict exposes R1, R2, R3 and each carries the writer-critical fields."""
        _req = _result["requirements"]
        assert set(_req.keys()) == {"R1", "R2", "R3"}
        for _k in ("R1", "R2", "R3"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_r2_passes_under_normal_load(self, _result):
        """*test_r2_passes_under_normal_load()* response time must be under 26 ms at nominal arrival rates."""
        _r2 = _result["requirements"]["R2"]
        assert _r2["pass"], f"W_net={_r2['value']}"

    def test_std_columns_present(self, _result):
        """*test_std_columns_present()* every stochastic metric has its `_std` companion; CI plotters depend on these."""
        _nds = _result["nodes"]
        for _m in ("rho", "L", "Lq", "W", "Wq"):
            assert f"{_m}_std" in _nds.columns


class TestAnalyticAgreement:
    """**TestAnalyticAgreement** cross-method sanity: the DES baseline should agree with the closed-form analytic baseline on the network-wide averages within Monte-Carlo tolerance. Wider bands here because `_QUICK_CFG` only runs 3 reps x 1000 invocations."""

    def test_baseline_avg_rho_close_to_analytic(self,
                                                _result_baseline,
                                                _analytic_baseline):
        """*test_baseline_avg_rho_close_to_analytic()* stochastic avg_rho must be within 25 % of the analytic value at the _QUICK_CFG horizon (300 x 2)."""
        _st_rho = float(_result_baseline["network"].iloc[0]["avg_rho"])
        _an_rho = float(_analytic_baseline["network"].iloc[0]["avg_rho"])
        assert _st_rho == pytest.approx(_an_rho, rel=0.25), (
            f"stochastic avg_rho={_st_rho:.4f} vs "
            f"analytic avg_rho={_an_rho:.4f}"
        )

    def test_baseline_W_net_close_to_analytic(self,
                                              _result_baseline,
                                              _analytic_baseline):
        """*test_baseline_W_net_close_to_analytic()* stochastic W_net must be within 30 % of the analytic value at the _QUICK_CFG horizon (300 x 2)."""
        _st_w = float(_result_baseline["network"].iloc[0]["W_net"])
        _an_w = float(_analytic_baseline["network"].iloc[0]["W_net"])
        assert _st_w == pytest.approx(_an_w, rel=0.30), (
            f"stochastic W_net={_st_w:.6f} vs analytic W_net={_an_w:.6f}"
        )
