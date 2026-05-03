# -*- coding: utf-8 -*-
"""
Module test_executor.py
=======================

Boundary tests for `src.experiment.executor`: rho_grid expansion (`_resolve_rates`), the one-cell driver (`execute_one`), and the cartesian-grid sweep (`execute_sweep`, absorbed from `scanner.scan_sweep` in Stage 4).

    - **TestExecutor** rho_grid passthrough + Jackson expansion; one-cell envelope shape; sweep block layout, array alignment, dimensional bounds (theta in [0,1], sigma ~ theta, eta >= 0, phi == theta), saturation drop.
"""
# native python modules
import asyncio
import tempfile
from pathlib import Path
from typing import Any, Dict

# scientific stack
import numpy as np

# testing framework
import nest_asyncio
nest_asyncio.apply()

import pytest  # noqa: E402

# modules under test
from src.experiment.executor import (_resolve_rates,  # noqa: E402
                                     execute_one,
                                     execute_sweep)
from src.io import NetCfg, load_method_cfg, load_profile  # noqa: E402


_QUICK_RAMP: Dict[str, Any] = {
    "min_samples_per_kind": 32,
    "max_probe_window_s": 5.0,
    "rates": [10.0],
    "cascade": {"mode": "rolling", "threshold": 0.5, "window": 50},
}


_SWEEP_RAMP: Dict[str, Any] = {
    "min_samples_per_kind": 32,
    "max_probe_window_s": 3.0,
    "rates": [50],
    "cascade": {"mode": "rolling", "threshold": 0.10, "window": 50},
}


# 1x1x1 grid keeps the launch -> log -> coefficient pipeline exercised under ~30 s
_QUICK_GRID: Dict[str, Any] = {
    "mu_factor": [1.0],
    "c": [1],
    "K": [32],
    "util_threshold": 0.95,
}


@pytest.fixture(scope="module")
def _profile_cfg() -> NetCfg:
    """*_profile_cfg()* baseline profile, cached for the module."""
    return load_profile(adaptation="baseline")


@pytest.fixture(scope="module")
def _method_cfg() -> Dict[str, Any]:
    """*_method_cfg()* experiment method config with a tight ramp suitable for `execute_one`."""
    _cfg = dict(load_method_cfg("experiment"))
    _cfg["ramp"] = dict(_QUICK_RAMP)
    return _cfg


@pytest.fixture(scope="module")
def _sweep_method_cfg() -> Dict[str, Any]:
    """*_sweep_method_cfg()* experiment method config with a faster ramp tuned for the per-combo sweep."""
    _cfg = dict(load_method_cfg("experiment"))
    _cfg["ramp"] = dict(_SWEEP_RAMP)
    return _cfg


@pytest.fixture(scope="module")
def _quick_sweep(
        _profile_cfg: NetCfg,
        _sweep_method_cfg: Dict[str, Any]
) -> Dict[str, Dict[str, np.ndarray]]:
    """*_quick_sweep()* run the 1-combo prototype sweep once for the whole module."""
    return execute_sweep(_profile_cfg,
                         _QUICK_GRID,
                         method_cfg=_sweep_method_cfg,
                         adp="baseline")


class TestExecutor:
    """**TestExecutor** `_resolve_rates` is a pure passthrough when no `rho_grid` is set and a Jackson-inverted expansion when present; `execute_one` returns a populated envelope with probes + log counts + positive duration; `execute_sweep` returns one block per artifact, each block carries the canonical 8 keys with aligned arrays, the measured coefficients sit inside the dimensional bounds (theta in [0, 1], sigma ~ theta, eta >= 0, phi == theta), and a combo at the saturation cap is dropped (every per-artifact array empty)."""

    def test_resolve_rates_passthrough(self, _profile_cfg: NetCfg) -> None:
        """*test_resolve_rates_passthrough()* a ramp block with `rates` but no `rho_grid` is returned unchanged; metadata is empty."""
        _block = {"rates": [10.0, 20.0],
                  "cascade": {"mode": "rolling",
                              "threshold": 0.5,
                              "window": 50}}
        _new_block, _meta = _resolve_rates(_profile_cfg, _block)
        assert _new_block == _block
        assert _meta == []

    def test_resolve_rates_expands_grid(self, _profile_cfg: NetCfg) -> None:
        """*test_resolve_rates_expands_grid()* `rho_grid=[r1, r2]` becomes `rates=[lambda1, lambda2]` (monotone), `rho_grid` key is stripped, metadata carries one entry per point with the three expected keys."""
        _block = {"rho_grid": [0.1, 0.2],
                  "cascade": {"mode": "rolling",
                              "threshold": 0.5,
                              "window": 50}}
        _new_block, _meta = _resolve_rates(_profile_cfg, _block)
        assert "rho_grid" not in _new_block
        assert "rates" in _new_block
        assert len(_new_block["rates"]) == 2
        assert _new_block["rates"][0] < _new_block["rates"][1]
        assert len(_meta) == 2
        for _m in _meta:
            assert "rho_target" in _m
            assert "lambda_z_inverted" in _m
            assert "bottleneck_artifact_idx" in _m

    def test_execute_one_baseline(self,
                                  _profile_cfg: NetCfg,
                                  _method_cfg: Dict[str, Any]) -> None:
        """*test_execute_one_baseline()* `execute_one` returns `probes` non-empty, `service_log_counts["TAS_{1}"] > 0`, `duration_s > 0`."""
        async def _go() -> Dict[str, Any]:
            with tempfile.TemporaryDirectory() as _tmp:
                return await execute_one(_profile_cfg,
                                         _method_cfg,
                                         "baseline",
                                         Path(_tmp))
        _result = asyncio.run(_go())
        assert "probes" in _result
        assert len(_result["probes"]) >= 1
        assert _result["duration_s"] > 0.0
        assert _result["service_log_counts"], (
            "service_log_counts must be populated after a ramp")
        assert "TAS_{1}" in _result["service_log_counts"]
        assert _result["service_log_counts"]["TAS_{1}"] > 0

    def test_sweep_one_block_per_artifact(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]],
            _profile_cfg: NetCfg) -> None:
        """*test_sweep_one_block_per_artifact()* `set(sweep.keys()) == {a.key for a in cfg.artifacts}`."""
        _expected = {_a.key for _a in _profile_cfg.artifacts}
        assert set(_quick_sweep.keys()) == _expected

    def test_sweep_eight_keys_per_block(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_eight_keys_per_block()* each per-artifact block carries theta / sigma / eta / phi plus c / mu / K / lambda arrays."""
        _expected_short = ("\\theta", "\\sigma", "\\eta", "\\phi",
                           "c", "\\mu", "K", "\\lambda")
        for _key, _block in _quick_sweep.items():
            assert len(_block) == 8, f"{_key}: got {list(_block.keys())}"
            for _short in _expected_short:
                _hits = [_s for _s in _block.keys() if _s.startswith(_short)]
                assert _hits, f"{_key}: missing {_short}"

    def test_sweep_arrays_aligned(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_arrays_aligned()* every array within an artifact block has the same length (one row per sweep point)."""
        for _key, _block in _quick_sweep.items():
            _lens = {len(_v) for _v in _block.values()}
            assert len(_lens) == 1, f"{_key}: misaligned {_lens}"

    def test_sweep_theta_bounded(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_theta_bounded()* theta = L/K in `[0, 1]` for every active artifact."""
        for _key, _block in _quick_sweep.items():
            _th = _block[f"\\theta_{{{_key}}}"]
            if len(_th) == 0:
                continue
            assert (_th >= 0).all(), f"{_key}: negative theta"
            assert (_th <= 1.0).all(), f"{_key}: theta > 1 ({_th.max()})"

    def test_sweep_sigma_close_to_theta(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_sigma_close_to_theta()* on the prototype, sigma = lambda*W/K and theta = L/K agree only approximately because operational lambda counts every arrival but L = X*W uses successful-throughput X. Loose 50% tolerance absorbs the failed-completion gap on a small-sample run; the dimensional test covers the exact equality."""
        for _key, _block in _quick_sweep.items():
            _si = _block[f"\\sigma_{{{_key}}}"]
            _th = _block[f"\\theta_{{{_key}}}"]
            if len(_si) == 0 or len(_th) == 0:
                continue
            assert np.allclose(_si, _th, rtol=0.5, atol=1e-9), \
                f"{_key}: sigma != theta (max rel diff {np.abs(_si - _th).max() / max(_th.max(), 1e-9):.3f})"

    def test_sweep_eta_non_negative(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_eta_non_negative()* eta = chi*K/(mu*c) >= 0 since chi, K, mu, c are all positive."""
        for _key, _block in _quick_sweep.items():
            _et = _block[f"\\eta_{{{_key}}}"]
            if len(_et) == 0:
                continue
            assert (_et >= 0).all(), f"{_key}: negative eta"

    def test_sweep_phi_equals_theta(
            self,
            _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sweep_phi_equals_theta()* phi = M_act / M_buf collapses to L/K in the CS-01 TAS schema, so it equals theta point-for-point."""
        for _key, _block in _quick_sweep.items():
            _th = _block[f"\\theta_{{{_key}}}"]
            _ph = _block[f"\\phi_{{{_key}}}"]
            if len(_th) == 0:
                continue
            assert np.allclose(_th, _ph), f"{_key}: phi != theta"

    def test_sweep_drops_unstable_combo(
            self,
            _profile_cfg: NetCfg,
            _sweep_method_cfg: Dict[str, Any]) -> None:
        """*test_sweep_drops_unstable_combo()* a crushed mu against a tight `util_threshold` forces saturation; the combo is dropped and every per-artifact array is empty. K=0 disables admission gating so the asyncio queue grows unbounded and the stability check fires on raw utilisation."""
        _grid: Dict[str, Any] = {
            "mu_factor": [0.01],
            "c": [1],
            "K": [0],
            "util_threshold": 0.50,
        }
        _out = execute_sweep(_profile_cfg,
                             _grid,
                             method_cfg=_sweep_method_cfg,
                             adp="baseline")
        for _key, _block in _out.items():
            for _sym, _arr in _block.items():
                assert len(_arr) == 0, f"{_key}/{_sym}: expected empty"
