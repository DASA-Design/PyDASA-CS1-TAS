"""Tests for `src.experimental.prototype.calibration.gate`.

Logic-only checks against synthetic envelopes; the notebook applies the report to a real envelope.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from src.experimental.prototype.calibration.gate import (
    HOST_FLOOR_PROBES,
    stamp_gate,
    verdict,
)


def _full_envelope(*,
                   timer_std_ns: float = 50.0,
                   timer_median_ns: int = 100,
                   jitter_median_us: float = 1010.0,
                   jitter_target_us: int = 1000,
                   jitter_std_us: float = 5.0,
                   loopback_median_us: float = 100.0,
                   loopback_std_us: float = 4.0,
                   handler_low: float = 50.0,
                   handler_high: float = 51.0,
                   sat_rate: int | None = 350) -> dict[str, Any]:
    """Build a synthetic envelope with all four probe blocks + rate block populated.

    Defaults sit comfortably inside the 5 % envelope band so tests can keep them as-is for the pass case or perturb specific fields for the fail case.
    """
    _env: dict[str, Any] = {
        "timer": {
            "samples_n": 100,
            "median_ns": timer_median_ns,
            "std_ns": timer_std_ns,
            "min_ns": 90,
            "max_ns": 110,
        },
        "jitter": {
            "samples_n": 10,
            "target_us": jitter_target_us,
            "median_us": jitter_median_us,
            "std_us": jitter_std_us,
            "p95_us": 1100.0,
            "p99_us": 1200.0,
        },
        "loopback": {
            "samples_n": 10,
            "payload_bytes": 64,
            "median_us": loopback_median_us,
            "std_us": loopback_std_us,
            "p95_us": 101.0,
            "p99_us": 102.0,
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
        "rate": {
            "saturation_rate": sat_rate,
            "ramp": [50, 100, 150, 200],
        },
    }
    return _env


class TestGate:
    """Calibration report: floors + precision band + envelope gates + verifiable range."""

    def test_floors_extracted(self) -> None:
        """Floors block carries each floor's central value + std-dev in microseconds."""
        _v = verdict(_full_envelope())
        _f = _v["floors"]
        assert _f["timer"]["value_us"] == pytest.approx(0.1)
        assert _f["timer"]["std_us"] == pytest.approx(0.05)
        assert _f["jitter"]["value_us"] == pytest.approx(10.0)
        assert _f["loopback"]["value_us"] == pytest.approx(100.0)

    def test_precision_band_quadrature(self) -> None:
        """Precision band is the quadrature sum of the three floor std-devs."""
        _v = verdict(_full_envelope(timer_std_ns=1000.0,
                                    jitter_std_us=3.0,
                                    loopback_std_us=4.0))
        _band = _v["precision_band_us"]
        # timer 1000 ns = 1.0 us; sqrt(1^2 + 3^2 + 4^2) = sqrt(26) ~ 5.099
        assert _band["timer_std_us"] == pytest.approx(1.0)
        assert _band["jitter_std_us"] == pytest.approx(3.0)
        assert _band["loopback_std_us"] == pytest.approx(4.0)
        assert _band["total_us"] == pytest.approx(math.sqrt(26.0))

    def test_precision_band_missing_floor(self) -> None:
        """Missing floor data sets `total_us=None` so the report flags the gap rather than computing on partial data."""
        _env = _full_envelope()
        _env["loopback"] = {}
        _v = verdict(_env)
        assert _v["precision_band_us"]["total_us"] is None

    def test_verifiable_range(self) -> None:
        """Verifiable range reports `c_max` (highest stable concurrency) and `r_max` (saturation rate)."""
        _v = verdict(_full_envelope(sat_rate=350))
        _r = _v["verifiable_range"]
        assert _r["c_max"] == 4
        assert _r["r_max_req_s"] == 350

    def test_c_max_truncated_at_band_break(self) -> None:
        """When scaling breaks above some c, `c_max` is the last concurrency inside the band."""
        _env = _full_envelope()
        _env["handler_scaling"]["stats"] = {
            "1": {"median_us": 50.0},
            "4": {"median_us": 51.0},
            "16": {"median_us": 80.0},
        }
        _v = verdict(_env)
        assert _v["verifiable_range"]["c_max"] == 4

    def test_gate_handler_scaling_pass(self) -> None:
        """Handler-scaling gate passes when at least one concurrency above c=1 stays within the band; reports the knee."""
        _v = verdict(_full_envelope())
        _g = _v["gates"]["handler_scaling"]
        assert _g["passed"] is True
        assert "knee at c=4" in _g["reason"]

    def test_gate_handler_scaling_reports_knee_not_failure(self) -> None:
        """A runaway high-c median does NOT fail the gate; the knee is reported instead (mirrors saturation reporting)."""
        _env = _full_envelope()
        _env["handler_scaling"]["stats"] = {
            "1": {"median_us": 50.0},
            "2": {"median_us": 51.0},
            "4": {"median_us": 100.0},  # break point
            "8": {"median_us": 5_000.0},  # runaway tail; ignored
        }
        _v = verdict(_env)
        _g = _v["gates"]["handler_scaling"]
        assert _g["passed"] is True
        assert "knee at c=2" in _g["reason"]

    def test_gate_handler_scaling_fail_no_headroom(self) -> None:
        """Gate fails only when even the first non-trivial concurrency drifts (zero headroom)."""
        _env = _full_envelope()
        _env["handler_scaling"]["stats"] = {
            "1": {"median_us": 50.0},
            "2": {"median_us": 100.0},
        }
        _v = verdict(_env)
        assert _v["gates"]["handler_scaling"]["passed"] is False

    def test_gate_saturation_pass(self) -> None:
        """Saturation gate passes when the rate sweep reports a knee."""
        _v = verdict(_full_envelope(sat_rate=350))
        assert _v["gates"]["saturation_knee"]["passed"] is True

    def test_gate_saturation_fail(self) -> None:
        """Saturation gate fails when the rate sweep didn't find a knee within its range."""
        _v = verdict(_full_envelope(sat_rate=None))
        assert _v["gates"]["saturation_knee"]["passed"] is False

    def test_overall_passed(self) -> None:
        """Overall `passed` is True iff every envelope gate passes (floors are informational)."""
        _v_ok = verdict(_full_envelope())
        assert _v_ok["passed"] is True
        _v_bad = verdict(_full_envelope(handler_high=80.0))
        assert _v_bad["passed"] is False

    def test_stamp_writes(self) -> None:
        """`stamp_gate(env)` mutates `env["gate"]` and returns the same dict."""
        _env = _full_envelope()
        _ans = stamp_gate(_env, noise_floor_pct=5.0)
        assert _env["gate"] is _ans
        assert _env["gate"]["passed"] is True

    def test_host_floor_probes_constant(self) -> None:
        """The exported probe-name tuple still names the four floor probes (back-compat for the notebook)."""
        assert HOST_FLOOR_PROBES == ("timer", "jitter", "loopback", "handler_scaling")

    def test_summary_keys(self) -> None:
        """Summary block carries one `headline` row per probe + rate; no verdict prose."""
        _v = verdict(_full_envelope())
        _s = _v["summary"]
        assert set(_s.keys()) == {"timer", "jitter", "loopback", "scaling", "rate"}
        for _row in _s.values():
            assert "headline" in _row
            assert "verdict" not in _row

    def test_summary_timer_headline(self) -> None:
        """Timer headline reports the std-dev as +/- microseconds."""
        _v = verdict(_full_envelope(timer_std_ns=50.0))
        assert _v["summary"]["timer"]["headline"] == r"$\pm$ 0.05 $\mu$s"

    def test_summary_scaling_truncates_at_knee(self) -> None:
        """Scaling headline reports the knee (highest c within band), not the runaway value past it."""
        _env = _full_envelope()
        _env["handler_scaling"]["stats"] = {
            "1": {"median_us": 50.0},
            "4": {"median_us": 51.0},
            "16": {"median_us": 80.0},
        }
        _v = verdict(_env)
        assert "c=4" in _v["summary"]["scaling"]["headline"]
        assert "16" not in _v["summary"]["scaling"]["headline"]

    def test_summary_scaling_no_headroom(self) -> None:
        """When even the first non-trivial concurrency drifts, the headline reports 'no headroom'."""
        _env = _full_envelope()
        _env["handler_scaling"]["stats"] = {
            "1": {"median_us": 50.0},
            "2": {"median_us": 100.0},
        }
        _v = verdict(_env)
        assert _v["summary"]["scaling"]["headline"] == "no headroom"

    def test_summary_rate_no_knee(self) -> None:
        """A rate sweep that didn't saturate gets a 'no knee within ramp' headline."""
        _v = verdict(_full_envelope(sat_rate=None))
        assert "no knee" in _v["summary"]["rate"]["headline"]
