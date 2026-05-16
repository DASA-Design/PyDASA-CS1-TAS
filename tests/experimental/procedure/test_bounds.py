"""Tests for `src.experimental.procedure.bounds`.

**TestBounds**:

- `test_all_within_envelope`: requested values inside the ceiling return `passed=True`.
- `test_axis_exceeds_raises`: when `r > r_max` and `raise_on_fail=True`, raises `EnvelopeExceededError`.
- `test_axis_exceeds_no_raise`: with `raise_on_fail=False`, returns a report with `passed=False`.
- `test_missing_limit_skips`: a missing ceiling on one axis is treated as "no constraint" and that axis passes.
- `test_missing_request_skips`: a missing requested value on one axis is also skipped.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.procedure.bounds import (
    EnvelopeExceededError,
    validate_experimental_limits,
)


def _limits(*,
            c_max: int | None = 64,
            r_max: int | None = 200,
            w_max: int | None = 4) -> dict[str, Any]:
    """Build a ceiling dict shaped like the `experimental.json::trial` block."""
    _ans: dict[str, Any] = {}
    if c_max is not None:
        _ans["c_max"] = c_max
    if r_max is not None:
        _ans["r_max"] = r_max
    if w_max is not None:
        _ans["w_max"] = w_max
    return _ans


class TestBounds:
    """`validate_experimental_limits` per-axis verdicts."""

    def test_all_within_envelope(self) -> None:
        """*test_all_within_envelope()* requested `(c=8, r=100, w=2)` against ceiling `(64, 200, 4)` returns `passed=True`."""
        _report = validate_experimental_limits(
            {"c": 8, "r": 100, "w": 2},
            _limits(),
            raise_on_fail=False,
        )
        assert _report.passed is True
        assert all(_c.passed for _c in _report.checks)

    def test_axis_exceeds_raises(self) -> None:
        """*test_axis_exceeds_raises()* a request that exceeds `r_max` raises `EnvelopeExceededError` when `raise_on_fail=True`."""
        with pytest.raises(EnvelopeExceededError):
            validate_experimental_limits(
                {"c": 8, "r": 999, "w": 2},
                _limits(),
            )

    def test_axis_exceeds_no_raise(self) -> None:
        """*test_axis_exceeds_no_raise()* `raise_on_fail=False` returns a report with the failing axis flagged but no exception."""
        _report = validate_experimental_limits(
            {"c": 8, "r": 999, "w": 2},
            _limits(),
            raise_on_fail=False,
        )
        assert _report.passed is False
        _failed = [_c for _c in _report.checks if not _c.passed]
        assert len(_failed) == 1
        assert _failed[0].axis == "r"

    def test_missing_limit_skips(self) -> None:
        """*test_missing_limit_skips()* a ceiling without a value on one axis treats that axis as unconstrained and passes."""
        _lim = _limits(c_max=None)
        _report = validate_experimental_limits(
            {"c": 9999, "r": 100, "w": 2},
            _lim,
            raise_on_fail=False,
        )
        assert _report.passed is True

    def test_missing_request_skips(self) -> None:
        """*test_missing_request_skips()* a request without a value on one axis is skipped (the axis passes)."""
        _report = validate_experimental_limits(
            {"r": 100},
            _limits(),
            raise_on_fail=False,
        )
        assert _report.passed is True
