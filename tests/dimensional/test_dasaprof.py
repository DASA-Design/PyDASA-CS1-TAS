# -*- coding: utf-8 -*-
"""
Module test_dasaprof.py
=======================

Pin the boundary contract of `src.dimensional.dasaprof.derive_calib_coefs` and assert byte-identical output against the legacy `src.methods.calibration.derive_calib_coefs` for the same envelope. This is the C8 stop-gate: the relocation+rewrite must not change a single coefficient value, otherwise the orchestrator switchover at C9 would silently shift dim-card numbers.

    - **TestDasaprof** envelope-shape contracts (empty / missing block / non-empty round trip), then a byte-identical regression vs the legacy implementation across (a) single-K, (b) multi-K, (c) zero-payload (phi NaN), (d) non-zero payload paths.
"""
# native python modules
import math
from typing import Any, Dict, List

# scientific stack
import numpy as np

# testing framework
import pytest

# modules under test (new path) and legacy comparison (old path)
from src.dimensional.dasaprof import derive_calib_coefs as derive_new
from src.methods.calibration import derive_calib_coefs as derive_old


def _fixture_envelope() -> Dict[str, Any]:
    """*_fixture_envelope()* fixed-seed calibration envelope shaped like the on-disk JSON.

    Five `n_con_usr` levels with deterministic median-us values that cover the full M/M/c/K range from idle to mild saturation. Loopback median sets `mu`; `args.uvicorn_backlog` sets the legacy K. Used by every regression test below to keep inputs byte-identical between the old and new code paths.

    Returns:
        Dict[str, Any]: envelope dict with `handler_scaling`, `loopback`, `args` blocks populated.
    """
    return {
        "handler_scaling": {
            "1": {"median_us": 250.0, "min_us": 230.0, "p95_us": 280.0,
                  "p99_us": 320.0, "std_us": 15.0, "samples": 1000,
                  "reject_rate": 0.0},
            "10": {"median_us": 480.0, "min_us": 320.0, "p95_us": 720.0,
                   "p99_us": 880.0, "std_us": 95.0, "samples": 1000,
                   "reject_rate": 0.0},
            "32": {"median_us": 1100.0, "min_us": 480.0, "p95_us": 1900.0,
                   "p99_us": 2400.0, "std_us": 280.0, "samples": 1000,
                   "reject_rate": 0.0},
            "64": {"median_us": 2400.0, "min_us": 720.0, "p95_us": 4100.0,
                   "p99_us": 5300.0, "std_us": 620.0, "samples": 1000,
                   "reject_rate": 0.01},
            "128": {"median_us": 4900.0, "min_us": 1200.0, "p95_us": 8400.0,
                    "p99_us": 11000.0, "std_us": 1300.0, "samples": 1000,
                    "reject_rate": 0.04},
        },
        "loopback": {"median_us": 230.0, "min_us": 215.0, "p95_us": 260.0,
                     "p99_us": 290.0, "std_us": 12.0, "samples": 5000},
        "args": {"uvicorn_backlog": 16384},
    }


def _assert_lists_equal_nan_safe(name: str,
                                 a: List[float],
                                 b: List[float]) -> None:
    """*_assert_lists_equal_nan_safe()* compare two coefficient arrays element-wise treating `NaN == NaN` as True.

    `numpy.array_equal` rejects NaNs by default; phi can be all-NaN under zero payload, so this helper does the per-element compare with a NaN-aware short-circuit. Lengths must match, then every pair must be either both-NaN or numerically equal.

    Args:
        name (str): coefficient key (used in the assertion failure message).
        a (List[float]): values from the legacy path.
        b (List[float]): values from the new path.

    Raises:
        AssertionError: when lengths differ or any element disagrees.
    """
    assert len(a) == len(b), f"{name}: length mismatch ({len(a)} vs {len(b)})"
    for _i, (_va, _vb) in enumerate(zip(a, b)):
        _na = math.isnan(_va)
        _nb = math.isnan(_vb)
        if _na and _nb:
            continue
        assert not _na and not _nb, (
            f"{name}[{_i}]: NaN mismatch ({_va} vs {_vb})")
        assert _va == _vb, f"{name}[{_i}]: {_va} != {_vb}"


class TestDasaprof:
    """**TestDasaprof** envelope-shape contracts plus byte-identical regression of the new `src.dimensional.dasaprof.derive_calib_coefs` against the legacy `src.methods.calibration.derive_calib_coefs`. Coverage axes: missing block (early-return empty dict) / single-K (legacy backlog path) / multi-K (tiled cartesian) / zero-payload (phi NaN) / non-zero-payload (phi finite)."""

    def test_empty_envelope(self) -> None:
        """*test_empty_envelope()* `derive_calib_coefs({})` returns the empty dict (no `handler_scaling`, no `loopback`)."""
        assert derive_new({}) == {}
        assert derive_old({}) == {}

    def test_missing_handler_scaling(self) -> None:
        """*test_missing_handler_scaling()* envelope with only a `loopback` block returns the empty dict."""
        _env = {"loopback": {"median_us": 100.0}}
        assert derive_new(_env) == {}

    def test_missing_loopback(self) -> None:
        """*test_missing_loopback()* envelope with only a `handler_scaling` block returns the empty dict."""
        _env = {"handler_scaling": {"1": {"median_us": 100.0}}}
        assert derive_new(_env) == {}

    def test_byte_identical_single_K_zero_payload(self) -> None:
        """*test_byte_identical_single_K_zero_payload()* legacy and new dim cards match exactly for a single-K (legacy backlog) call with `payload_size_bytes=0` (phi degenerate, forced NaN)."""
        _env_old = _fixture_envelope()
        _env_new = _fixture_envelope()
        _new = derive_new(_env_new, payload_size_bytes=0)
        _old = derive_old(_env_old, payload_size_bytes=0)
        assert set(_new.keys()) == set(_old.keys())
        for _key in _new.keys():
            if _key == "meta":
                assert _new[_key] == _old[_key], f"meta mismatch on {_key}"
                continue
            _assert_lists_equal_nan_safe(_key, _new[_key], _old[_key])

    def test_byte_identical_multi_K_with_payload(self) -> None:
        """*test_byte_identical_multi_K_with_payload()* legacy and new dim cards match exactly for a multi-K tiled call (`K_values=[64, 128, 256]`) with `payload_size_bytes=128000` (phi finite)."""
        _env_old = _fixture_envelope()
        _env_new = _fixture_envelope()
        _K = [64, 128, 256]
        _new = derive_new(_env_new, payload_size_bytes=128000, K_values=_K)
        _old = derive_old(_env_old, payload_size_bytes=128000, K_values=_K)
        assert set(_new.keys()) == set(_old.keys())
        for _key in _new.keys():
            if _key == "meta":
                assert _new[_key] == _old[_key], f"meta mismatch on {_key}"
                continue
            _assert_lists_equal_nan_safe(_key, _new[_key], _old[_key])

    def test_byte_identical_custom_tag(self) -> None:
        """*test_byte_identical_custom_tag()* legacy and new dim cards match exactly when a custom `tag` is passed (non-default subscript on every output key)."""
        _env_old = _fixture_envelope()
        _env_new = _fixture_envelope()
        _new = derive_new(_env_new, payload_size_bytes=64000, tag="HOST")
        _old = derive_old(_env_old, payload_size_bytes=64000, tag="HOST")
        assert set(_new.keys()) == set(_old.keys())
        for _key in _new.keys():
            if _key == "meta":
                assert _new[_key] == _old[_key]
                continue
            _assert_lists_equal_nan_safe(_key, _new[_key], _old[_key])

    def test_card_shape(self) -> None:
        """*test_card_shape()* the returned dict carries the four coefficient keys, the four input-side context keys, plus `n_con_usr_*`, `n_con_usr_demand_*`, `reject_rate_*`, and a `meta` dict with the documented provenance fields."""
        _env = _fixture_envelope()
        _card = derive_new(_env, payload_size_bytes=128000)
        assert "\\theta_{CALIB}" in _card
        assert "\\sigma_{CALIB}" in _card
        assert "\\eta_{CALIB}" in _card
        assert "\\phi_{CALIB}" in _card
        assert "c_{CALIB}" in _card
        assert "\\mu_{CALIB}" in _card
        assert "K_{CALIB}" in _card
        assert "\\lambda_{CALIB}" in _card
        assert "n_con_usr_{CALIB}" in _card
        assert "n_con_usr_demand_{CALIB}" in _card
        assert "reject_rate_{CALIB}" in _card
        assert "meta" in _card
        assert _card["meta"]["tag"] == "CALIB"
        assert _card["meta"]["pipeline"] == "pydasa.MonteCarloSimulation(mode=DATA)"

    def test_phi_nan_under_zero_payload(self) -> None:
        """*test_phi_nan_under_zero_payload()* `payload_size_bytes=0` makes every phi entry NaN (degenerate 0/0 memory case is forced to NaN by post-processing)."""
        _env = _fixture_envelope()
        _card = derive_new(_env, payload_size_bytes=0)
        for _v in _card["\\phi_{CALIB}"]:
            assert math.isnan(_v)

    def test_phi_finite_under_payload(self) -> None:
        """*test_phi_finite_under_payload()* with `payload_size_bytes > 0`, phi is finite (the model's memory-usage ratio is well-defined)."""
        _env = _fixture_envelope()
        _card = derive_new(_env, payload_size_bytes=128000)
        for _v in _card["\\phi_{CALIB}"]:
            assert not math.isnan(_v)
            assert _v >= 0.0

    def test_theta_capped_at_one(self) -> None:
        """*test_theta_capped_at_one()* L is capped at K so theta = L/K never exceeds 1 in the output card."""
        _env = _fixture_envelope()
        _card = derive_new(_env, payload_size_bytes=128000)
        for _v in _card["\\theta_{CALIB}"]:
            assert _v <= 1.0 + 1e-9
