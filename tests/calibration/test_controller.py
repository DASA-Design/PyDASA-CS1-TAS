# -*- coding: utf-8 -*-
"""
Module test_controller.py
=========================

Pin the boundary contract of `HostSweepGrid`, `DasaSweepGrid`, and `SweepController`. The grid dataclasses are pure types with `from_config` classmethods (full-dict / partial / empty cases); the controller's construction validates `dpl` and stamps fields. The full `run_host_sweep` end-to-end (gauge spawn + 5 probe blocks) carries minutes of wall time and is exercised behind `@pytest.mark.live_mesh`; the default suite stays inline.

    - **TestController** dataclass defaults / frozen / `from_config`; controller `__init__` validates `dpl`; `run_dasa_sweep` raises until C8; injected deriver path attaches the dim-card; (live_mesh) end-to-end host-sweep on `dpl="localhost"`.
"""
# native python modules
import dataclasses
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.calibration import (DasaSweepGrid,
                             HostSweepGrid,
                             StopConditions,
                             SweepController)


def _stub_deriver(envelope: Dict[str, Any],
                  *,
                  payload_size_bytes: int,
                  K_values: Any) -> Dict[str, Any]:
    """*_stub_deriver()* fake `derive_calib_coefs` for testing the `run_dasa_sweep` injection path.

    Args:
        envelope (Dict[str, Any]): host envelope (unused; the stub does not read it).
        payload_size_bytes (int): forwarded payload (recorded so the test can assert it).
        K_values (Any): forwarded K-grid (recorded).

    Returns:
        Dict[str, Any]: marker dict naming the call args so the test can verify the controller passed them through.
    """
    return {"stub": True,
            "payload_size_bytes": payload_size_bytes,
            "K_values": list(K_values)}


class TestController:
    """**TestController** dataclass + controller contract: `HostSweepGrid` and `DasaSweepGrid` are frozen with documented defaults; `from_config` honours partial / empty dicts; `SweepController.__post_init__` validates `dpl`; `run_dasa_sweep` raises `NotImplementedError` without an injected deriver; the live-mesh test runs the full host-floor sweep on `dpl="localhost"`."""

    def test_host_grid_defaults(self) -> None:
        """*test_host_grid_defaults()* default `HostSweepGrid()` carries the documented payload size, ladder, and sample counts."""
        _g = HostSweepGrid()
        assert _g.payload_size_bytes == 128000
        assert _g.samples_per_level == 1024
        assert 1 in _g.n_con_usr
        assert 128 in _g.n_con_usr
        assert _g.run_rate_sweep is True
        assert _g.run_stability_sweep is True

    def test_host_grid_frozen(self) -> None:
        """*test_host_grid_frozen()* mutating any `HostSweepGrid` field raises `dataclasses.FrozenInstanceError`."""
        _g = HostSweepGrid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            _g.payload_size_bytes = 99  # type: ignore[misc]

    def test_host_grid_from_config_full(self) -> None:
        """*test_host_grid_from_config_full()* a config dict with `n_con_usr`, `samples_per_level`, `payload_size_bytes`, plus a nested `rate_sweep` block hydrates every field."""
        _g = HostSweepGrid.from_config({
            "n_con_usr": [1, 2, 4],
            "samples_per_level": 200,
            "payload_size_bytes": 64000,
            "timer_samples": 100,
            "jitter_samples": 50,
            "loopback_samples": 25,
            "loopback_warmup": 5,
            "rate_sweep": {
                "rates": [10.0, 20.0],
                "trials_per_rate": 3,
                "max_probe_window_s": 1.0,
                "target_loss_pct": 1.0,
            },
            "skip_rate_sweep": True,
            "skip_handler_stability_sweep": True,
        })
        assert _g.n_con_usr == (1, 2, 4)
        assert _g.samples_per_level == 200
        assert _g.payload_size_bytes == 64000
        assert _g.rates == (10.0, 20.0)
        assert _g.rate_trials_per_rate == 3
        assert _g.rate_max_probe_s == 1.0
        assert _g.run_rate_sweep is False
        assert _g.run_stability_sweep is False

    def test_host_grid_from_config_empty(self) -> None:
        """*test_host_grid_from_config_empty()* an empty config dict equals the default `HostSweepGrid()`."""
        assert HostSweepGrid.from_config({}) == HostSweepGrid()

    def test_dasa_grid_defaults(self) -> None:
        """*test_dasa_grid_defaults()* default `DasaSweepGrid()` carries `c=(8,16,32)`, `K=(64,128,256)`, `mu_factor=(0.5,1.0,1.5,2.0)`."""
        _g = DasaSweepGrid()
        assert _g.c == (8, 16, 32)
        assert _g.K == (64, 128, 256)
        assert _g.mu_factor == (0.5, 1.0, 1.5, 2.0)

    def test_dasa_grid_frozen(self) -> None:
        """*test_dasa_grid_frozen()* mutating any `DasaSweepGrid` field raises `dataclasses.FrozenInstanceError`."""
        _g = DasaSweepGrid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            _g.c = (1,)  # type: ignore[misc]

    def test_dasa_grid_from_config(self) -> None:
        """*test_dasa_grid_from_config()* `from_config({"sweep_grid": {"c": [4], "K": [16], "mu_factor": [1.0]}})` hydrates all three fields."""
        _g = DasaSweepGrid.from_config(
            {"sweep_grid": {"c": [4], "K": [16], "mu_factor": [1.0]}})
        assert _g.c == (4,)
        assert _g.K == (16,)
        assert _g.mu_factor == (1.0,)

    def test_controller_dpl_validation(self) -> None:
        """*test_controller_dpl_validation()* constructing with `dpl="not-a-dpl"` raises `ValueError` with `"not recognised"` in the message."""
        with pytest.raises(ValueError, match="not recognised"):
            SweepController(host_grid=HostSweepGrid(),
                            dasa_grid=DasaSweepGrid(),
                            stop=StopConditions(),
                            dpl="not-a-dpl")

    def test_controller_localhost_init(self) -> None:
        """*test_controller_localhost_init()* `SweepController(..., dpl="localhost")` constructs and stamps the four fields onto the instance."""
        _c = SweepController(host_grid=HostSweepGrid(),
                             dasa_grid=DasaSweepGrid(),
                             stop=StopConditions(),
                             dpl="localhost")
        assert _c.dpl == "localhost"
        assert _c.port == 8765

    def test_controller_multiprocess_init(self) -> None:
        """*test_controller_multiprocess_init()* `SweepController(..., dpl="multiprocess")` constructs without raising."""
        _c = SweepController(host_grid=HostSweepGrid(),
                             dasa_grid=DasaSweepGrid(),
                             stop=StopConditions(),
                             dpl="multiprocess")
        assert _c.dpl == "multiprocess"

    def test_dasa_sweep_raises_without_deriver(self) -> None:
        """*test_dasa_sweep_raises_without_deriver()* `run_dasa_sweep(envelope)` with no `deriver` arg raises `NotImplementedError` (Stage C8 not yet wired)."""
        _c = SweepController(host_grid=HostSweepGrid(),
                             dasa_grid=DasaSweepGrid(),
                             stop=StopConditions(),
                             dpl="localhost")
        with pytest.raises(NotImplementedError, match="Stage C8"):
            _c.run_dasa_sweep({})

    def test_dasa_sweep_with_injected_deriver(self) -> None:
        """*test_dasa_sweep_with_injected_deriver()* injecting `_stub_deriver` attaches `dimensional_card` to the envelope; the stub records that the controller passed `payload_size_bytes` and `K_values` from its grids."""
        _c = SweepController(host_grid=HostSweepGrid(payload_size_bytes=64000),
                             dasa_grid=DasaSweepGrid(K=(32, 64)),
                             stop=StopConditions(),
                             dpl="localhost")
        _env: Dict[str, Any] = {"loopback": {}, "handler_scaling": {}}
        _result = _c.run_dasa_sweep(_env, deriver=_stub_deriver)
        assert _result is _env
        assert _env["dimensional_card"]["stub"] is True
        assert _env["dimensional_card"]["payload_size_bytes"] == 64000
        assert _env["dimensional_card"]["K_values"] == [32, 64]

    @pytest.mark.live_mesh
    def test_host_sweep_localhost_live(self, tmp_path, monkeypatch) -> None:
        """*test_host_sweep_localhost_live()* `dpl="localhost"` end-to-end: `run_host_sweep()` returns an envelope with `host_profile`, `timer`, `jitter`, `loopback`, `handler_scaling`, `elapsed_s`, `dpl`. Skips the rate + stability sub-blocks (cheap-suite mode) so the test runs in seconds."""
        from src.calibration import envelope as _env_mod
        monkeypatch.setattr(_env_mod, "_CALIB_ROOT", tmp_path / "calibration")
        _grid = HostSweepGrid(
            n_con_usr=(1, 4),
            payload_size_bytes=128,
            samples_per_level=20,
            timer_samples=100,
            jitter_samples=10,
            loopback_samples=10,
            loopback_warmup=2,
            run_rate_sweep=False,
            run_stability_sweep=False,
        )
        _c = SweepController(host_grid=_grid,
                             dasa_grid=DasaSweepGrid(),
                             stop=StopConditions(),
                             dpl="localhost",
                             inter_level_delay_s=0.0,
                             verbose=False)
        _env = _c.run_host_sweep()
        assert "host_profile" in _env
        assert "timer" in _env
        assert "jitter" in _env
        assert "loopback" in _env
        assert "handler_scaling" in _env
        assert _env["dpl"] == "localhost"
        assert _env["elapsed_s"] >= 0.0
        assert "rate_sweep" not in _env
        assert "handler_stability_sweep" not in _env
