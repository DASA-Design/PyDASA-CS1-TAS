# -*- coding: utf-8 -*-
"""
Module calibration/conditionals.py
==================================

Stop predicates for the calibration sweep cells. Pure functions: no I/O, no side effects, no module-scope state.

Three independent halt signals combine in `should_stop`:

1. **Rejection rate over threshold**: the model assumes lossless service up to capacity K, so a non-zero reject rate means we are no longer measuring the predicted regime. Default 5% (locked decision I-1, 2026-05-03 evening 3).
2. **Phi at or above 1.0**: phi = M_act / M_buf; once phi reaches 1 the fixed-K buffer assumption is violated (new buffer allocation is active).
3. **Sigma over clip**: sigma = lambda*W/K keeps climbing under saturation even after the L-cap pins theta at 1; default cap 2.0 catches edge cases where rejection counting is delayed and phi is degenerate.

`loopback_two_trial_ok` is separate: it gates the precondition probe itself by checking two consecutive loopback medians stay within `loopback_two_trial_delta_pct` (default 5%).
"""
# native python modules
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class StopConditions:
    """**StopConditions** per-iteration halt thresholds for a calibration sweep.

    Frozen so an instance can be safely shared across sweep cells without accidental in-flight mutation. Defaults match `data/config/method/calibration.json::stop_conditions`.

    Attributes:
        rejection_threshold_pct (float): halt when `reject_rate_pct` exceeds this value. Default 5.0 (locked decision I-1).
        phi_threshold (float): halt when phi reaches this value. Default 1.0 (memory invariant: M_act < M_buf for the model's fixed-K assumption to hold).
        sigma_max_clip (float): halt when sigma exceeds this value. Default 2.0 (one doubling past the saturation knee).
        loopback_two_trial_delta_pct (float): max relative delta between two consecutive loopback median probes. Default 5.0 (precondition gate per `experimental-design.md` §1).
    """

    rejection_threshold_pct: float = 5.0
    phi_threshold: float = 1.0
    sigma_max_clip: float = 2.0
    loopback_two_trial_delta_pct: float = 5.0

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]) -> "StopConditions":
        """*from_config()* hydrate from a parsed `calibration.json::stop_conditions` block.

        Missing keys fall back to the dataclass defaults so a partial JSON still loads.

        Args:
            cfg (Dict[str, Any]): parsed JSON dict; keys not present are skipped.

        Returns:
            StopConditions: instance with all four thresholds resolved.
        """
        return cls(
            rejection_threshold_pct=float(cfg.get(
                "rejection_threshold_pct",
                cls.rejection_threshold_pct)),
            phi_threshold=float(cfg.get(
                "phi_threshold",
                cls.phi_threshold)),
            sigma_max_clip=float(cfg.get(
                "sigma_max_clip",
                cls.sigma_max_clip)),
            loopback_two_trial_delta_pct=float(cfg.get(
                "loopback_two_trial_delta_pct",
                cls.loopback_two_trial_delta_pct)),
        )


def should_stop(probe_row: Dict[str, Any],
                conds: StopConditions) -> bool:
    """*should_stop()* True when the probe row trips any of the three halt signals.

    Returns True on the first tripped condition; the order is rejection -> phi -> sigma so the most methodologically meaningful signal (rejection = outside model envelope) takes precedence. Missing keys are treated as 0.0; a row with no recognised keys returns False.

    Args:
        probe_row (Dict[str, Any]): one sweep cell's measurement output. Recognised keys: `reject_rate_pct` (float, 0-100), `phi` (float), `sigma` (float).
        conds (StopConditions): thresholds.

    Returns:
        bool: True when any of `reject_rate_pct > rejection_threshold_pct`, `phi >= phi_threshold`, `sigma > sigma_max_clip` holds.
    """
    _reject = float(probe_row.get("reject_rate_pct", 0.0))
    if _reject > conds.rejection_threshold_pct:
        return True
    _phi = float(probe_row.get("phi", 0.0))
    if _phi >= conds.phi_threshold:
        return True
    _sigma = float(probe_row.get("sigma", 0.0))
    if _sigma > conds.sigma_max_clip:
        return True
    return False


def should_stop_detailed(probe_row: Dict[str, Any],
                         conds: StopConditions) -> Dict[str, Any]:
    """*should_stop_detailed()* same decision as `should_stop`, plus the per-signal trigger flags and the input + threshold values for envelope provenance.

    Used by the sweep controller to write a `stop_conditions` block onto the output envelope. Each trigger flag is independent so a heavily-saturated row can record multiple trips.

    Args:
        probe_row (Dict[str, Any]): one sweep cell's measurement output (same keys as `should_stop`).
        conds (StopConditions): thresholds.

    Returns:
        Dict[str, Any]: `{"stop": bool, "rejection_triggered": bool, "phi_triggered": bool, "sigma_triggered": bool, "values": {"reject_rate_pct": ..., "phi": ..., "sigma": ...}, "thresholds": {...}}`.
    """
    _reject = float(probe_row.get("reject_rate_pct", 0.0))
    _phi = float(probe_row.get("phi", 0.0))
    _sigma = float(probe_row.get("sigma", 0.0))
    _rej_trip = _reject > conds.rejection_threshold_pct
    _phi_trip = _phi >= conds.phi_threshold
    _sig_trip = _sigma > conds.sigma_max_clip
    return {
        "stop": _rej_trip or _phi_trip or _sig_trip,
        "rejection_triggered": _rej_trip,
        "phi_triggered": _phi_trip,
        "sigma_triggered": _sig_trip,
        "values": {
            "reject_rate_pct": _reject,
            "phi": _phi,
            "sigma": _sigma,
        },
        "thresholds": {
            "rejection_threshold_pct": conds.rejection_threshold_pct,
            "phi_threshold": conds.phi_threshold,
            "sigma_max_clip": conds.sigma_max_clip,
        },
    }


def loopback_two_trial_ok(median_us_t1: float,
                          median_us_t2: float,
                          conds: StopConditions) -> Dict[str, Any]:
    """*loopback_two_trial_ok()* report whether two consecutive loopback medians agree within `conds.loopback_two_trial_delta_pct`.

    The relative delta is computed against the larger of the two medians so the result is symmetric: `delta_pct = abs(t1 - t2) / max(t1, t2) * 100`. Used by the precondition probe; a failed check means the host is too noisy at the gate (per `experimental-design.md` §1: 5% relative error is the gate).

    Args:
        median_us_t1 (float): loopback median from trial 1 in microseconds; must be > 0.
        median_us_t2 (float): loopback median from trial 2 in microseconds; must be > 0.
        conds (StopConditions): supplies `loopback_two_trial_delta_pct`.

    Returns:
        Dict[str, Any]: `{"ok": bool, "delta_pct": float, "threshold_pct": float, "t1_us": float, "t2_us": float}`.

    Raises:
        ValueError: when either median is non-positive (zero or negative loopback medians are instrument errors; aborting is safer than reporting `inf` delta).
    """
    if median_us_t1 <= 0.0 or median_us_t2 <= 0.0:
        _msg = (f"loopback medians must be > 0; got "
                f"t1={median_us_t1}, t2={median_us_t2}")
        raise ValueError(_msg)
    _denom = max(float(median_us_t1), float(median_us_t2))
    _delta_pct = abs(float(median_us_t1) - float(median_us_t2)) / _denom * 100.0
    return {
        "ok": _delta_pct <= conds.loopback_two_trial_delta_pct,
        "delta_pct": _delta_pct,
        "threshold_pct": conds.loopback_two_trial_delta_pct,
        "t1_us": float(median_us_t1),
        "t2_us": float(median_us_t2),
    }
