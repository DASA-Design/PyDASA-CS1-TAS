# -*- coding: utf-8 -*-
"""
Module test_mem_budget.py
=========================

FR-2.4: pin the explicit FastAPI memory-budget declaration that the
launcher threads from `experiment.json::request_size_bytes` into every
`ServiceSpec.mem_per_buffer`, and surfaces in the per-run
`config.json` snapshot.

Runtime enforcement is deferred per `notes/prototype.md` FR-2.4; this
module covers the declaration-and-audit path only.

    - **TestAvgRequestSize** `_compute_avg_req_size` takes the arithmetic mean over declared per-kind sizes, ignoring zeros.
    - **TestServiceSpecBudget** `ServiceSpec.mem_per_buffer` and `buffer_budget_bytes` round-trip the declared value; default is 0.
    - **TestLauncherPopulatesBudget** the launcher derives `mem_per_buffer = K * avg_request_size * MEM_HEADROOM_FACTOR` into every spec and surfaces it in `config.json::artifacts`.
"""
# native python modules
import json
import tempfile
from pathlib import Path

# testing framework
import pytest

# modules under test
from src.experiment.launcher import ExperimentLauncher, _compute_avg_req_size
from src.experiment.services import ServiceRequest, ServiceResponse, ServiceSpec
from src.io import load_method_config, load_profile


# ---------------------------------------------------------------- helpers


async def _noop_forward(_target: str, _req: ServiceRequest) -> ServiceResponse:
    """*_noop_forward()* fail loudly if invoked; unit-tested services must have empty routing rows."""
    raise AssertionError(
        "unit-tested services have empty routing rows; forward must not fire")


# --------------------------------------------------------------- classes


class TestAvgRequestSize:
    """**TestAvgRequestSize** arithmetic mean across declared per-kind sizes."""

    def test_mean_of_three_sizes(self):
        """*test_mean_of_three_sizes()* `{100, 200, 300}` averages to 200."""
        assert _compute_avg_req_size({"a": 100, "b": 200, "c": 300}) == 200

    def test_empty_map_is_zero(self):
        """*test_empty_map_is_zero()* an empty dict averages to 0 (guard against ZeroDivision)."""
        assert _compute_avg_req_size({}) == 0

    def test_ignores_zeros(self):
        """*test_ignores_zeros()* zero-valued entries are dropped before averaging."""
        assert _compute_avg_req_size({"a": 0, "b": 200, "c": 300}) == 250


class TestServiceSpecBudget:
    """**TestServiceSpecBudget** spec exposes `mem_per_buffer` + `buffer_budget_bytes`."""

    def test_explicit_budget_value(self):
        """*test_explicit_budget_value()* declared bytes round-trip through the property."""
        _s = ServiceSpec(name="MAS_{1}", role="atomic", port=9000,
                         mu=100.0, epsilon=0.0, c=1, K=10,
                         mem_per_buffer=4096)
        assert _s.mem_per_buffer == 4096
        assert _s.buffer_budget_bytes == 4096

    def test_default_budget_zero_when_undeclared(self):
        """*test_default_budget_zero_when_undeclared()* default `mem_per_buffer == 0` and the property mirrors it."""
        _s = ServiceSpec(name="MAS_{1}", role="atomic", port=9000,
                         mu=100.0, epsilon=0.0, c=1, K=10)
        assert _s.mem_per_buffer == 0
        assert _s.buffer_budget_bytes == 0


class TestLauncherPopulatesBudget:
    """**TestLauncherPopulatesBudget** launcher threads avg-request-size from method config into every spec."""

    @pytest.mark.asyncio
    async def test_every_spec_has_expected_budget(self):
        """*test_every_spec_has_expected_budget()* every resolved spec has `mem_per_buffer = K * avg * headroom`."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        _sizes = _mcfg.get("request_size_bytes", {})
        _avg = _compute_avg_req_size(_sizes)
        assert _avg > 0, "fixture method config must declare at least one positive size"

        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            _headroom = ServiceSpec.MEM_HEADROOM_FACTOR
            for _name, _spec in _lnc.specs.items():
                _expected = int(_spec.K * _avg * _headroom)
                assert _spec.mem_per_buffer == _expected, (
                    f"{_name}: mem_per_buffer={_spec.mem_per_buffer} "
                    f"expected={_expected}")

    @pytest.mark.asyncio
    async def test_budget_surfaces_in_config_snapshot(self):
        """*test_budget_surfaces_in_config_snapshot()* `config.json::artifacts.<name>.mem_per_buffer` matches the resolved spec."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            with tempfile.TemporaryDirectory() as _td:
                _path = _lnc.snapshot_config(Path(_td))
                _doc = json.loads(_path.read_text(encoding="utf-8"))
                for _name, _art in _doc["artifacts"].items():
                    assert "mem_per_buffer" in _art
                    assert _art["mem_per_buffer"] == _lnc.specs[_name].mem_per_buffer
