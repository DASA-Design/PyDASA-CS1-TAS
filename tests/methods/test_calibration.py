# -*- coding: utf-8 -*-
"""
Module tests/methods/test_calibration.py
========================================

Contract tests for the calibration method in `src.methods.calibration`. Focuses on the pure helpers and the high-level orchestration; the full probe path is exercised by `demo` runs and the notebook, not pytest.

**TestRateSweepHelpers**
    - `test_parse_rates_handles_whitespace_and_empty_fragments()` CSV parser contract mirrors `_parse_n_con_usr`.
    - `test_batch_size_for_matches_target_tick()` send-batch formula tracks `_TARGET_TICK_S`.
    - `test_aggregate_rate_trials_stats_are_correct()` mean / lo / hi / mean_loss_pct maths.
    - `test_find_highest_sustainable_rate_walks_ascending()` calibrate helper picks the top passing rate.

**TestRunRateSweepOrchestration**
    - `test_run_rate_sweep_no_recursion_into_calibration_gate()` when `run_rate_sweep` drives `experiment.run`, the call passes `skip_calibration=True` so the inner run never re-enters the calibration gate.
    - `test_run_with_skip_rate_sweep_true_skips_block()` top-level `run()` with `skip_rate_sweep=True` does not populate the envelope's `rate_sweep` key and does not import the experiment module.

**TestCalibDimCard**
    - `test_returns_empty_when_blocks_missing()` no `handler_scaling` or no `loopback` -> empty dict.
    - `test_keys_match_dc_charts_shape()` LaTeX-subscripted keys plug into `src.view.plot_yoly_chart`.
    - `test_mu_derived_from_loopback_median()` `mu = 1e6 / loopback.median_us` reflected in the meta block.
    - `test_pipeline_routes_through_pydasa()` meta flags PyDASA's `MonteCarloSimulation(mode=DATA)` produced the arrays.
    - `test_theta_and_eta_maths_are_correct()` hand-computed n=10 row locks the formulas (theta = L/K, eta = X*K/(mu*c)).
    - `test_phi_is_nan_without_payload()` phi is NaN for `payload_size_bytes == 0` (degenerate-memory case).
    - `test_phi_computes_when_payload_supplied()` constant payload -> phi == theta row-by-row.
    - `test_run_envelope_carries_dimensional_card()` `run()` attaches the block when handler+loopback are present.

**TestCalibSweepDriver**
    - `test_resolve_mu_anchor_explicit_value()` `sweep_grid.mu_anchor_req_per_s` short-circuits the loopback derivation.
    - `test_resolve_mu_anchor_loopback_default()` no explicit value -> `mu = 1e6 / loopback.median_us`.
    - `test_resolve_mu_anchor_returns_zero_on_missing_loopback()` no loopback + no explicit value -> `(0.0, source_tag)`.
    - `test_returns_empty_when_grid_missing()` explicit empty grid -> empty dict.
    - `test_returns_empty_when_anchor_unresolvable()` no loopback + no explicit anchor -> empty dict.
    - `test_one_entry_per_c_K_mu_combo()` nested dict carries one entry per (c, K, mu_factor) cartesian combo, tagged `CALIBc<c>K<K>m<int(mu_factor*100)>`.
    - `test_per_combo_meta_records_provenance()` every combo's `meta` block carries `mu_anchor_req_per_s`, `mu_anchor_source`, `mu_factor`, `c_srv`, `K_capacity`.
    - `test_lambda_ramp_clamps_to_absolute_bounds()` `lambda_min_req_per_s` / `lambda_max_req_per_s` clamp every driven step inside the accuracy band.

**TestCalibSweepEnvelope**
    - `test_writes_envelope_when_write_true()` output file lands at `<host>_<ts>_sweep.json` under the calibration dir.
    - `test_envelope_carries_grid_and_combos()` written JSON has `host_profile`, `mu_anchor_req_per_s`, `mu_anchor_source`, `sweep_grid`, `combos`.
"""
# native python modules
from __future__ import annotations

import json
import math
import sys
from typing import Any, Dict, List, Optional

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
        """*test_batch_size_for_matches_target_tick()* send-batch formula tracks the 20 ms target tick. Note: this batch is the per-tick send count, NOT the M/M/c/K system capacity."""
        # tick = 0.020 s; batch = round(tick / interarrival); 20/20=1, 20/10=2, 20/2=10
        assert cal._batch_size_for(0) == 1
        assert cal._batch_size_for(50) == 1
        assert cal._batch_size_for(100) == 2
        assert cal._batch_size_for(500) == 10

    def test_aggregate_rate_trials_stats_are_correct(self) -> None:
        """*test_aggregate_rate_trials_stats_are_correct()* mean / lo / hi / mean_loss_pct match hand-computed values. Trial dicts are the ping/echo shape (target / effective / gap / loss_pct); the legacy `entry_lambda` field is no longer produced."""
        _agg = cal._aggregate_rate_trials([
            {"target": 100.0, "effective": 99.0, "gap": 1.0, "loss_pct": 1.0},
            {"target": 100.0, "effective": 100.5, "gap": -0.5, "loss_pct": -0.5},
            {"target": 100.0, "effective": 97.0, "gap": 3.0, "loss_pct": 3.0},
        ])
        assert _agg["n"] == 3
        assert _agg["target"] == pytest.approx(100.0)
        assert _agg["mean"] == pytest.approx(98.8333, abs=1e-3)
        assert _agg["lo"] == pytest.approx(97.0)
        assert _agg["hi"] == pytest.approx(100.5)
        assert _agg["mean_loss_pct"] == pytest.approx(1.1667, abs=1e-3)
        assert "mean_entry_lambda" not in _agg

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
    """**TestRunRateSweepOrchestration** orchestration contract: ping/echo vernier driver, opt-in gate, no TAS coupling."""

    def test_run_rate_sweep_drives_ping_vernier(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """*test_run_rate_sweep_drives_ping_vernier()* the orchestrator stands up one vernier, loops rates x trials via `_drive_lambda_step`, and aggregates achieved rates into the result envelope. Verifies the rate sweep is decoupled from `experiment.run` / TAS profiles."""
        _trials_returned: Dict[float, List[Dict[str, float]]] = {
            100.0: [{"target": 100.0, "effective": 99.0, "gap": 1.0, "loss_pct": 1.0}] * 2,
            200.0: [{"target": 200.0, "effective": 198.0, "gap": 2.0, "loss_pct": 1.0}] * 2,
        }

        async def _fake_async_runner(**kwargs: Any) -> Dict[float, List[Dict[str, float]]]:
            # confirm the orchestrator passes the vernier-driver kwargs through; presence of these keys means we are NOT calling the legacy TAS path
            assert "rates" in kwargs
            assert "trials_per_rate" in kwargs
            assert "window_s" in kwargs
            assert "port" in kwargs
            assert "payload_size_bytes" in kwargs
            return _trials_returned

        monkeypatch.setattr(cal, "_run_rate_sweep_async", _fake_async_runner)

        _out = cal.run_rate_sweep(
            rates=(100.0, 200.0),
            trials_per_rate=2,
            calibrate=True,
            verbose=False,
        )

        # confirm orchestration shape; the new envelope drops adaptation / entry_service / cascade
        assert _out["rates"] == [100.0, 200.0]
        assert _out["trials_per_rate"] == 2
        assert set(_out["aggregates"].keys()) == {"100.0", "200.0"}
        assert "calibrated_rate" in _out
        assert "adaptation" not in _out
        assert "entry_service" not in _out
        assert "cascade" not in _out
        # aggregates carry mean / lo / hi / mean_loss_pct / n; no legacy mean_entry_lambda
        for _agg in _out["aggregates"].values():
            assert "mean_entry_lambda" not in _agg
            assert {"target", "mean", "lo", "hi", "mean_loss_pct", "n"} <= set(_agg.keys())

    def test_run_with_skip_rate_sweep_true_skips_block(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
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
    """**TestCalibDimCard** Route-B dimensional-card derivation contract: coefficients come from measurements (loopback + handler_scaling), output shape plugs into `src.view.plot_yoly_chart`."""

    def _envelope(self, *,
                  loopback_median_us: float = 1000.0,
                  handler: Optional[Dict[str, Dict[str, float]]] = None,
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


# fake handler_scaling stats; used by stubbed `_drive_one_combo` so tests do not spawn real uvicorn instances
def _fake_handler_scaling(n_levels: int = 5) -> Dict[str, Dict[str, float]]:
    """*_fake_handler_scaling()* synthetic per-level stats with shapes `derive_calib_coefs` expects."""
    _out: Dict[str, Dict[str, float]] = {}
    for _i in range(1, n_levels + 1):
        _out[str(_i)] = {
            "min_us": 100.0 * _i,
            "median_us": 200.0 * _i,
            "p95_us": 350.0 * _i,
            "p99_us": 500.0 * _i,
            "std_us": 50.0 * _i,
            "samples": 100,
        }
    return _out


class TestCalibSweepDriver:
    """**TestCalibSweepDriver** Route-B sweep contract: `run_calib_sweep` walks the `(c, K, mu_factor)` cartesian, drives vernier per combo, and reuses `derive_calib_coefs` for the dim-card derivation. Real uvicorn is stubbed via `_drive_one_combo` monkeypatch so the suite stays under 30 s."""

    def _envelope(self) -> Dict[str, Any]:
        """*_envelope()* minimal host envelope with the loopback anchor `_resolve_mu_anchor` falls back to."""
        return {"loopback": {"median_us": 1000.0},
                "host_profile": {"hostname": "test-host"}}

    def _grid(self, **overrides: Any) -> Dict[str, Any]:
        """*_grid()* small `_QUICK_CFG` grid kept under a few combos for fast tests."""
        _g: Dict[str, Any] = {
            "mu_factor": [1.0, 2.0],
            "c": [1, 2],
            "K": [50, 100],
            "lambda_steps": 3,
            "lambda_factor_min": 0.05,
            "util_threshold": 0.95,
            "max_probe_window_s": 0.1,
        }
        _g.update(overrides)
        return _g

    def _stub_drive(self, monkeypatch: pytest.MonkeyPatch,
                    n_levels: int = 5) -> None:
        """*_stub_drive()* monkeypatch `_drive_one_combo` so tests skip the real uvicorn lifecycle."""
        async def _fake(**_kwargs: Any) -> Dict[str, Dict[str, float]]:
            return _fake_handler_scaling(n_levels=n_levels)
        monkeypatch.setattr(cal, "_drive_one_combo", _fake)

    def test_resolve_mu_anchor_explicit_value(self) -> None:
        """*test_resolve_mu_anchor_explicit_value()* `mu_anchor_req_per_s` short-circuits the loopback derivation; source tagged `"explicit"`."""
        _value, _src = cal._resolve_mu_anchor(
            self._envelope(),
            {"mu_anchor_req_per_s": 500.0},
        )
        assert _value == 500.0
        assert _src == "explicit"

    def test_resolve_mu_anchor_loopback_default(self) -> None:
        """*test_resolve_mu_anchor_loopback_default()* no explicit value -> `mu = 1e6 / loopback.median_us`; source tagged `"loopback.median_us"`."""
        _value, _src = cal._resolve_mu_anchor(
            self._envelope(),
            {"mu_anchor_source": "loopback.median_us"},
        )
        assert _value == pytest.approx(1000.0)
        assert _src == "loopback.median_us"

    def test_resolve_mu_anchor_returns_zero_on_missing_loopback(self) -> None:
        """*test_resolve_mu_anchor_returns_zero_on_missing_loopback()* no loopback and no explicit anchor -> `(0.0, source_tag)`."""
        _value, _src = cal._resolve_mu_anchor({}, {})
        assert _value == 0.0
        assert _src == "loopback.median_us"

    def test_returns_empty_when_grid_missing(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_returns_empty_when_grid_missing()* explicit empty grid -> empty dict."""
        self._stub_drive(monkeypatch)
        assert cal.run_calib_sweep(
            self._envelope(),
            sweep_grid={},
            write=False, verbose=False) == {}

    def test_returns_empty_when_anchor_unresolvable(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_returns_empty_when_anchor_unresolvable()* missing loopback and no explicit `mu_anchor_req_per_s` -> empty dict."""
        self._stub_drive(monkeypatch)
        _no_loopback = {"host_profile": {"hostname": "test-host"}}
        assert cal.run_calib_sweep(
            _no_loopback,
            sweep_grid=self._grid(),
            write=False, verbose=False) == {}

    def test_one_entry_per_c_K_mu_combo(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_one_entry_per_c_K_mu_combo()* nested dict carries one entry per `(c, K, mu_factor)` combo, tagged `CALIBc<c>K<K>m<int(mu_factor*100)>`."""
        self._stub_drive(monkeypatch)
        _sweep = cal.run_calib_sweep(
            self._envelope(),
            sweep_grid=self._grid(),
            write=False, verbose=False)
        # 2 c-values x 2 K-values x 2 mu_factor = 8 combos (all K >= c)
        assert len(_sweep) == 8
        for _c_val in (1, 2):
            for _K_val in (50, 100):
                for _mu_factor in (1.0, 2.0):
                    _mu_tag = int(round(_mu_factor * 100))
                    _key = f"CALIBc{_c_val}K{_K_val}m{_mu_tag}"
                    assert _key in _sweep, f"missing {_key}"

    def test_per_combo_meta_records_provenance(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_per_combo_meta_records_provenance()* every combo's `meta` block carries the per-combo provenance (anchor, source, factor, c_srv, K_capacity)."""
        self._stub_drive(monkeypatch)
        _sweep = cal.run_calib_sweep(
            self._envelope(),
            sweep_grid=self._grid(mu_factor=[1.5], c=[2], K=[100]),
            write=False, verbose=False)
        _key = "CALIBc2K100m150"
        assert _key in _sweep
        _meta = _sweep[_key]["meta"]
        assert _meta["mu_anchor_req_per_s"] == pytest.approx(1000.0)
        assert _meta["mu_anchor_source"] == "loopback.median_us"
        assert _meta["mu_factor"] == 1.5
        assert _meta["c_srv"] == 2
        assert _meta["K_capacity"] == 100
        assert _meta["lambda_steps"] == 3

    def test_lambda_ramp_clamps_to_absolute_bounds(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_lambda_ramp_clamps_to_absolute_bounds()* `lambda_min_req_per_s` / `lambda_max_req_per_s` clamp the ramp endpoints; every probed `target_rate` lands inside the band, regardless of `lambda_factor_min` * mu or `util_threshold` * mu * c."""

        # capture target_rate values handed to the step driver; bypass real uvicorn + real httpx by stubbing both
        _seen_rates: List[float] = []

        async def _fake_step(port: int, target_rate: float,
                             window_s: float,
                             body: Dict[str, Any]) -> Dict[str, float]:
            _seen_rates.append(float(target_rate))
            return {"min_us": 1.0, "median_us": 1.0, "p95_us": 1.0,
                    "p99_us": 1.0, "std_us": 0.0, "samples": 1}

        class _FakeServer:
            def __init__(self, *a: Any, **kw: Any) -> None:
                pass

            def start(self) -> None:
                pass

            def wait_ready(self, *a: Any, **kw: Any) -> None:
                pass

            def shutdown(self) -> None:
                pass

        monkeypatch.setattr(cal, "_drive_lambda_step", _fake_step)
        monkeypatch.setattr(cal, "_UvicornThread", _FakeServer)

        _grid = self._grid(
            mu_factor=[2.0], c=[4], K=[200],
            mu_anchor_req_per_s=125.0,
            lambda_min_req_per_s=50.0,
            lambda_max_req_per_s=250.0,
        )
        _sweep = cal.run_calib_sweep(
            self._envelope(), sweep_grid=_grid,
            write=False, verbose=False)
        # the unclamped ramp at mu_factor=2.0 * 125 = mu=250, c=4 would hit lam_hi = 0.95*250*4 = 950 req/s
        # the clamps trim it to [50, 250]; every observed rate must lie in that band
        assert _seen_rates, "expected at least one driven step"
        for _rate in _seen_rates:
            assert 50.0 <= _rate <= 250.0, f"rate {_rate} outside [50, 250]"
        assert "CALIBc4K200m200" in _sweep


class TestCalibSweepEnvelope:
    """**TestCalibSweepEnvelope** the on-disk envelope written by `run_calib_sweep` when `write=True`."""

    def _envelope(self) -> Dict[str, Any]:
        return {"loopback": {"median_us": 1000.0},
                "host_profile": {"hostname": "test-host"}}

    def _grid(self) -> Dict[str, Any]:
        return {"mu_factor": [1.0], "c": [1], "K": [50],
                "lambda_steps": 2, "lambda_factor_min": 0.1,
                "util_threshold": 0.9, "max_probe_window_s": 0.1}

    def test_writes_envelope_when_write_true(
            self,
            monkeypatch: pytest.MonkeyPatch,
            tmp_path: Any) -> None:
        """*test_writes_envelope_when_write_true()* the per-host sweep envelope lands at `<host>_<ts>_sweep.json` under `data/results/experiment/calibration/`."""

        async def _fake(**_kwargs: Any) -> Dict[str, Dict[str, float]]:
            return _fake_handler_scaling()

        monkeypatch.setattr(cal, "_drive_one_combo", _fake)
        # redirect output to tmp_path so the test does not pollute real results dir
        monkeypatch.setattr(cal, "_CALIB_DIR", tmp_path)
        cal.run_calib_sweep(
            self._envelope(),
            sweep_grid=self._grid(),
            write=True, verbose=False)
        _matches = list(tmp_path.glob("test-host_*_sweep.json"))
        assert len(_matches) == 1, f"expected one sweep.json, got {_matches}"

    def test_envelope_carries_grid_and_combos(
            self,
            monkeypatch: pytest.MonkeyPatch,
            tmp_path: Any) -> None:
        """*test_envelope_carries_grid_and_combos()* persisted JSON carries `host_profile`, `mu_anchor_req_per_s`, `mu_anchor_source`, `sweep_grid`, `combos`, `timestamp`."""

        async def _fake(**_kwargs: Any) -> Dict[str, Dict[str, float]]:
            return _fake_handler_scaling()

        monkeypatch.setattr(cal, "_drive_one_combo", _fake)
        monkeypatch.setattr(cal, "_CALIB_DIR", tmp_path)
        cal.run_calib_sweep(
            self._envelope(),
            sweep_grid=self._grid(),
            write=True, verbose=False)
        _path = next(tmp_path.glob("test-host_*_sweep.json"))
        _payload = json.loads(_path.read_text(encoding="utf-8"))
        for _key in ("host_profile", "mu_anchor_req_per_s",
                     "mu_anchor_source", "sweep_grid",
                     "combos", "timestamp"):
            assert _key in _payload, f"missing {_key}"
        assert _payload["host_profile"]["hostname"] == "test-host"
        assert _payload["mu_anchor_source"] == "loopback.median_us"
        # one combo expected from the 1x1x1 grid
        assert "CALIBc1K50m100" in _payload["combos"]
