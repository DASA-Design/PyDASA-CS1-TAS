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

    def test_run_experiment_not_yet_supported(self) -> None:
        """Asking for the experiment stage raises so callers know the path is not yet wired."""
        with pytest.raises(NotImplementedError, match="not yet wired"):
            experimental.run(stage="experiment")

    def test_run_unknown_stage_raises(self) -> None:
        """An unknown stage name is rejected immediately rather than silently doing nothing."""
        with pytest.raises(ValueError, match="unknown stage"):
            experimental.run(stage="nonsense")
