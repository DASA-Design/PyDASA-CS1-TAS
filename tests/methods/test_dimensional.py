# -*- coding: utf-8 -*-
"""
Module test_dimensional.py
==========================

End-to-end sanity checks for the dimensional-method orchestrator in
`src.methods.dimensional`.

Each class groups tests by the contract under verification:

    - **TestDimensionalEndToEnd**: each adaptation solves end-to-end via PyDASA, produces 13 (or 16) artifact blocks with the expected pi-group / coefficient / sensitivity shape.
    - **TestResultEnvelope**: the JSON envelope written to `data/results/dimensional/<scenario>/<profile>.json` is well-formed and round-trips on disk.
    - **TestMethodCfgOverride**: the `method_cfg=` kwarg lets callers inject a trimmed spec so tests do not depend on disk state.

*IMPORTANT:* every adaptation is solved ONCE in a module-scope fixture;
per-test assertions reuse the cached dict. One full solve of the 13-artifact
network takes about 1.5 s on current hardware, so the full file runs in ~5 s.
"""
# native python modules
import json

# testing framework
import pytest

# modules under test
from src.methods.dimensional import run as run_dimensional


# module-scope fixtures so each adaptation is solved ONCE and reused
# across every assertion that needs it


@pytest.fixture(scope="module")
def _result_baseline():
    """*_result_baseline()* module-scoped fixture: run the dimensional solver for the `baseline` adaptation once and hand the result dict to every test that needs it."""
    return run_dimensional(adp="baseline", wrt=False)


@pytest.fixture(scope="module")
def _result_s1():
    """*_result_s1()* same as `_result_baseline`, for the `s1` adaptation."""
    return run_dimensional(adp="s1", wrt=False)


@pytest.fixture(scope="module")
def _result_aggregate():
    """*_result_aggregate()* same as `_result_baseline`, for the `aggregate` adaptation; exercises the 16-artifact opti profile."""
    return run_dimensional(adp="aggregate", wrt=False)


class TestDimensionalEndToEnd:
    """**TestDimensionalEndToEnd** verifies that the PyDASA pipeline runs end-to-end, produces one artifact block per queue node, and attaches the four derived coefficients plus sensitivity for every one. Runs on `baseline`, `s1`, and `aggregate` -- covering both profiles (`dflt` / `opti`) and both artifact counts (13 / 16)."""

    @pytest.fixture(params=["baseline", "s1", "aggregate"])
    def _result(self, request, _result_baseline, _result_s1, _result_aggregate):
        """*_result()* parametrised indirection so each test body stays fixture-free; returns the right per-adaptation result."""
        _map = {
            "baseline": _result_baseline,
            "s1": _result_s1,
            "aggregate": _result_aggregate,
        }
        return _map[request.param]

    def test_artifact_count_matches_scenario(self, _result):
        """*test_artifact_count_matches_scenario()* 13 nodes on baseline/s1, 16 on aggregate (opti expands the swap slots)."""
        _arts = _result["artifacts"]
        _cfg = _result["config"]
        assert len(_arts) == len(_cfg.artifacts)

    def test_artifact_keys_match_config(self, _result):
        """*test_artifact_keys_match_config()* per-artifact block keys line up with the resolved NetworkConfig order."""
        _expected = [_a.key for _a in _result["config"].artifacts]
        assert list(_result["artifacts"].keys()) == _expected

    def test_each_artifact_has_seven_pi_groups(self, _result):
        """*test_each_artifact_has_seven_pi_groups()* Buckingham: 10 relevant variables - 3 FDUs = 7 Pi-groups."""
        for _k, _a in _result["artifacts"].items():
            assert len(_a["pi_groups"]) == 7, f"{_k}: {len(_a['pi_groups'])} Pi-groups"

    def test_each_artifact_has_four_coefficients(self, _result):
        """*test_each_artifact_has_four_coefficients()* theta, sigma, eta, phi per artifact."""
        for _k, _a in _result["artifacts"].items():
            assert len(_a["coefficients"]) == 4, f"{_k}: {len(_a['coefficients'])} coefficients"

    def test_coefficient_setpoints_are_floats(self, _result):
        """*test_coefficient_setpoints_are_floats()* every derived coefficient carries a numeric setpoint (post `calculate_setpoint()`)."""
        for _k, _a in _result["artifacts"].items():
            for _sym, _co in _a["coefficients"].items():
                assert isinstance(_co["setpoint"], (int, float)), (
                    f"{_k}/{_sym}: setpoint is {type(_co['setpoint']).__name__}"
                )

    def test_sensitivity_block_present(self, _result):
        """*test_sensitivity_block_present()* every artifact has a non-empty sensitivity dict with SEN_-prefixed keys."""
        for _k, _a in _result["artifacts"].items():
            _sens = _a["sensitivity"]
            assert len(_sens) > 0
            assert all(_s.startswith("SEN_") for _s in _sens.keys())

    def test_theta_matches_L_over_K_baseline(self, _result_baseline):
        """*test_theta_matches_L_over_K_baseline()* per-artifact theta equals L_mean / K_mean (6/10 = 0.6 across the uniform baseline initialisation). Runs on baseline only -- s1 / aggregate swap slots have different L / K means, so the uniform 0.6 check does not apply there."""
        for _k, _a in _result_baseline["artifacts"].items():
            _theta = _a["coefficients"][f"\\theta_{{{_k}}}"]["setpoint"]
            assert _theta == pytest.approx(0.6, abs=1e-6), f"{_k}: theta={_theta}"


class TestResultEnvelope:
    """**TestResultEnvelope** verifies the JSON envelope written to disk is well-formed and round-trips cleanly. Uses a temporary directory per the pytest convention so the real `data/results/dimensional/` tree is untouched."""

    def test_wrt_true_writes_file(self, tmp_path, monkeypatch):
        """*test_wrt_true_writes_file()* writing to a tmp_path results dir produces a well-formed JSON file."""
        # redirect both the results dir AND the _ROOT so relative_to() can
        # express the written file as a repo-relative path
        from src.methods import dimensional as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path)

        _result = run_dimensional(adp="baseline", wrt=True)

        # orchestrator reports the written path
        assert "profile" in _result["paths"]

        _path = tmp_path / "baseline" / "dflt.json"
        assert _path.exists(), f"expected {_path} to exist"

        _doc = json.loads(_path.read_text(encoding="utf-8"))
        assert _doc["method"] == "dimensional"
        assert _doc["profile"] == "dflt"
        assert _doc["scenario"] == "baseline"
        assert len(_doc["artifacts"]) == 13

    def test_envelope_carries_method_config(self, tmp_path, monkeypatch):
        """*test_envelope_carries_method_config()* the written blob embeds the full method config so the run is self-describing on disk."""
        from src.methods import dimensional as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path)

        run_dimensional(adp="baseline", wrt=True)

        _doc = json.loads((tmp_path / "baseline" / "dflt.json").read_text())
        assert "method_config" in _doc
        assert "fdus" in _doc["method_config"]
        assert "coefficients" in _doc["method_config"]


class TestMethodCfgOverride:
    """**TestMethodCfgOverride** verifies the `method_cfg=` kwarg lets tests inject a trimmed spec without touching disk."""

    def test_single_coefficient_override(self):
        """*test_single_coefficient_override()* injecting a one-entry coefficient spec yields exactly one derived coefficient per artifact."""
        _trim = {
            "seed": 42,
            "fdus": [
                {"_idx": 0, "_sym": "T", "_fwk": "CUSTOM", "_name": "Time",
                 "_unit": "s", "description": "t"},
                {"_idx": 1, "_sym": "S", "_fwk": "CUSTOM", "_name": "Structure",
                 "_unit": "req", "description": "s"},
                {"_idx": 2, "_sym": "D", "_fwk": "CUSTOM", "_name": "Data",
                 "_unit": "kB", "description": "d"},
            ],
            "coefficients": [
                {"symbol": "theta", "expr_pattern": "{pi[6]} * {pi[3]}**(-1)",
                 "name": "Occupancy", "description": "theta = L/K"},
            ],
            "sensitivity": {"val_type": "mean", "cat": "SYM"},
        }
        _result = run_dimensional(adp="baseline", wrt=False, method_cfg=_trim)
        for _k, _a in _result["artifacts"].items():
            assert len(_a["coefficients"]) == 1
            assert f"\\theta_{{{_k}}}" in _a["coefficients"]
