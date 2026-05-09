"""Tests for `src.experimental.prototype.calibration.gate`.

Logic-only checks against synthetic envelopes; the notebook applies the gate to a real envelope.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.prototype.calibration.gate import (
    HOST_FLOOR_PROBES,
    _check_handler_scaling,
    _check_jitter,
    _check_loopback,
    _check_probe,
    _check_timer,
    _spread_check,
    stamp_gate,
    verdict,
)


def _full_envelope(*,
                   timer_max_ns: int = 110,
                   timer_median_ns: int = 100,
                   jitter_median_us: float = 1010.0,
                   jitter_target_us: int = 1000,
                   loopback_median_us: float = 100.0,
                   loopback_p99_us: float = 102.0,
                   handler_low: float = 50.0,
                   handler_high: float = 51.0) -> dict[str, Any]:
    """Build a synthetic envelope with all four probe blocks populated.

    Defaults sit comfortably inside the 5 % noise-floor band so tests can keep them as-is for the pass case or perturb specific fields for the fail case.

    Args:
        timer_max_ns (int, optional): max delta. Defaults to 110.
        timer_median_ns (int, optional): median delta. Defaults to 100.
        jitter_median_us (float, optional): measured jitter median. Defaults to 1010.0.
        jitter_target_us (int, optional): jitter target. Defaults to 1000.
        loopback_median_us (float, optional): loopback median. Defaults to 100.0.
        loopback_p99_us (float, optional): loopback p99. Defaults to 102.0.
        handler_low (float, optional): handler-scaling latency at the lowest c. Defaults to 50.0.
        handler_high (float, optional): handler-scaling latency at the highest c. Defaults to 51.0.

    Returns:
        dict[str, Any]: a populated envelope shape ready for `verdict`.
    """
    _env: dict[str, Any] = {
        "timer": {
            "samples_n": 100,
            "median_ns": timer_median_ns,
            "min_ns": 90,
            "max_ns": timer_max_ns,
        },
        "jitter": {
            "samples_n": 10,
            "target_us": jitter_target_us,
            "median_us": jitter_median_us,
            "p95_us": 1100.0,
            "p99_us": 1200.0,
        },
        "loopback": {
            "samples_n": 10,
            "payload_bytes": 64,
            "median_us": loopback_median_us,
            "p95_us": 101.0,
            "p99_us": loopback_p99_us,
        },
        "handler_scaling": {
            "concurs": [1, 4],
            "stats": {
                "1": {"samples_n": 10,
                      "median_us": handler_low,
                      "p95_us": 60.0,
                      "p99_us": 70.0},
                "4": {"samples_n": 40,
                      "median_us": handler_high,
                      "p95_us": 60.0,
                      "p99_us": 70.0},
            },
        },
    }
    return _env


class TestGate:
    """Spread checker + four per-probe rules + verdict + stamp."""

    def test_spread_within(self) -> None:
        """A spread inside the noise-floor band passes the check."""
        _ans = _spread_check(110.0, 100.0, 15.0, "label")
        assert _ans["passed"] is True
        assert _ans["value_pct"] == pytest.approx(10.0)

    def test_spread_over(self) -> None:
        """A spread above the noise-floor band fails the check; the reason line cites both percentages so the operator can see how far off the band the probe was."""
        _ans = _spread_check(110.0, 100.0, 5.0, "label")
        assert _ans["passed"] is False
        assert "10.00%" in _ans["reason"]
        assert "limit 5.00%" in _ans["reason"]

    def test_timer_passes(self) -> None:
        """A clock with consistent ticks (max close to median) passes the timer rule."""
        _ans = _check_timer({"median_ns": 100, "max_ns": 104}, 5.0)
        assert _ans["passed"] is True

    def test_timer_fails(self) -> None:
        """A clock whose worst tick is far from the median fails the timer rule."""
        _ans = _check_timer({"median_ns": 100, "max_ns": 200}, 5.0)
        assert _ans["passed"] is False

    def test_timer_missing_data(self) -> None:
        """A timer block with no data fails as missing rather than passing by default; the gate never trusts an unmeasured probe."""
        _ans = _check_timer({}, 5.0)
        assert _ans["passed"] is False
        assert _ans["reason"] == "missing data"

    def test_jitter_passes(self) -> None:
        """Jitter slightly over the target sleep still passes the rule."""
        _ans = _check_jitter({"target_us": 1000, "median_us": 1010.0}, 5.0)
        assert _ans["passed"] is True

    def test_jitter_fails(self) -> None:
        """Jitter well over the target sleep fails the rule."""
        _ans = _check_jitter({"target_us": 1000, "median_us": 1100.0}, 5.0)
        assert _ans["passed"] is False

    def test_jitter_zero_target(self) -> None:
        """A zero-target jitter block fails as missing data; a probe that wasn't actually run shouldn't pass by accident."""
        _ans = _check_jitter({"target_us": 0, "median_us": 100.0}, 5.0)
        assert _ans["reason"] == "missing data"

    def test_loopback_passes(self) -> None:
        """A small p99-vs-median spread on loopback passes the rule (the tail behaves like the typical case)."""
        _ans = _check_loopback({"median_us": 100.0, "p99_us": 102.0}, 5.0)
        assert _ans["passed"] is True

    def test_loopback_fails(self) -> None:
        """A large p99-vs-median spread on loopback fails the rule (the tail is far from typical)."""
        _ans = _check_loopback({"median_us": 100.0, "p99_us": 150.0}, 5.0)
        assert _ans["passed"] is False

    def test_scaling_passes(self) -> None:
        """A flat latency curve across concurrencies passes the scaling rule."""
        _stats = {"1": {"median_us": 50.0}, "16": {"median_us": 50.5}}
        _ans = _check_handler_scaling({"stats": _stats}, 5.0)
        assert _ans["passed"] is True

    def test_scaling_fails(self) -> None:
        """A latency curve that climbs sharply with concurrency fails the scaling rule."""
        _stats = {"1": {"median_us": 50.0}, "16": {"median_us": 75.0}}
        _ans = _check_handler_scaling({"stats": _stats}, 5.0)
        assert _ans["passed"] is False

    def test_scaling_single_c(self) -> None:
        """A scaling block with only one concurrency level fails as missing data; you cannot compare a probe to itself."""
        _ans = _check_handler_scaling({"stats": {"1": {"median_us": 50.0}}}, 5.0)
        assert _ans["reason"] == "missing data"

    def test_verdict_all_pass(self) -> None:
        """An envelope tuned inside the 5 % band yields `passed=True` overall and per-probe."""
        # 4 % spread, under the 5 % limit
        _env = _full_envelope(timer_max_ns=104)
        _v = verdict(_env, noise_floor_pct=5.0)
        assert _v["passed"] is True
        for _name in HOST_FLOOR_PROBES:
            assert _v["checks"][_name]["passed"] is True

    def test_verdict_one_fails(self) -> None:
        """Pushing one probe outside the band flips the overall verdict to `passed=False` while the others stay `passed=True`."""
        # 100 % spread, over the 5 % limit
        _env = _full_envelope(timer_max_ns=200)
        _v = verdict(_env, noise_floor_pct=5.0)
        assert _v["passed"] is False
        assert _v["checks"]["timer"]["passed"] is False
        assert _v["checks"]["jitter"]["passed"] is True

    def test_verdict_unknown_probe(self) -> None:
        """Dispatching to an unknown probe name raises so config typos surface immediately rather than silently skipping a check."""
        with pytest.raises(ValueError, match="unknown probe"):
            _check_probe("not_a_probe", {}, 5.0)

    def test_stamp_writes(self) -> None:
        """`stamp_gate(env)` mutates `env["gate"]` and returns the same dict; the gate-block fields match the standalone `verdict` output."""
        _env = _full_envelope(timer_max_ns=104)
        _ans = stamp_gate(_env, noise_floor_pct=5.0)
        assert _env["gate"] is _ans
        assert _env["gate"]["passed"] is True
