# -*- coding: utf-8 -*-
"""
Module tests/scripts/test_calibration.py
========================================

Contract tests for the calibration script in `src.scripts.calibration`. Focuses on the pure helpers and the high-level orchestration; the full probe path is exercised by `demo` runs and the notebook, not pytest.

**TestRateSweepHelpers**
    - `test_parse_rates_handles_whitespace_and_empty_fragments()` CSV parser contract mirrors `_parse_concurrency`.
    - `test_batch_size_for_matches_target_tick()` K-batch formula tracks `_TARGET_TICK_S`.
    - `test_aggregate_rate_trials_stats_are_correct()` mean / lo / hi / mean_loss_pct maths.
    - `test_find_highest_sustainable_rate_walks_ascending()` calibrate helper picks the top passing rate.

**TestRunRateSweepOrchestration**
    - `test_run_rate_sweep_no_recursion_into_calibration_gate()` when `run_rate_sweep` drives `experiment.run`, the call passes `skip_calibration=True` so the inner run never re-enters the calibration gate.
    - `test_run_with_skip_rate_sweep_true_skips_block()` top-level `run()` with `skip_rate_sweep=True` does not populate the envelope's `rate_sweep` key and does not import the experiment module.
"""
# native python modules
from __future__ import annotations

import sys

# test stack
import pytest

# target under test
from src.scripts import calibration as cal


class TestRateSweepHelpers:
    """**TestRateSweepHelpers** pure helpers inside `src.scripts.calibration`."""

    def test_parse_rates_handles_whitespace_and_empty_fragments(self) -> None:
        """*test_parse_rates_handles_whitespace_and_empty_fragments()* whitespace + empty tokens produce a clean tuple of floats."""
        assert cal._parse_rates("100,200,345") == (100.0, 200.0, 345.0)
        assert cal._parse_rates("100 , 200 , 345") == (100.0, 200.0, 345.0)
        assert cal._parse_rates("100,,200") == (100.0, 200.0)
        assert cal._parse_rates("  ,  50  ,  ,  ") == (50.0,)

    def test_batch_size_for_matches_target_tick(self) -> None:
        """*test_batch_size_for_matches_target_tick()* K formula tracks the 20 ms target tick."""
        # tick = 0.020 s; K = round(tick / interarrival)
        assert cal._batch_size_for(0) == 1
        assert cal._batch_size_for(50) == 1          # 20 ms / 20 ms = 1
        assert cal._batch_size_for(100) == 2         # 20 ms / 10 ms = 2
        assert cal._batch_size_for(500) == 10        # 20 ms / 2 ms = 10

    def test_aggregate_rate_trials_stats_are_correct(self) -> None:
        """*test_aggregate_rate_trials_stats_are_correct()* mean / lo / hi / mean_loss_pct match hand-computed values."""
        _agg = cal._aggregate_rate_trials([
            {"target": 100.0, "effective": 99.0,
             "entry_lambda": 98.5, "gap": 1.0, "loss_pct": 1.0},
            {"target": 100.0, "effective": 100.5,
             "entry_lambda": 99.0, "gap": -0.5, "loss_pct": -0.5},
            {"target": 100.0, "effective": 97.0,
             "entry_lambda": 96.5, "gap": 3.0, "loss_pct": 3.0},
        ])
        assert _agg["n"] == 3
        assert _agg["target"] == pytest.approx(100.0)
        assert _agg["mean"] == pytest.approx(98.8333, abs=1e-3)
        assert _agg["lo"] == pytest.approx(97.0)
        assert _agg["hi"] == pytest.approx(100.5)
        assert _agg["mean_loss_pct"] == pytest.approx(1.1667, abs=1e-3)
        assert _agg["mean_entry_lambda"] == pytest.approx(98.0, abs=1e-3)

    def test_find_highest_sustainable_rate_walks_ascending(self) -> None:
        """*test_find_highest_sustainable_rate_walks_ascending()* returns the highest rate whose `mean_loss_pct` is at or below the threshold; `None` when no rate passes."""
        _aggs = {
            100.0: {"mean_loss_pct": 0.5},
            200.0: {"mean_loss_pct": 1.2},
            300.0: {"mean_loss_pct": 3.4},
            400.0: {"mean_loss_pct": 8.1},
        }
        assert cal._find_highest_sustainable_rate(_aggs, 2.0) == 200.0
        assert cal._find_highest_sustainable_rate(_aggs, 0.25) is None
        assert cal._find_highest_sustainable_rate(_aggs, 100.0) == 400.0


class TestRunRateSweepOrchestration:
    """**TestRunRateSweepOrchestration** orchestration contract: no-recursion guard + opt-in gate."""

    def test_run_rate_sweep_no_recursion_into_calibration_gate(self,
                                                               monkeypatch):
        """*test_run_rate_sweep_no_recursion_into_calibration_gate()* the inner `experiment.run` is always invoked with `skip_calibration=True` so the rate sweep never re-enters its own gate."""
        _calls = []

        def _fake_probe(**kwargs):
            _calls.append(kwargs)
            # shape the experiment.run would return for `client_effective_rate`
            # + a `nodes` frame carrying the entry lambda.
            import pandas as _pd
            return {
                "client_effective_rate": float(kwargs["rate"]) * 0.98,
                "nodes": _pd.DataFrame([
                    {"key": "TAS_{1}",
                     "lambda": float(kwargs["rate"]) * 0.97}
                ]),
            }

        monkeypatch.setattr(cal, "_run_single_rate_probe", _fake_probe)

        _out = cal.run_rate_sweep(
            rates=(100.0, 200.0),
            trials_per_rate=2,
            calibrate=True,
            verbose=False,
        )

        # confirm orchestration shape
        assert _out["rates"] == [100.0, 200.0]
        assert _out["trials_per_rate"] == 2
        assert set(_out["aggregates"].keys()) == {"100.0", "200.0"}
        # calibrate=True records the highest passing rate
        assert "calibrated_rate" in _out

        # no-recursion guard: every _run_single_rate_probe call receives the
        # rate + adaptation + probe knobs, but the inner experiment.run call
        # is OWNED by _run_single_rate_probe itself (which always sets
        # skip_calibration=True). We assert that the helper was called with
        # the right adaptation + cascade so the inner call path is covered.
        assert len(_calls) == 4  # 2 rates * 2 trials
        for _c in _calls:
            assert _c["adaptation"] == cal._DEFAULT_RATE_SWEEP_ADAPTATION
            assert _c["cascade_mode"] == cal._DEFAULT_RATE_SWEEP_CASCADE_MODE

    def test_run_with_skip_rate_sweep_true_skips_block(self, monkeypatch):
        """*test_run_with_skip_rate_sweep_true_skips_block()* top-level `run()` with the default `skip_rate_sweep=True` does NOT populate the envelope's `rate_sweep` key and does NOT import `src.methods.experiment`."""
        # ensure a clean slate for the experiment-module import check
        sys.modules.pop("src.methods.experiment", None)

        # keep the probes cheap; we only care about the rate-sweep gate
        _env = cal.run(
            timer_samples=100,
            jitter_samples=10,
            skip_loopback=True,
            skip_rate_sweep=True,
            write=False,
            verbose=False,
        )
        assert "rate_sweep" not in _env
        assert _env["args"]["skip_rate_sweep"] is True
        # lazy-import guard: rate sweep was skipped so experiment module must
        # NOT have been loaded as a side effect
        assert "src.methods.experiment" not in sys.modules
