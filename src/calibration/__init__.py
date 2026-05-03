# -*- coding: utf-8 -*-
"""Calibration package: precondition-gate building blocks for the per-host noise-floor probe.

This package is the host-side gate per `.claude/skills/design/experimental-design.md` §1: it measures the host's irreducible overhead (timer, jitter, loopback, handler-scaling) so downstream experiment runs can subtract it via `reported = measured - loopback_median ± jitter_p99`. It is NOT a method module; the orchestrator that exposes the method-shaped CLI lives at `src/methods/calibration.py`.

Public API (populated as Stages C3-C7 land):
    - `StopConditions`: dataclass holding the per-iteration halt thresholds (rejection, phi, sigma, loopback two-trial).
    - `should_stop(probe_row, conds)`: pure predicate returning True when any halt condition trips.
    - `should_stop_detailed(probe_row, conds)`: same predicate but returns a dict naming which threshold tripped, used by the controller to record provenance on the envelope's `stop_conditions` block.
    - `loopback_two_trial_ok(t1, t2, conds)`: pure predicate validating two consecutive loopback medians stay within `loopback_two_trial_delta_pct`.
    - `output_path(dpl, host, stamp)`, `write_envelope(env, dpl, host, stamp)`, `find_latest(dpl, host)`, `load_latest(dpl, host)`: per-`dpl` JSON I/O for calibration envelopes under `data/results/calibration/<dpl>/`.
"""
from src.calibration.conditionals import (StopConditions,
                                          loopback_two_trial_ok,
                                          should_stop,
                                          should_stop_detailed)
from src.calibration.envelope import (find_latest,
                                      load_latest,
                                      output_path,
                                      write_envelope)

__all__ = [
    "StopConditions",
    "find_latest",
    "load_latest",
    "loopback_two_trial_ok",
    "output_path",
    "should_stop",
    "should_stop_detailed",
    "write_envelope",
]
