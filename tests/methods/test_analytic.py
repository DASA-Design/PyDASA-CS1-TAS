# -*- coding: utf-8 -*-
"""
Module test_analytic.py
=======================

End-to-end sanity checks for the analytic-method orchestrator in `src.methods.analytic`, exercised across all four adaptations (`baseline`, `s1`, `s2`, `aggregate`).

    - **TestAnalyticEndToEnd** every adaptation produces 13 stable nodes and a full R1 / R2 verdict with the expected schema, and R2 passes at the nominal arrival rate.
    - **TestAggregateBestCase** the `aggregate` adaptation (opti routing + opti services) is no worse than `baseline` on the network-wide response time.
"""
# testing framework
import pytest

# module under test
from src.methods.analytic import run


@pytest.mark.parametrize(
    "adp",
    ["baseline", "s1", "s2", "aggregate"],
)
class TestAnalyticEndToEnd:
    """**TestAnalyticEndToEnd** every adaptation solves end-to-end, produces 13 stable nodes, exposes a full R1 / R2 verdict, and passes R2 at the nominal 345 req/s arrival rate."""

    def test_runs_and_stable(self, adp: str) -> None:
        """*test_runs_and_stable()* `len(nodes) == 13` and `nodes["rho"].max() < 1.0` for every adaptation."""
        _result = run(adp=adp, wrt=False)
        _nds = _result["nodes"]
        assert len(_nds) == 13
        _max_rho = _nds["rho"].max()
        assert _max_rho < 1.0, f"{adp}: max rho={_max_rho:.4f}"

    def test_requirements_shape(self, adp: str) -> None:
        """*test_requirements_shape()* `set(req.keys()) == {"R1", "R2"}` and every verdict carries `pass`, `value`, `metric`."""
        _result = run(adp=adp, wrt=False)
        _req = _result["requirements"]
        assert set(_req.keys()) == {"R1", "R2"}
        for _k in ("R1", "R2"):
            assert "pass" in _req[_k]
            assert "value" in _req[_k]
            assert "metric" in _req[_k]

    def test_r2_passes_under_normal_load(self, adp: str) -> None:
        """*test_r2_passes_under_normal_load()* `req["R2"]["pass"] is True` for every adaptation at nominal arrival rates."""
        _result = run(adp=adp, wrt=False)
        _r2 = _result["requirements"]["R2"]
        assert _r2["pass"], f"{adp}: W_net={_r2['value']}"


class TestAggregateBestCase:
    """**TestAggregateBestCase** the `aggregate` adaptation does not regress network-wide response time relative to `baseline`."""

    def test_aggregate_lte_baseline_w_net(self) -> None:
        """*test_aggregate_lte_baseline_w_net()* `aggregate.W_net <= baseline.W_net * 1.01` (1 percent tolerance absorbs numerical drift without hiding regressions)."""
        _baseline = run(adp="baseline", wrt=False)
        _aggregate = run(adp="aggregate", wrt=False)
        _w_baseline = _baseline["network"].iloc[0]["W_net"]
        _w_aggregate = _aggregate["network"].iloc[0]["W_net"]
        _msg = f"aggregate W_net={_w_aggregate} > baseline W_net={_w_baseline}"
        assert _w_aggregate <= _w_baseline * 1.01, _msg
