# -*- coding: utf-8 -*-
"""Calibration package: precondition-gate building blocks for the per-host noise-floor probe.

This package is the host-side gate per `.claude/skills/design/experimental-design.md` §1: it measures the host's irreducible overhead (timer, jitter, loopback, handler-scaling) so downstream experiment runs can subtract it via `reported = measured - loopback_median ± jitter_p99`. It is NOT a method module; the orchestrator that exposes the method-shaped CLI lives at `src/methods/calibration.py`.

Public API (populated as Stages C3-C7 land):
    - `StopConditions`: dataclass holding the per-iteration halt thresholds (rejection, phi, sigma, loopback two-trial).
    - `should_stop(probe_row, conds)`: pure predicate returning True when any halt condition trips.
    - `should_stop_detailed(probe_row, conds)`: same predicate but returns a dict naming which threshold tripped, used by the controller to record provenance on the envelope's `stop_conditions` block.
    - `loopback_two_trial_ok(t1, t2, conds)`: pure predicate validating two consecutive loopback medians stay within `loopback_two_trial_delta_pct`.
    - `output_path(dpl, host, stamp)`, `write_envelope(env, dpl, host, stamp)`, `find_latest(dpl, host)`, `load_latest(dpl, host)`: per-`dpl` JSON I/O for calibration envelopes under `data/results/calibration/<dpl>/`.
    - `snapshot_host_profile()`, `measure_timer(samples)`, `measure_jitter(samples)`, `measure_loopback(port, samples, warmup)`, `measure_handler_scaling(port, n_con_usr, ...)`: host-floor probes producing the raw envelope blocks.
    - `stats_from_us_array(arr)`, `stats_from_us_status_pairs(pairs)`: canonical stats helpers reused by the probes.
    - `run_rate_sweep(rates, ...)`, `find_highest_sustainable_rate(aggregates, threshold)`, `batch_size_for(rate)`: rate-saturation discovery against the standalone vernier.
    - `run_handler_stability_sweep(n_con_usr, c_grid, ...)`, `aggregate_stability_cell(trials, metric)`, `select_c_per_n_con_usr(cells, ...)`: 2D `(n_con_usr × c)` apparatus self-consistency probe.
"""
from src.calibration.conditionals import (StopConditions,
                                          loopback_two_trial_ok,
                                          should_stop,
                                          should_stop_detailed)
from src.calibration.envelope import (find_latest,
                                      load_latest,
                                      output_path,
                                      write_envelope)
from src.calibration.hoststats import (measure_handler_scaling,
                                       measure_jitter,
                                       measure_loopback,
                                       measure_timer,
                                       snapshot_host_profile,
                                       stats_from_us_array,
                                       stats_from_us_status_pairs)
from src.calibration.rate import (batch_size_for,
                                  find_highest_sustainable_rate,
                                  run_rate_sweep)
from src.calibration.stability import (aggregate_stability_cell,
                                       run_handler_stability_sweep,
                                       select_c_per_n_con_usr)

__all__ = [
    "StopConditions",
    "aggregate_stability_cell",
    "batch_size_for",
    "find_highest_sustainable_rate",
    "find_latest",
    "load_latest",
    "loopback_two_trial_ok",
    "measure_handler_scaling",
    "measure_jitter",
    "measure_loopback",
    "measure_timer",
    "output_path",
    "run_handler_stability_sweep",
    "run_rate_sweep",
    "select_c_per_n_con_usr",
    "should_stop",
    "should_stop_detailed",
    "snapshot_host_profile",
    "stats_from_us_array",
    "stats_from_us_status_pairs",
    "write_envelope",
]
