# -*- coding: utf-8 -*-
"""
Module test_dimensional.py
==========================

End-to-end sanity checks for the dimensional-method orchestrator in `src.methods.dimensional`.

Each adaptation is solved ONCE in a module-scope fixture and the cached dict is reused across every assertion. One full 13-artifact solve runs in ~1.5 s, so the file finishes in ~5 s.

    - **TestDimensionalEndToEnd**: each adaptation solves end-to-end via PyDASA and produces 13 (or 16) artifact blocks with the expected pi-group / coefficient / sensitivity shape.
    - **TestResultEnvelope**: the JSON envelope written to `data/results/dimensional/<scenario>/<profile>.json` is well-formed and round-trips on disk.
    - **TestMethodCfgOverride**: the `method_cfg=` kwarg lets callers inject a trimmed spec so tests do not depend on disk state.
"""
# native python modules
import json
from typing import Any, Dict

# testing framework
import pytest

# modules under test
from src.methods.dimensional import run as run_dimensional


@pytest.fixture(scope="module")
def _result_baseline() -> Dict[str, Any]:
    """*_result_baseline()* `run_dimensional(adp="baseline", wrt=False)` once per module."""
    return run_dimensional(adp="baseline", wrt=False)


@pytest.fixture(scope="module")
def _result_s1() -> Dict[str, Any]:
    """*_result_s1()* `run_dimensional(adp="s1", wrt=False)` once per module."""
    return run_dimensional(adp="s1", wrt=False)


@pytest.fixture(scope="module")
def _result_aggregate() -> Dict[str, Any]:
    """*_result_aggregate()* `run_dimensional(adp="aggregate", wrt=False)`; exercises the 16-artifact opti profile."""
    return run_dimensional(adp="aggregate", wrt=False)


class TestDimensionalEndToEnd:
    """**TestDimensionalEndToEnd** the PyDASA pipeline runs end-to-end across `baseline` / `s1` / `aggregate`, producing one artifact block per queue node with the four derived coefficients plus sensitivity. Covers both profiles (`dflt` / `opti`) and both artifact counts (13 / 16)."""

    @pytest.fixture(params=["baseline", "s1", "aggregate"])
    def _result(self,
                request: pytest.FixtureRequest,
                _result_baseline: Dict[str, Any],
                _result_s1: Dict[str, Any],
                _result_aggregate: Dict[str, Any]) -> Dict[str, Any]:
        """*_result()* dispatch the right per-adaptation result by `request.param`."""
        _map = {
            "baseline": _result_baseline,
            "s1": _result_s1,
            "aggregate": _result_aggregate,
        }
        return _map[request.param]

    def test_art_count_matches_cfg(self, _result: Dict[str, Any]) -> None:
        """*test_art_count_matches_cfg()* `len(_result["artifacts"]) == len(_result["config"].artifacts)`."""
        _arts = _result["artifacts"]
        _cfg = _result["config"]
        assert len(_arts) == len(_cfg.artifacts)

    def test_art_keys_match_cfg(self, _result: Dict[str, Any]) -> None:
        """*test_art_keys_match_cfg()* `list(_result["artifacts"]) == [a.key for a in _result["config"].artifacts]`."""
        _expected = [_a.key for _a in _result["config"].artifacts]
        assert list(_result["artifacts"].keys()) == _expected

    def test_seven_pi_groups_per_art(self, _result: Dict[str, Any]) -> None:
        """*test_seven_pi_groups_per_art()* Buckingham yields `10 relevant - 3 FDUs = 7` Pi-groups for every artifact."""
        for _k, _a in _result["artifacts"].items():
            assert len(_a["pi_groups"]) == 7, f"{_k}: {len(_a['pi_groups'])} Pi-groups"

    def test_four_coefs_per_art(self, _result: Dict[str, Any]) -> None:
        """*test_four_coefs_per_art()* `len(_a["coefficients"]) == 4` (theta, sigma, eta, phi) for every artifact."""
        for _k, _a in _result["artifacts"].items():
            assert len(_a["coefficients"]) == 4, f"{_k}: {len(_a['coefficients'])} coefficients"

    def test_coef_setpoints_are_numeric(self, _result: Dict[str, Any]) -> None:
        """*test_coef_setpoints_are_numeric()* `isinstance(co["setpoint"], (int, float))` after `calculate_setpoint()`."""
        for _k, _a in _result["artifacts"].items():
            for _sym, _co in _a["coefficients"].items():
                assert isinstance(_co["setpoint"], (int, float)), (
                    f"{_k}/{_sym}: setpoint is {type(_co['setpoint']).__name__}"
                )

    def test_sens_block_present(self, _result: Dict[str, Any]) -> None:
        """*test_sens_block_present()* `len(_a["sensitivity"]) > 0` and every key starts with `SEN_`."""
        for _k, _a in _result["artifacts"].items():
            _sens = _a["sensitivity"]
            assert len(_sens) > 0
            assert all(_s.startswith("SEN_") for _s in _sens.keys())

    def test_theta_varies_per_art_baseline(self,
                                           _result_baseline: Dict[str, Any]) -> None:
        """*test_theta_varies_per_art_baseline()* `max(thetas) - min(thetas) > 0.05` after `seed_dim_from_analytic` populates per-artifact L/K ratios; uniform theta means the seed failed."""
        _thetas = [_a["coefficients"][f"\\theta_{{{_k}}}"]["setpoint"]
                   for _k, _a in _result_baseline["artifacts"].items()]
        _range = max(_thetas) - min(_thetas)
        assert _range > 0.05, f"theta range {_range} too small; seed may have failed"


class TestResultEnvelope:
    """**TestResultEnvelope** the JSON envelope written to disk is well-formed and round-trips cleanly. `tmp_path` keeps the real `data/results/dimensional/` tree untouched."""

    def test_wrt_true_writes_file(self,
                                  tmp_path,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_wrt_true_writes_file()* `wrt=True` produces `tmp_path/baseline/dflt.json` with `method == "dimensional"` and 13 artifacts."""
        # redirect _ROOT alongside _RESULTS_DIR so relative_to() can express the path as repo-relative
        from src.methods import dimensional as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path)
        _result = run_dimensional(adp="baseline", wrt=True)
        assert "profile" in _result["paths"]
        _path = tmp_path / "baseline" / "dflt.json"
        assert _path.exists(), f"expected {_path} to exist"
        _doc = json.loads(_path.read_text(encoding="utf-8"))
        assert _doc["method"] == "dimensional"
        assert _doc["profile"] == "dflt"
        assert _doc["scenario"] == "baseline"
        assert len(_doc["artifacts"]) == 13

    def test_envelope_carries_method_cfg(self,
                                         tmp_path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_envelope_carries_method_cfg()* the written blob has `method_config.fdus` and `method_config.coefficients` so the run is self-describing on disk."""
        from src.methods import dimensional as _mod
        monkeypatch.setattr(_mod, "_ROOT", tmp_path)
        monkeypatch.setattr(_mod, "_RESULTS_DIR", tmp_path)
        run_dimensional(adp="baseline", wrt=True)
        _doc = json.loads((tmp_path / "baseline" / "dflt.json").read_text())
        assert "method_config" in _doc
        assert "fdus" in _doc["method_config"]
        assert "coefficients" in _doc["method_config"]


class TestMethodCfgOverride:
    """**TestMethodCfgOverride** the `method_cfg=` kwarg lets tests inject a trimmed spec without touching disk."""

    def test_single_coef_override(self) -> None:
        """*test_single_coef_override()* a one-entry coefficient spec yields `len(_a["coefficients"]) == 1` and `\\theta_{<key>}` per artifact."""
        _trim = {
            "seed": 42,
            "fdus": [
                {
                    "_idx": 0,
                    "_sym": "T",
                    "_fwk": "CUSTOM",
                    "_name": "Time",
                    "_unit": "s",
                    "description": "t"
                },
                {
                    "_idx": 1,
                    "_sym": "S",
                    "_fwk": "CUSTOM",
                    "_name": "Structure",
                    "_unit": "req",
                    "description": "s"
                },
                {
                    "_idx": 2,
                    "_sym": "D",
                    "_fwk": "CUSTOM",
                    "_name": "Data",
                    "_unit": "kB",
                    "description": "d"
                },
            ],
            "coefficients": [
                {
                    "symbol": "theta",
                    "expr_pattern": "{pi[6]} * {pi[3]}**(-1)",
                    "name": "Occupancy",
                    "description": "theta = L/K"
                },
            ],
            "sensitivity": {
                "val_type": "mean",
                "cat": "SYM"
            },
        }
        _result = run_dimensional(adp="baseline", wrt=False, method_cfg=_trim)
        for _k, _a in _result["artifacts"].items():
            assert len(_a["coefficients"]) == 1
            assert f"\\theta_{{{_k}}}" in _a["coefficients"]
