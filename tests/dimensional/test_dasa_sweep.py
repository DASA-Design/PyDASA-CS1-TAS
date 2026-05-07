# -*- coding: utf-8 -*-
"""
Module test_dasa_sweep.py
=========================

Pin the boundary contract of `_resolve_mu_anchor`, `_resolve_sweep_grid`, `_build_sweep_output_path`, and the empty-input early-returns of `run_calib_sweep`. The full multi-combo `(c, K, mu_factor)` sweep takes minutes per combo and is exercised behind `@pytest.mark.live_mesh`; the default suite stays inline.

    - **TestDasaSweep** mu-anchor resolution (explicit / loopback / unknown source / zero-loopback degenerate); sweep-grid resolution (explicit / fallback to JSON); output-path shape (host normalisation, `_sweep` suffix, per-`dpl` subdir); `run_calib_sweep` empty-input early-returns (no grid, no anchor, missing loopback).
"""
# native python modules
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.dimensional import run_calib_sweep
from src.dimensional.dasa_sweep import (_build_sweep_output_path,
                                        _resolve_mu_anchor,
                                        _resolve_sweep_grid)


class TestDasaSweep:
    """**TestDasaSweep** pure helpers from `src.dimensional.dasa_sweep` plus empty-input early-returns of `run_calib_sweep`. The mu-anchor table covers all four resolution paths; the output-path shape pins the per-`dpl` location + `_sweep` filename suffix."""

    def test_mu_anchor_explicit_wins(self) -> None:
        """*test_mu_anchor_explicit_wins()* explicit `mu_anchor_req_per_s` returns `(value, "explicit")` regardless of `loopback`."""
        _val, _src = _resolve_mu_anchor(
            envelope={"loopback": {"median_us": 1000.0}},
            sweep_grid={"mu_anchor_req_per_s": 250.0})
        assert _val == 250.0
        assert _src == "explicit"

    def test_mu_anchor_from_loopback(self) -> None:
        """*test_mu_anchor_from_loopback()* default source `loopback.median_us` produces `mu = 1e6 / median_us` and source tag `"loopback.median_us"`."""
        _val, _src = _resolve_mu_anchor(
            envelope={"loopback": {"median_us": 2000.0}},
            sweep_grid={})
        assert _val == 500.0  # 1e6 / 2000 = 500
        assert _src == "loopback.median_us"

    def test_mu_anchor_zero_loopback(self) -> None:
        """*test_mu_anchor_zero_loopback()* `loopback.median_us == 0` returns `(0.0, "loopback.median_us")` so the orchestrator can skip the sweep cleanly."""
        _val, _src = _resolve_mu_anchor(
            envelope={"loopback": {"median_us": 0.0}},
            sweep_grid={})
        assert _val == 0.0
        assert _src == "loopback.median_us"

    def test_mu_anchor_missing_loopback(self) -> None:
        """*test_mu_anchor_missing_loopback()* envelope without a `loopback` block returns `(0.0, "loopback.median_us")`."""
        _val, _src = _resolve_mu_anchor(envelope={}, sweep_grid={})
        assert _val == 0.0
        assert _src == "loopback.median_us"

    def test_mu_anchor_unknown_source(self) -> None:
        """*test_mu_anchor_unknown_source()* an unrecognised `mu_anchor_source` returns `(0.0, source_tag)` so the source name survives into the meta block for diagnosis."""
        _val, _src = _resolve_mu_anchor(
            envelope={"loopback": {"median_us": 100.0}},
            sweep_grid={"mu_anchor_source": "not-a-source"})
        assert _val == 0.0
        assert _src == "not-a-source"

    def test_resolve_sweep_grid_explicit(self) -> None:
        """*test_resolve_sweep_grid_explicit()* an explicit `sweep_grid` argument round-trips as a dict copy (mutation safety)."""
        _explicit: Dict[str, Any] = {"c": [4], "K": [16], "mu_factor": [1.0]}
        _resolved = _resolve_sweep_grid(_explicit)
        assert _resolved == _explicit
        assert _resolved is not _explicit  # copy

    def test_resolve_sweep_grid_fallback(self) -> None:
        """*test_resolve_sweep_grid_fallback()* `None` argument falls back to `calibration.json::sweep_grid` (current JSON has at least `c`, `K`, `mu_factor`)."""
        _resolved = _resolve_sweep_grid(None)
        assert "c" in _resolved
        assert "K" in _resolved
        assert "mu_factor" in _resolved

    def test_output_path_shape(self) -> None:
        """*test_output_path_shape()* path is `<root>/calibration/localhost/<host>_<stamp>_sweep.json` with hostname spaces normalised to hyphens."""
        _p = _build_sweep_output_path(
            profile={"hostname": "MY HOST"},
            stamp="20260504_120000")
        assert _p.name == "MY-HOST_20260504_120000_sweep.json"
        assert _p.parent.name == "localhost"
        assert _p.parent.parent.name == "calibration"

    def test_output_path_default_stamp(self) -> None:
        """*test_output_path_default_stamp()* with no `stamp` argument, the filename ends in a 15-char `YYYYMMDD_HHMMSS` pattern + `_sweep.json`."""
        _p = _build_sweep_output_path(profile={"hostname": "HOST"})
        assert _p.name.startswith("HOST_")
        assert _p.name.endswith("_sweep.json")
        _stamp = _p.name[len("HOST_"):-len("_sweep.json")]
        assert len(_stamp) == 15
        assert _stamp[8] == "_"

    def test_run_empty_grid(self) -> None:
        """*test_run_empty_grid()* `run_calib_sweep(envelope, sweep_grid={})` returns the empty dict (no combos to drive)."""
        _env = {"loopback": {"median_us": 1000.0},
                "host_profile": {"hostname": "HOST"}}
        assert run_calib_sweep(_env, sweep_grid={},
                               write=False, verbose=False) == {}

    def test_run_no_anchor(self) -> None:
        """*test_run_no_anchor()* envelope without a usable mu anchor (zero loopback) returns the empty dict."""
        _env = {"loopback": {"median_us": 0.0},
                "host_profile": {"hostname": "HOST"}}
        _grid = {"c": [1], "K": [10], "mu_factor": [1.0],
                 "lambda_steps": 1, "lambda_factor_min": 0.05,
                 "util_threshold": 0.95}
        assert run_calib_sweep(_env, sweep_grid=_grid,
                               write=False, verbose=False) == {}
