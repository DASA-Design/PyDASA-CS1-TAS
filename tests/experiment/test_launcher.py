# -*- coding: utf-8 -*-
"""
Module test_launcher.py
=======================

Integration-level tests for `ExperimentLauncher` + `ClientSimulator`.
Spins up the full 13-service in-process mesh (no real ports), drives a
small client load through `TAS_{1}`, and asserts that:

    - Every deployed service's `/healthz` returns 200 after startup.
    - The launcher derives `kind_weights` from TAS_{1}'s routing-matrix row.
    - A tiny baseline ramp-probe returns enough samples end-to-end + logs the analyse path.
    - `flush_logs()` writes one CSV per deployed service.
"""
# native python modules
from pathlib import Path

# testing framework
import pytest

# modules under test
from src.experiment.client import (CascadeConfig,
                                   ClientConfig,
                                   ClientSimulator,
                                   RampConfig)
from src.experiment.launcher import ExperimentLauncher
from src.io import load_method_config, load_profile


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def _method_cfg():
    return load_method_config("experiment")


@pytest.fixture(scope="module")
def _profile_cfg():
    return load_profile(adaptation="baseline")


def _tiny_ramp_cfg(rate: float,
                   min_samples: int = 32,
                   max_probe_window_s: float = 10.0) -> RampConfig:
    """*_tiny_ramp_cfg()* single-rate ramp, just enough to exercise the probe machinery."""
    return RampConfig(min_samples_per_kind=min_samples,
                      max_probe_window_s=max_probe_window_s,
                      rates=[rate],
                      cascade=CascadeConfig(mode="rolling",
                                            threshold=0.5,
                                            window=50))


class TestLauncherStartup:
    """**TestLauncherStartup** every deployed service is reachable after startup."""

    @pytest.mark.asyncio
    async def test_all_services_healthy(self, _profile_cfg, _method_cfg):
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            assert _lnc.client is not None
            assert _lnc.registry is not None
            # swap-slot artifacts may be in the registry but not deployed
            # for this adaptation (e.g. MAS_{4} absent for baseline) -- only
            # hit services present in apps.
            for _name in _lnc.apps.keys():
                _url = _lnc.registry.build_healthz_url(_name)
                _r = await _lnc.client.get(_url)
                assert _r.status_code == 200, f"{_name} not healthy"
                _body = _r.json()
                # TAS service exposes {"role": "tas", "components": [...]},
                # third-party services expose {"name": <name>, ...}.
                if _body.get("role") == "tas":
                    _comp_names = {_c["name"] for _c in _body.get("components", [])}
                    assert _name in _comp_names, f"{_name} not in TAS healthz body"
                else:
                    assert _body.get("name") == _name

    @pytest.mark.asyncio
    async def test_kind_weights_derived_from_routing(self, _profile_cfg,
                                                     _method_cfg):
        """Launcher exposes kind_weights + kind_to_target derived from TAS_{1}'s routing row."""
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            assert _lnc.kind_weights, "launcher did not derive kind_weights"
            assert _lnc.kind_to_target, "launcher did not derive kind_to_target"
            # weights should sum to 1 (normalised from the routing row)
            _s = sum(_lnc.kind_weights.values())
            assert abs(_s - 1.0) < 1e-9, f"kind_weights sum={_s}"
            # every kind label maps to an artifact deployed in this adaptation
            for _k, _t in _lnc.kind_to_target.items():
                assert _t in _lnc.apps, f"kind {_k} -> target {_t} not deployed"


class TestLauncherE2E:
    """**TestLauncherE2E** tiny baseline ramp-probe; pipeline functional, logs populated."""

    @pytest.mark.asyncio
    async def test_baseline_quick_run(self, _profile_cfg, _method_cfg, tmp_path):
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            # low load well below saturation: lam_entry / 10, min samples 32
            _rate = _lnc.lambda_z_entry() / 10.0
            _client_cfg = ClientConfig(entry_service="TAS_{1}",
                                       seed=42,
                                       kind_weights=_lnc.kind_weights,
                                       ramp=_tiny_ramp_cfg(_rate))
            _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)
            _result = await _sim.run_ramp()

            # probe shape
            assert len(_result["probes"]) == 1
            _probe = _result["probes"][0]
            _records = _probe["records"]
            assert len(_records) >= 5, "expected at least a handful of requests"

            # at least one end-to-end success -- we only check the pipeline is
            # functional. DASA validation against predicted rates happens in
            # the notebook, not here.
            _succ = sum(1 for _r in _records if _r.success)
            assert _succ >= 1, "no requests succeeded end-to-end"

            # at this low rate the cascade must not have tripped
            assert _result["saturation_rate"] is None
            # flush logs; the analyse-path services must have non-zero rows
            _counts = _lnc.flush_logs(tmp_path)
            assert _counts.get("TAS_{1}", 0) > 0, "TAS_{1} has no logged invocations"
            # at least one MAS_{*} was hit (exact one depends on kind sampling)
            assert any(_counts.get(_n, 0) > 0
                       for _n in ("MAS_{1}", "MAS_{2}", "MAS_{3}")), \
                "no MAS_{*} invocations logged"

    @pytest.mark.asyncio
    async def test_flush_writes_csv_per_service(self, _profile_cfg,
                                                _method_cfg, tmp_path):
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            _rate = _lnc.lambda_z_entry() / 20.0
            _client_cfg = ClientConfig(entry_service="TAS_{1}",
                                       seed=7,
                                       kind_weights=_lnc.kind_weights,
                                       ramp=_tiny_ramp_cfg(_rate))
            _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)
            await _sim.run_ramp()
            _lnc.flush_logs(tmp_path)
        # expect at least one CSV file for the entry service
        _files = list(tmp_path.glob("TAS_*.csv"))
        assert len(_files) >= 1
