"""Tests for `src.methods.experimental`.

Logic-only checks on the `run()` dispatcher. The full calibration path is integration code; `tests/demo/calibration.py` exercises it end-to-end and the notebook is the human-facing check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.methods import experimental


class TestExperimental:
    """Top-level dispatcher for the experimental method."""

    def test_run_dispatches_calibration(self) -> None:
        """When stage equals calibration, the dispatcher delegates to `run_calibration` and returns its result unchanged."""
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
        """An unknown stage name is rejected immediately rather than silently doing nothing."""
        with pytest.raises(ValueError, match="unknown stage"):
            experimental.run(stage="nonsense")
