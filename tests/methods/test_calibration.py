# -*- coding: utf-8 -*-
"""
Module tests/methods/test_calibration.py
========================================

Contract tests for the calibration method in `src.methods.calibration`. Focuses on the pure helpers and the high-level orchestration; the full probe path is exercised by `demo` runs and the notebook, not pytest.

**TestRateSweepHelpers**
    - `test_parse_rates_handles_whitespace_and_empty_fragments()` CSV parser contract mirrors `_parse_n_con_usr`.
    - `test_batch_size_for_matches_target_tick()` K-batch formula tracks `_TARGET_TICK_S`.
    - `test_aggregate_rate_trials_stats_are_correct()` mean / lo / hi / mean_loss_pct maths.
    - `test_find_highest_sustainable_rate_walks_ascending()` calibrate helper picks the top passing rate.

**TestRunRateSweepOrchestration**
    - `test_run_rate_sweep_no_recursion_into_calibration_gate()` when `run_rate_sweep` drives `experiment.run`, the call passes `skip_calibration=True` so the inner run never re-enters the calibration gate.
    - `test_run_with_skip_rate_sweep_true_skips_block()` top-level `run()` with `skip_rate_sweep=True` does not populate the envelope's `rate_sweep` key and does not import the experiment module.
"""
# native python modules
from __future__ import annotations

import math
import sys
from typing import Any, Dict

# scientific stack
import pandas as pd

# test stack
import pytest

# target under test
from src.methods import calibration as cal


class TestRateSweepHelpers:
    """**TestRateSweepHelpers** pure helpers inside `src.methods.calibration`."""

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
            # mimic experiment.run's client_effective_rate + nodes frame
            _rate = float(kwargs["rate"])
            _effective = _rate * 0.98
            _entry_lam = _rate * 0.97
            _entry_row = {"key": "TAS_{1}", "lambda": _entry_lam}
            _nodes = pd.DataFrame([_entry_row])
            return {"client_effective_rate": _effective, "nodes": _nodes}

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

        # no-recursion guard: _run_single_rate_probe owns skip_calibration=True; assert it got the right knobs
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
        # lazy-import guard: skipped sweep must not pull experiment module as a side effect
        assert "src.methods.experiment" not in sys.modules


class TestCalibDimCard:
    """**TestCalibDimCard** Route-B dimensional-card derivation contract: coefficients come from measurements (loopback + handler_scaling), output shape plugs into `src.view.dc_charts.plot_yoly_chart`."""

    def _envelope(self, *,
                  loopback_median_us: float = 1000.0,
                  handler: Dict[str, Dict[str, float]] = None,
                  backlog: int = 16384) -> Dict[str, Any]:
        """*_envelope()* craft a minimal calibration envelope with just the blocks the dim card needs."""
        if handler is None:
            handler = {
                "1": {"median_us": 1000.0},
                "10": {"median_us": 10000.0},
                "100": {"median_us": 100000.0},
            }
        _args = {"uvicorn_backlog": int(backlog)}
        _loopback = {"median_us": float(loopback_median_us)}
        _envelope = {
            "args": _args,
            "loopback": _loopback,
            "handler_scaling": handler,
        }
        return _envelope

    def test_returns_empty_when_blocks_missing(self) -> None:
        """*test_returns_empty_when_blocks_missing()* no `handler_scaling` or no `loopback` -> empty dict (no crash)."""
        assert cal.derive_calib_coefs({}) == {}
        assert cal.derive_calib_coefs(
            {"handler_scaling": {}, "loopback": None}) == {}

    def test_keys_match_dc_charts_shape(self) -> None:
        """*test_keys_match_dc_charts_shape()* output carries the LaTeX-subscripted keys `plot_yoly_chart` looks up via prefix match."""
        _card = cal.derive_calib_coefs(self._envelope())
        _tag = cal._CALIB_DIM_TAG
        assert f"\\theta_{{{_tag}}}" in _card
        assert f"\\sigma_{{{_tag}}}" in _card
        assert f"\\eta_{{{_tag}}}" in _card
        assert f"\\phi_{{{_tag}}}" in _card
        assert f"c_{{{_tag}}}" in _card
        assert f"\\mu_{{{_tag}}}" in _card
        assert f"K_{{{_tag}}}" in _card
        assert "meta" in _card

    def test_mu_derived_from_loopback_median(self) -> None:
        """*test_mu_derived_from_loopback_median()* `mu` = `1e6 / loopback.median_us`; one level reports the scalar value in the meta block."""
        _card = cal.derive_calib_coefs(self._envelope(loopback_median_us=2000.0))
        assert _card["meta"]["mu_req_per_s"] == pytest.approx(500.0)
        assert _card["meta"]["mu_source"] == "loopback.median_us"

    def test_pipeline_routes_through_pydasa(self) -> None:
        """*test_pipeline_routes_through_pydasa()* meta block flags that PyDASA's MonteCarloSimulation in DATA mode produced the coefficient arrays (not hand-rolled arithmetic)."""
        _card = cal.derive_calib_coefs(self._envelope())
        assert "pydasa" in _card["meta"]["pipeline"].lower()
        assert "DATA" in _card["meta"]["pipeline"]

    def test_theta_and_eta_maths_are_correct(self) -> None:
        """*test_theta_and_eta_maths_are_correct()* theta = L/K with L = n_con_usr; eta = X*K / (mu*c) with X = n/R. Hand-compute one row to lock the formulas."""
        # hand-check at n=10: mu=1000, X=1000, K=16384, c=1 -> eta=16384, theta=10/16384
        _card = cal.derive_calib_coefs(self._envelope())
        _tag = cal._CALIB_DIM_TAG

        _levels = _card["meta"]["n_con_usr"]
        _idx_10 = _levels.index(10)
        _theta = _card[f"\\theta_{{{_tag}}}"][_idx_10]
        _eta = _card[f"\\eta_{{{_tag}}}"][_idx_10]

        assert _theta == pytest.approx(10.0 / 16384.0, rel=1e-6)
        assert _eta == pytest.approx(16384.0, rel=1e-6)

    def test_phi_is_nan_without_payload(self) -> None:
        """*test_phi_is_nan_without_payload()* phi is NaN when `payload_size_bytes == 0`; degenerate-memory case documented rather than silently zero."""
        _card = cal.derive_calib_coefs(self._envelope())
        _tag = cal._CALIB_DIM_TAG
        _phi = _card[f"\\phi_{{{_tag}}}"]
        for _v in _phi:
            assert math.isnan(_v)

    def test_phi_computes_when_payload_supplied(self) -> None:
        """*test_phi_computes_when_payload_supplied()* phi = (n * payload) / (K * payload) = n/K when every request carries the same payload."""
        _card = cal.derive_calib_coefs(self._envelope(),
                                       payload_size_bytes=1024)
        _tag = cal._CALIB_DIM_TAG
        _levels = _card["meta"]["n_con_usr"]
        _phi = _card[f"\\phi_{{{_tag}}}"]
        _theta = _card[f"\\theta_{{{_tag}}}"]
        # degenerate-memory case: constant payload -> phi == theta row-by-row
        for _i in range(len(_levels)):
            assert _phi[_i] == pytest.approx(_theta[_i], rel=1e-9)

    def test_run_envelope_carries_dimensional_card(self) -> None:
        """*test_run_envelope_carries_dimensional_card()* top-level `run(skip_loopback=False)` attaches a `dimensional_card` block next to `handler_scaling`; `run(skip_loopback=True)` does not."""
        # with handler_scaling + loopback present: block appears
        _env = self._envelope()
        _env.update({"dimensional_card": cal.derive_calib_coefs(_env)})
        assert "dimensional_card" in _env
        assert _env["dimensional_card"]["meta"]["c_srv"] == 1

        # with loopback absent: helper returns {} and no block is attached
        _stripped = dict(_env)
        _stripped.pop("loopback", None)
        assert cal.derive_calib_coefs(_stripped) == {}
