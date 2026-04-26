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

**TestLauncherDeploymentHelpers**
    - `test_pick_bind_addr_local()` `local` -> `127.0.0.1`.
    - `test_pick_bind_addr_loopback_aliased()` -> `0.0.0.0`.
    - `test_pick_bind_addr_remote()` -> `0.0.0.0`.
    - `test_pick_bind_addr_override()` explicit override returned verbatim.
    - `test_local_services_for_role_all()` `"all"` -> every service.
    - `test_local_services_for_role_buckets()` `"client"` / `"composite"` / `"atomic"` / `"composite-atomic"` filter to expected sets.
    - `test_local_services_for_role_unknown_returns_empty()` typo bucket -> empty list.

**TestLauncherDeploymentGate**
    - `test_local_mode_populates_local_services_with_all()` default `local` mode lists every service.
    - `test_loopback_aliased_raises_until_g5()` non-local deployment raises `NotImplementedError` with a pointer to G5.
    - `test_remote_raises_until_g5()` same gate as `loopback_aliased`.
"""
# native python modules
from pathlib import Path

# testing framework
import pytest

# modules under test
from src.experiment.client import (CascadeCfg,
                                   ClientCfg,
                                   ClientSimulator,
                                   RampCfg)
from src.experiment.launcher import (ExperimentLauncher,
                                     local_services_for_role,
                                     pick_bind_addr)
from src.experiment.registry import SvcRegistry
from src.io import load_method_cfg, load_profile


_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def _method_cfg():
    """*_method_cfg()* module-cached method config (`experiment.json`)."""
    return load_method_cfg("experiment")


@pytest.fixture(scope="module")
def _profile_cfg():
    """*_profile_cfg()* module-cached baseline profile config."""
    return load_profile(adaptation="baseline")


def _tiny_ramp_cfg(rate: float,
                   min_samples: int = 32,
                   max_probe_window_s: float = 10.0) -> RampCfg:
    """*_tiny_ramp_cfg()* single-rate ramp, just enough to exercise the probe machinery."""
    return RampCfg(min_samples_per_kind=min_samples,
                      max_probe_window_s=max_probe_window_s,
                      rates=[rate],
                      cascade=CascadeCfg(mode="rolling",
                                            threshold=0.5,
                                            window=50))


class TestLauncherStartup:
    """**TestLauncherStartup** every deployed service is reachable after startup."""

    @pytest.mark.asyncio
    async def test_all_services_healthy(self, _profile_cfg, _method_cfg):
        """*test_all_services_healthy()* every deployed service answers `/healthz` with HTTP 200 after startup; TAS returns a `components: [...]` list while third-party services return `{"name": <name>, ...}`."""
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
        """*test_kind_weights_derived_from_routing()* `kind_weights` and `kind_to_target` are derived from TAS_{1}'s routing row; weights sum to 1; every kind targets a deployed artifact."""
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
        """*test_baseline_quick_run()* at lam_entry / 10 the cascade never trips, the probe collects >= 5 records with >= 1 success, and `flush_logs` writes non-empty TAS_{1} + some MAS_{*} rows."""
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            # low load well below saturation: lam_entry / 10, min samples 32
            _rate = _lnc.get_lam_z_entry() / 10.0
            _client_cfg = ClientCfg(entry_service="TAS_{1}",
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
        """*test_flush_writes_csv_per_service()* `flush_logs` writes at least one `TAS_*.csv` file to the output directory after a small ramp."""
        async with ExperimentLauncher(
                cfg=_profile_cfg, method_cfg=_method_cfg,
                adaptation="baseline") as _lnc:
            _rate = _lnc.get_lam_z_entry() / 20.0
            _client_cfg = ClientCfg(entry_service="TAS_{1}",
                                       seed=7,
                                       kind_weights=_lnc.kind_weights,
                                       ramp=_tiny_ramp_cfg(_rate))
            _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)
            await _sim.run_ramp()
            _lnc.flush_logs(tmp_path)
        # expect at least one CSV file for the entry service
        _files = list(tmp_path.glob("TAS_*.csv"))
        assert len(_files) >= 1


class TestLauncherDeploymentHelpers:
    """**TestLauncherDeploymentHelpers** pure helpers: `pick_bind_addr` + `local_services_for_role`."""

    def test_pick_bind_addr_local(self):
        """*test_pick_bind_addr_local()* `local` deployment binds the kernel loopback fast path."""
        assert pick_bind_addr("local") == "127.0.0.1"

    def test_pick_bind_addr_loopback_aliased(self):
        """*test_pick_bind_addr_loopback_aliased()* `loopback_aliased` binds `0.0.0.0` so each `127.0.0.X` alias is reachable."""
        assert pick_bind_addr("loopback_aliased") == "0.0.0.0"

    def test_pick_bind_addr_remote(self):
        """*test_pick_bind_addr_remote()* `remote` binds `0.0.0.0` so LAN clients can reach the service."""
        assert pick_bind_addr("remote") == "0.0.0.0"

    def test_pick_bind_addr_override(self):
        """*test_pick_bind_addr_override()* explicit `--bind` override wins over auto-flip."""
        assert pick_bind_addr("remote", override="127.0.0.1") == "127.0.0.1"

    def test_local_services_for_role_all(self, _method_cfg):
        """*test_local_services_for_role_all()* `"all"` returns every service in the registry."""
        _reg = SvcRegistry.from_config(_method_cfg)
        _names = local_services_for_role("all", _reg)
        assert len(_names) == len(_reg.table)

    def test_local_services_for_role_buckets(self, _method_cfg):
        """*test_local_services_for_role_buckets()* each bucket returns the expected role subset."""
        _reg = SvcRegistry.from_config(_method_cfg)
        # client bucket = composite_client only
        _client = set(local_services_for_role("client", _reg))
        for _n in _client:
            assert _reg.table[_n].role == "composite_client"
        # composite bucket = composite_medical / _alarm / _drug
        _comp = set(local_services_for_role("composite", _reg))
        for _n in _comp:
            assert _reg.table[_n].role.startswith("composite_")
            assert _reg.table[_n].role != "composite_client"
        # atomic bucket = atomic only
        _atomic = set(local_services_for_role("atomic", _reg))
        for _n in _atomic:
            assert _reg.table[_n].role == "atomic"
        # composite-atomic = composite (without client) ∪ atomic
        _ca = set(local_services_for_role("composite-atomic", _reg))
        assert _ca == (_comp | _atomic)
        # client and composite-atomic partition all services with composite_client members on top
        assert (_client | _ca) == set(_reg.list_names())

    def test_local_services_for_role_unknown_returns_empty(self, _method_cfg):
        """*test_local_services_for_role_unknown_returns_empty()* typo / unrecognised role -> empty list (caller fails fast)."""
        _reg = SvcRegistry.from_config(_method_cfg)
        assert local_services_for_role("not-a-role", _reg) == []


class TestLauncherDeploymentGate:
    """**TestLauncherDeploymentGate** the `__aenter__` enum gate: only `local` is implemented in this PR; non-local raises with a pointer to G5."""

    @pytest.mark.asyncio
    async def test_local_mode_populates_local_services_with_all(
            self, _method_cfg, _profile_cfg):
        """*test_local_mode_populates_local_services_with_all()* default `local` deployment + `launcher_role='all'` lists every service in `local_services`."""
        async with ExperimentLauncher(cfg=_profile_cfg,
                                      method_cfg=_method_cfg,
                                      adaptation="baseline") as _lnc:
            assert _lnc.resolved_deployment == "local"
            assert _lnc.resolved_launcher_role == "all"
            assert len(_lnc.local_services) == len(_lnc.registry.table)

    @pytest.mark.asyncio
    async def test_loopback_aliased_raises_until_g5(
            self, _method_cfg, _profile_cfg):
        """*test_loopback_aliased_raises_until_g5()* `loopback_aliased` deployment is accepted at construction but `__aenter__` raises until the real-uvicorn launcher script lands (distribute G5)."""
        with pytest.raises(NotImplementedError) as _exc:
            async with ExperimentLauncher(cfg=_profile_cfg,
                                          method_cfg=_method_cfg,
                                          adaptation="baseline",
                                          deployment="loopback_aliased"):
                pass
        assert "loopback_aliased" in str(_exc.value)
        assert "launch_services" in str(_exc.value)

    @pytest.mark.asyncio
    async def test_remote_raises_until_g5(self, _method_cfg, _profile_cfg):
        """*test_remote_raises_until_g5()* `remote` deployment shares the same gate as `loopback_aliased`."""
        with pytest.raises(NotImplementedError) as _exc:
            async with ExperimentLauncher(cfg=_profile_cfg,
                                          method_cfg=_method_cfg,
                                          adaptation="baseline",
                                          deployment="remote"):
                pass
        assert "remote" in str(_exc.value)
        assert "launch_services" in str(_exc.value)
