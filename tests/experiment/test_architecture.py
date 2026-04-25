# -*- coding: utf-8 -*-
"""
Module test_architecture.py
===========================

Integration tests for `src.experiment.architecture.sweep_arch_exp`. Mirror of the dimensional `tests/dimensional/test_networks.py` shape but each combo launches the FastAPI mesh, so the contract is exercised on a single 1x1x1 grid (one combo only) with `_QUICK_CFG` ramp settings to keep per-file runtime under ~30 s.

Test contracts:

    - **TestSweepArchExpShape** the returned dict has the canonical nested shape and every per-artifact array carries the eight expected keys.
    - **TestSweepArchExpValues** measured coefficients fall inside the dimensional bounds (theta in `[0, 1]`, sigma equals theta under Little's law, eta >= 0) for the smallest stable combo.
    - **TestSweepArchExpStability** a combo where every node hits the saturation cap is dropped (returns empty arrays).
"""
# native python modules
import nest_asyncio
nest_asyncio.apply()

# data types
from typing import Any, Dict  # noqa: E402

# scientific stack
import numpy as np  # noqa: E402

# testing framework
import pytest  # noqa: E402

# modules under test
from src.experiment.architecture import sweep_arch_exp  # noqa: E402
from src.io import NetCfg, load_method_cfg, load_profile  # noqa: E402


# small grid + tight ramp; one combo only to exercise the launch -> log -> coefficient pipeline (test-layout convention)
_QUICK_GRID: Dict[str, Any] = {
    "mu_factor": [1.0],
    "c": [1],
    "K": [32],
    "util_threshold": 0.95,
}

_QUICK_RAMP = {
    "min_samples_per_kind": 32,
    "max_probe_window_s": 3.0,
    "rates": [50],
    "cascade": {"mode": "rolling", "threshold": 0.10, "window": 50},
}


@pytest.fixture(scope="module")
def _profile_cfg() -> NetCfg:
    """*_profile_cfg()* module-cached baseline profile config."""
    return load_profile(adaptation="baseline")


@pytest.fixture(scope="module")
def _method_cfg() -> Dict[str, Any]:
    """*_method_cfg()* module-cached experiment method config with a tight ramp."""
    _cfg = load_method_cfg("experiment")
    _cfg = dict(_cfg)
    _cfg["ramp"] = dict(_QUICK_RAMP)
    return _cfg


@pytest.fixture(scope="module")
def _quick_sweep(
    _profile_cfg: NetCfg,
    _method_cfg: Dict[str, Any],
) -> Dict[str, Dict[str, np.ndarray]]:
    """*_quick_sweep()* run the 1-combo prototype sweep once for the whole module."""
    return sweep_arch_exp(_profile_cfg,
                          _QUICK_GRID,
                          method_cfg=_method_cfg,
                          adp="baseline")


class TestSweepArchExpShape:
    """**TestSweepArchExpShape** returned dict carries one block per artifact with the canonical key set."""

    def test_returns_one_block_per_artifact(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]], _profile_cfg: NetCfg) -> None:
        """*test_returns_one_block_per_artifact()* every artifact in the input cfg shows up as a top-level key."""
        _expected = {_a.key for _a in _profile_cfg.artifacts}
        assert set(_quick_sweep.keys()) == _expected

    def test_each_block_has_eight_keys(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_each_block_has_eight_keys()* each per-artifact block carries theta / sigma / eta / phi plus c / mu / K / lambda arrays."""
        _expected_short = ("\\theta", "\\sigma", "\\eta", "\\phi",
                           "c", "\\mu", "K", "\\lambda")
        for _key, _block in _quick_sweep.items():
            assert len(_block) == 8, f"{_key}: got {list(_block.keys())}"
            for _short in _expected_short:
                _hits = [_s for _s in _block.keys() if _s.startswith(_short)]
                assert _hits, f"{_key}: missing {_short}"

    def test_arrays_are_aligned(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_arrays_are_aligned()* every array within an artifact block has the same length (one row per sweep point)."""
        for _key, _block in _quick_sweep.items():
            _lens = {len(_v) for _v in _block.values()}
            assert len(_lens) == 1, f"{_key}: misaligned {_lens}"


class TestSweepArchExpValues:
    """**TestSweepArchExpValues** measured coefficients fall inside dimensional bounds."""

    def test_theta_bounded(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_theta_bounded()* theta = L/K is in `[0, 1]` for every active artifact."""
        for _key, _block in _quick_sweep.items():
            _th = _block[f"\\theta_{{{_key}}}"]
            if len(_th) == 0:
                continue
            assert (_th >= 0).all(), f"{_key}: negative theta"
            assert (_th <= 1.0).all(), f"{_key}: theta > 1 ({_th.max()})"

    def test_sigma_close_to_theta(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_sigma_close_to_theta()* on the prototype, sigma = lambda*W/K and theta = L/K are NOT exactly equal (operational lambda counts every arrival including failed completions, while L = X*W uses successful-throughput X), so Little's-law equality `lambda*W = L` only holds approximately. Loose 50% tolerance absorbs the failed-completion gap on a small-sample run (tighter requires closed-form values; the dimensional test `tests/dimensional/test_networks.py::test_sigma_matches_theta` covers the exact equality)."""
        for _key, _block in _quick_sweep.items():
            _si = _block[f"\\sigma_{{{_key}}}"]
            _th = _block[f"\\theta_{{{_key}}}"]
            if len(_si) == 0 or len(_th) == 0:
                continue
            assert np.allclose(_si, _th, rtol=0.5, atol=1e-9), \
                f"{_key}: sigma != theta (max rel diff {np.abs(_si - _th).max() / max(_th.max(), 1e-9):.3f})"

    def test_eta_non_negative(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_eta_non_negative()* eta = chi*K/(mu*c) >= 0 since chi, K, mu, c are all positive."""
        for _key, _block in _quick_sweep.items():
            _et = _block[f"\\eta_{{{_key}}}"]
            if len(_et) == 0:
                continue
            assert (_et >= 0).all(), f"{_key}: negative eta"

    def test_phi_equals_theta(self, _quick_sweep: Dict[str, Dict[str, np.ndarray]]) -> None:
        """*test_phi_equals_theta()* phi = M_act / M_buf collapses to L/K in the CS-01 TAS schema, so it equals theta point-for-point."""
        for _key, _block in _quick_sweep.items():
            _th = _block[f"\\theta_{{{_key}}}"]
            _ph = _block[f"\\phi_{{{_key}}}"]
            if len(_th) == 0:
                continue
            assert np.allclose(_th, _ph), f"{_key}: phi != theta"


class TestSweepArchExpStability:
    """**TestSweepArchExpStability** combos that breach the utilisation cap are dropped."""

    def test_unstable_combo_dropped(self, _profile_cfg: NetCfg, _method_cfg: Dict[str, Any]) -> None:
        """*test_unstable_combo_dropped()* a tiny K with a high mu_factor cap forces saturation; the combo is dropped and every per-artifact array is empty."""
        _grid: Dict[str, Any] = {
            "mu_factor": [0.01],   # crush mu so any rate saturates
            "c": [1],
            "K": [1],
            "util_threshold": 0.50,
        }
        _out = sweep_arch_exp(_profile_cfg,
                              _grid,
                              method_cfg=_method_cfg,
                              adp="baseline")
        for _key, _block in _out.items():
            for _sym, _arr in _block.items():
                assert len(_arr) == 0, f"{_key}/{_sym}: expected empty"
