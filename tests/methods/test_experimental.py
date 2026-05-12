"""Tests for `src.methods.experimental`.

**TestExperimental**: top-level `run()` dispatcher + per-svc admission lifts (`profile.specs` -> mesh wire format).

- *test_run_dispatches_calibration()*: `stage='calibration'` delegates to `run_calibration` and returns its result unchanged.
- *test_run_dispatches_experiment()*: `stage='experiment'` delegates to `run_experiment` and returns its result unchanged.
- *test_run_dispatches_both()*: `stage='both'` calls `run_calibration` then `run_experiment`, threads the envelope into the second call, and returns both keyed by stage.
- *test_run_unknown_stage_raises()*: an unknown stage name is rejected immediately rather than silently doing nothing.
- *test_admission_lt_baseline_carries_c_and_k()*: `_admission_lt_from_profile('baseline')` returns one entry per artifact with int `c` and `k`.
- *test_resolve_admission_per_svc_wins()*: per-svc lookup overrides the global default; missing ids fall through.
- *test_mesh_admission_block_shape()*: `_build_mesh_admission` carries `{c, K, mu, eps}` per atomic id.

The full calibration + experiment paths are integration code; `tests/demo/calibration.py` exercises them end-to-end and the notebook is the human-facing check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.methods import experimental


class TestExperimental:
    """Top-level `run()` dispatcher + per-svc admission lifts."""

    def test_run_dispatches_calibration(self) -> None:
        """*test_run_dispatches_calibration()* `stage='calibration'` delegates to `run_calibration` and returns its result unchanged."""
        _sentinel: dict[str, Any] = {"sentinel": True}
        with patch.object(experimental,
                          "run_calibration",
                          return_value=_sentinel) as _mocked:
            _ans = experimental.run(stage="calibration",
                                    dpl="localhost",
                                    framework="fastapi",
                                    wsgi_server="waitress",
                                    write=False)
        assert _ans is _sentinel
        _mocked.assert_called_once()

    def test_run_dispatches_experiment(self) -> None:
        """*test_run_dispatches_experiment()* `stage='experiment'` delegates to `run_experiment` and returns its result unchanged."""
        _sentinel: dict[str, Any] = {"sentinel": True}
        with patch.object(experimental,
                          "run_experiment",
                          return_value=_sentinel) as _mocked:
            _ans = experimental.run(stage="experiment",
                                    adp="baseline",
                                    dpl="localhost",
                                    write=False)
        assert _ans is _sentinel
        _mocked.assert_called_once()

    def test_run_dispatches_both(self) -> None:
        """*test_run_dispatches_both()* `stage='both'` calls `run_calibration` then `run_experiment` (envelope is threaded into the second call) and returns both keyed by stage."""
        _calib: dict[str, Any] = {"calib": True, "gate": {"verifiable_range": {}}}
        _exp: dict[str, Any] = {"exp": True}
        with patch.object(experimental,
                          "run_calibration",
                          return_value=_calib) as _calib_mock, patch.object(
                              experimental,
                              "run_experiment",
                              return_value=_exp) as _exp_mock:
            _ans = experimental.run(stage="both",
                                    adp="baseline",
                                    dpl="localhost",
                                    write=False)
        assert _ans == {"calibration": _calib, "experiment": _exp}
        _calib_mock.assert_called_once()
        _exp_mock.assert_called_once()
        # The experiment must reuse the freshly produced envelope rather than re-discovering one.
        assert _exp_mock.call_args.kwargs["envelope"] is _calib

    def test_run_unknown_stage_raises(self) -> None:
        """*test_run_unknown_stage_raises()* an unknown stage name is rejected immediately rather than silently doing nothing."""
        with pytest.raises(ValueError, match="unknown stage"):
            experimental.run(stage="nonsense")

    def test_admission_lt_baseline_carries_c_and_k(self) -> None:
        """*test_admission_lt_baseline_carries_c_and_k()* `_admission_lt_from_profile('baseline')` returns one entry per artifact with int `c` and `k`."""
        _lt = experimental._admission_lt_from_profile("baseline")
        assert "MAS_{1}" in _lt
        _entry = _lt["MAS_{1}"]
        assert isinstance(_entry["c"], int)
        assert isinstance(_entry["k"], int)
        assert _entry["c"] == 1
        assert _entry["k"] == 10

    def test_resolve_admission_per_svc_wins(self) -> None:
        """*test_resolve_admission_per_svc_wins()* per-svc lookup overrides the global default; missing ids fall through."""
        _lt = {"MAS_{1}": {"c": 7, "k": 42}}
        assert experimental._resolve_admission("MAS_{1}", _lt, 1, 1) == (42, 7)
        assert experimental._resolve_admission("OTHER", _lt, 5, 9) == (5, 9)
        assert experimental._resolve_admission("OTHER", _lt, None, None) == (None, None)

    def test_mesh_admission_block_shape(self) -> None:
        """*test_mesh_admission_block_shape()* `_build_mesh_admission` carries `{c, K, mu, eps}` per atomic id."""
        _admission_lt = {"MAS_{1}": {"c": 1, "k": 10}}
        _mu_lt = {"MAS_{1}": 180.0}
        _eps_lt = {"MAS_{1}": 0.12}
        _block = experimental._build_mesh_admission(
            atomic_ids=["MAS_{1}"],
            admission_lt=_admission_lt,
            mu_lt=_mu_lt,
            eps_lt=_eps_lt,
            atomic_admission={"k": None, "c": None},
        )
        assert _block["MAS_{1}"] == {"c": 1, "K": 10, "mu": 180.0, "eps": 0.12}
