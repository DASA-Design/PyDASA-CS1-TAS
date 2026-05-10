"""Tests for `src.experimental.procedure.bounds`.

**TestBounds**:

- `test_all_within_envelope`: requested values inside the envelope return `passed=True`.
- `test_axis_exceeds_raises`: when `r > r_max_req_s` and `raise_on_fail=True`, raises `EnvelopeExceededError`.
- `test_axis_exceeds_no_raise`: with `raise_on_fail=False`, returns a report with `passed=False`.
- `test_missing_limit_skips`: a missing limit on one axis is treated as "no constraint" and that axis passes.
- `test_missing_request_skips`: a missing requested value on one axis is also skipped.
- `test_envelope_run_id_surfaced`: the report carries the envelope's `run_id` for traceability.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.procedure.bounds import (
    EnvelopeExceededError,
    validate_experimental_limits,
)


def _envelope(*,
              c_max: int | None = 64,
              r_max: int | None = 200,
              w_max: int | None = 4,
              run_id: str = "calib-run") -> dict[str, Any]:
    """Build a minimal envelope dict shaped like the calibration output."""
    _ans: dict[str, Any] = {"run_id": run_id, "gate": {"verifiable_range": {}}}
    if c_max is not None:
        _ans["gate"]["verifiable_range"]["c_max"] = c_max
    if r_max is not None:
        _ans["gate"]["verifiable_range"]["r_max_req_s"] = r_max
    if w_max is not None:
        _ans["gate"]["verifiable_range"]["w_max"] = w_max
    return _ans


class TestBounds:
    """`validate_experimental_limits` per-axis verdicts."""

    def test_all_within_envelope(self) -> None:
        """*test_all_within_envelope()* requested `(c=8, r=100, w=2)` against `(64, 200, 4)` returns `passed=True`."""
        _report = validate_experimental_limits(
            {"c": 8, "r": 100, "w": 2},
            _envelope(),
            raise_on_fail=False,
        )
        assert _report.passed is True
        assert all(_c.passed for _c in _report.checks)

    def test_axis_exceeds_raises(self) -> None:
        """*test_axis_exceeds_raises()* a request that exceeds `r_max_req_s` raises `EnvelopeExceededError` when `raise_on_fail=True`."""
        with pytest.raises(EnvelopeExceededError):
            validate_experimental_limits(
                {"c": 8, "r": 999, "w": 2},
                _envelope(),
            )

    def test_axis_exceeds_no_raise(self) -> None:
        """*test_axis_exceeds_no_raise()* `raise_on_fail=False` returns a report with the failing axis flagged but no exception."""
        _report = validate_experimental_limits(
            {"c": 8, "r": 999, "w": 2},
            _envelope(),
            raise_on_fail=False,
        )
        assert _report.passed is False
        _failed = [_c for _c in _report.checks if not _c.passed]
        assert len(_failed) == 1
        assert _failed[0].axis == "r"

    def test_missing_limit_skips(self) -> None:
        """*test_missing_limit_skips()* an envelope without a limit on one axis treats that axis as unconstrained and passes."""
        _env = _envelope(c_max=None)
        _report = validate_experimental_limits(
            {"c": 9999, "r": 100, "w": 2},
            _env,
            raise_on_fail=False,
        )
        assert _report.passed is True

    def test_missing_request_skips(self) -> None:
        """*test_missing_request_skips()* a request without a value on one axis is skipped (the axis passes)."""
        _report = validate_experimental_limits(
            {"r": 100},
            _envelope(),
            raise_on_fail=False,
        )
        assert _report.passed is True

    def test_envelope_run_id_surfaced(self) -> None:
        """*test_envelope_run_id_surfaced()* the report carries the envelope's `run_id` for traceability."""
        _report = validate_experimental_limits(
            {"r": 100},
            _envelope(run_id="abc123"),
            raise_on_fail=False,
        )
        assert _report.envelope_run_id == "abc123"
