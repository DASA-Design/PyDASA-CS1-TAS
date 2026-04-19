# -*- coding: utf-8 -*-
"""
Module test_analytic.py
=======================

End-to-end sanity checks for the analytic-method orchestrator in
`src.methods.analytic`, exercised across all four adaptations
(`baseline`, `s1`, `s2`, `aggregate`).

Each class groups tests by the contract under verification:

    - **TestAnalyticEndToEnd**: every adaptation produces 13 stable nodes and a full R1 / R2 / R3 verdict with the expected schema, and R2 passes at the nominal arrival rate.
    - **TestAggregateBestCase**: the `aggregate` adaptation (opti routing + opti services) must not be worse than `baseline` on the network-wide response time.

# TODO: add a guardrail test that re-asserts the written JSON matches `run(wrt=False)` byte-for-byte after round-tripping through disk (catches accidental ordering or ensure_ascii regressions).
"""
# native python modules
# (none)

# testing framework
import pytest

# module under test
from src.methods.analytic import run


@pytest.mark.parametrize(
    "adp",
    ["baseline", "s1", "s2", "aggregate"],
)
class TestAnalyticEndToEnd:
    """**TestAnalyticEndToEnd** verifies that every adaptation solves end-to-end, produces 13 stable nodes, exposes a full R1 / R2 / R3 verdict, and passes R2 at the nominal 345 req/s arrival rate."""

    def test_runs_and_stable(self, adp):
        """*test_runs_and_stable()* every adaptation returns 13 nodes all of which are stable (rho < 1)."""
        _result = run(adp=adp, wrt=False)
        _nds = _result["nodes"]

        # 13 artifacts regardless of adaptation
        assert len(_nds) == 13

        # every node must be stable under the Jackson-solved rates
        _max_rho = _nds["rho"].max()
        assert _max_rho < 1.0, (
            f"{adp}: max rho={_max_rho:.4f}"
        )

    def test_requirements_shape(self, adp):
        """*test_requirements_shape()* the verdict dict exposes R1, R2, R3 and each carries the full `pass` / `value` / `metric` schema expected by the writer."""
        _result = run(adp=adp, wrt=False)
        _req = _result["requirements"]

        # three verdict keys
        assert set(_req.keys()) == {"R1", "R2", "R3"}

        # every verdict must carry the three writer-critical fields
        for _k in ("R1", "R2", "R3"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_r2_passes_under_normal_load(self, adp):
        """*test_r2_passes_under_normal_load()* response time must be well under 26 ms at nominal arrival rates for every adaptation."""
        _result = run(adp=adp, wrt=False)
        _r2 = _result["requirements"]["R2"]

        assert _r2["pass"], (
            f"{adp}: W_net={_r2['value']}"
        )


class TestAggregateBestCase:
    """**TestAggregateBestCase** verifies that the `aggregate` adaptation (opti routing + opti services) does not regress the network-wide response time relative to `baseline`. A small tolerance is allowed so tiny numerical drift does not trip the test; the point is they are at least comparable."""

    def test_aggregate_lte_baseline_w_net(self):
        """*test_aggregate_lte_baseline_w_net()* aggregate W_net must
        be at most baseline W_net within a 1 percent tolerance."""
        # solve both adaptations end-to-end
        _baseline = run(adp="baseline", wrt=False)
        _aggregate = run(adp="aggregate", wrt=False)

        # pull the single-row network aggregate out of each
        _w_baseline = _baseline["network"].iloc[0]["W_net"]
        _w_aggregate = _aggregate["network"].iloc[0]["W_net"]

        # tolerance absorbs tiny numerical drift without hiding regressions
        _msg = f"aggregate W_net={_w_aggregate} > baseline W_net={_w_baseline}"
        assert _w_aggregate <= _w_baseline * 1.01, (_msg)
