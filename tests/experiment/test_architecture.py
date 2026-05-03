# -*- coding: utf-8 -*-
"""
Module test_architecture.py
===========================

Integration tests for `TasArchitecture`: spin up the in-process 13-service mesh and pin the prototype-component contract — every service answers `/healthz`, the entry-router kind map comes from TAS_{1}'s routing row, `flush_logs` writes per-service CSVs, the deployment gate raises on non-local until G5 ships, and the deployment helpers behave per spec.

Tests that drive traffic against the architecture go through `TasUser` (the public client-side ctxmgr) instead of building `ClientSimulator` directly. Sweep tests live in `tests/experiment/test_scanner.py`; end-to-end ramp tests in `tests/experiment/test_executor.py`.

    - **TestTasArchitecture** startup health, kind-prob derivation, shared TAS app, ramp-driven log flush, deployment-helper surface, deployment-mode gate.
"""
# native python modules
from typing import Any, Dict

# testing framework
import pytest

# modules under test
from src.experiment.architecture import TasArchitecture
from src.experiment.users import TasUser
from src.io import NetCfg, load_method_cfg, load_profile


@pytest.fixture(scope="module")
def _method_cfg() -> Dict[str, Any]:
    """*_method_cfg()* parsed `experiment.json`, cached for the module."""
    return load_method_cfg("experiment")


@pytest.fixture(scope="module")
def _profile_cfg() -> NetCfg:
    """*_profile_cfg()* baseline profile `dflt.json`, cached for the module."""
    return load_profile(adaptation="baseline")


def _tiny_ramp_block(rate: float,
                     min_samples: int = 32,
                     max_probe_s: float = 10.0) -> Dict[str, Any]:
    """*_tiny_ramp_block()* single-rate ramp dict in the JSON shape `load_ramp_cfg` consumes; permissive cascade keeps in-test ramps fast.

    Args:
        rate (float, req/s): target rate placed in `rates`.
        min_samples (int): per-kind sample floor.
        max_probe_s (float, seconds): per-probe safety timeout.

    Returns:
        Dict[str, Any]: ramp block; rolling cascade at threshold 0.5 over a 50-sample window.
    """
    return {
        "rates": [rate],
        "min_samples_per_kind": min_samples,
        "max_probe_window_s": max_probe_s,
        "cascade": {"mode": "rolling",
                    "threshold": 0.5,
                    "window": 50},
    }


class TestTasArchitecture:
    """**TestTasArchitecture** every deployed service answers `/healthz`; entry-router kind map sums to 1 and only targets deployed artifacts; TAS_{1..6} share one FastAPI app; a tiny baseline ramp through `TasUser` populates per-service log buffers and `flush_logs` writes them to disk; `bind_addr` and `local_services()` behave per the deployment / role spec; `__aenter__` raises `NotImplementedError` on `multiprocess` and `remote` until the real-uvicorn launcher ships."""

    @pytest.mark.asyncio
    async def test_all_services_healthy(self,
                                        _profile_cfg: NetCfg,
                                        _method_cfg: Dict[str, Any]) -> None:
        """*test_all_services_healthy()* every key in `arch.apps` answers `/healthz` with HTTP 200 and reports its own name in `body["components"][*]["name"]`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.client is not None
            assert _arch.registry is not None
            for _name in _arch.apps.keys():
                _url = _arch.registry.build_healthz_url(_name)
                _r = await _arch.client.get(_url)
                assert _r.status_code == 200, f"{_name} not healthy"
                _body = _r.json()
                _comp_names = {_c["name"] for _c in _body.get("components", [])}
                assert _name in _comp_names, f"{_name} not in healthz body"

    @pytest.mark.asyncio
    async def test_kind_prob_from_routing(self,
                                          _profile_cfg: NetCfg,
                                          _method_cfg: Dict[str, Any]) -> None:
        """*test_kind_prob_from_routing()* `arch.kind_prob` and `arch.kind_to_tgt` are populated, weights sum to 1 (within 1e-9), and every kind's target is in `arch.apps`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.kind_prob, "architecture did not derive kind_prob"
            assert _arch.kind_to_tgt, "architecture did not derive kind_to_tgt"
            _s = sum(_arch.kind_prob.values())
            assert abs(_s - 1.0) < 1e-9, f"kind_prob sum={_s}"
            for _k, _t in _arch.kind_to_tgt.items():
                assert _t in _arch.apps, f"kind {_k} -> target {_t} not deployed"

    @pytest.mark.asyncio
    async def test_shared_tas_app(self,
                                  _profile_cfg: NetCfg,
                                  _method_cfg: Dict[str, Any]) -> None:
        """*test_shared_tas_app()* `len({id(app) for name, app in arch.apps.items() if name.startswith("TAS_")}) == 1` (all six TAS keys alias to one FastAPI app)."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            _tas_app_ids = {id(_app) for _name, _app in _arch.apps.items()
                            if _name.startswith("TAS_")}
            assert len(_tas_app_ids) == 1, (
                f"expected one shared TAS app, found {len(_tas_app_ids)}")

    @pytest.mark.asyncio
    async def test_baseline_quick_run(self,
                                      _profile_cfg: NetCfg,
                                      _method_cfg: Dict[str, Any],
                                      tmp_path) -> None:
        """*test_baseline_quick_run()* one ramp at lam_entry/10 collects >= 5 records with >= 1 success, the cascade does not trip, and `flush_logs` writes non-empty rows for `TAS_{1}` plus at least one `MAS_{*}`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.client is not None
            assert _arch.registry is not None
            _rate = _arch.get_lam_z_entry() / 10.0
            _patched_method_cfg = dict(_method_cfg)
            _patched_method_cfg["seed"] = 42
            _patched_method_cfg["ramp"] = _tiny_ramp_block(_rate)
            async with TasUser(client=_arch.client,
                               registry=_arch.registry,
                               method_cfg=_patched_method_cfg,
                               kind_prob=dict(_arch.kind_prob)) as _user:
                _result = await _user.run_ramp()
            assert len(_result["probes"]) == 1
            _probe = _result["probes"][0]
            _records = _probe["records"]
            assert len(_records) >= 5, "expected at least a handful of requests"
            _succ = sum(1 for _r in _records if _r.success)
            assert _succ >= 1, "no requests succeeded end-to-end"
            assert _result["saturation_rate"] is None
            _counts = _arch.flush_logs(tmp_path)
            assert _counts.get("TAS_{1}", 0) > 0, "TAS_{1} has no logged invocations"
            assert any(_counts.get(_n, 0) > 0
                       for _n in ("MAS_{1}", "MAS_{2}", "MAS_{3}")), \
                "no MAS_{*} invocations logged"

    @pytest.mark.asyncio
    async def test_flush_csv_per_service(self,
                                         _profile_cfg: NetCfg,
                                         _method_cfg: Dict[str, Any],
                                         tmp_path) -> None:
        """*test_flush_csv_per_service()* after a small ramp, `tmp_path.glob("TAS_*.csv")` returns at least one file."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.client is not None
            assert _arch.registry is not None
            _rate = _arch.get_lam_z_entry() / 20.0
            _patched_method_cfg = dict(_method_cfg)
            _patched_method_cfg["seed"] = 7
            _patched_method_cfg["ramp"] = _tiny_ramp_block(_rate)
            async with TasUser(client=_arch.client,
                               registry=_arch.registry,
                               method_cfg=_patched_method_cfg,
                               kind_prob=dict(_arch.kind_prob)) as _user:
                await _user.run_ramp()
            _arch.flush_logs(tmp_path)
        _files = list(tmp_path.glob("TAS_*.csv"))
        assert len(_files) >= 1

    def test_bind_addr_localhost(self,
                                 _profile_cfg: NetCfg,
                                 _method_cfg: Dict[str, Any]) -> None:
        """*test_bind_addr_localhost()* `deployment="localhost"` gives `arch.bind_addr == "127.0.0.1"` even before `__aenter__`."""
        _arch = TasArchitecture(cfg=_profile_cfg,
                                method_cfg=_method_cfg,
                                adaptation="baseline",
                                deployment="localhost")
        assert _arch.bind_addr == "127.0.0.1"

    def test_bind_addr_multiprocess(self,
                                    _profile_cfg: NetCfg,
                                    _method_cfg: Dict[str, Any]) -> None:
        """*test_bind_addr_multiprocess()* `deployment="multiprocess"` gives `arch.bind_addr == "0.0.0.0"`."""
        _arch = TasArchitecture(cfg=_profile_cfg,
                                method_cfg=_method_cfg,
                                adaptation="baseline",
                                deployment="multiprocess")
        assert _arch.bind_addr == "0.0.0.0"

    def test_bind_addr_remote(self,
                              _profile_cfg: NetCfg,
                              _method_cfg: Dict[str, Any]) -> None:
        """*test_bind_addr_remote()* `deployment="remote"` gives `arch.bind_addr == "0.0.0.0"`."""
        _arch = TasArchitecture(cfg=_profile_cfg,
                                method_cfg=_method_cfg,
                                adaptation="baseline",
                                deployment="remote")
        assert _arch.bind_addr == "0.0.0.0"

    @pytest.mark.asyncio
    async def test_role_all(self,
                            _profile_cfg: NetCfg,
                            _method_cfg: Dict[str, Any]) -> None:
        """*test_role_all()* `launcher_role="all"` gives `len(arch.local_services()) == len(arch.registry.table)`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="all") as _arch:
            assert _arch.registry is not None
            _names = _arch.local_services()
            assert len(_names) == len(_arch.registry.table)

    @pytest.mark.asyncio
    async def test_role_buckets(self,
                                _profile_cfg: NetCfg,
                                _method_cfg: Dict[str, Any]) -> None:
        """*test_role_buckets()* `client` -> only `composite_client`; `composite` -> only `composite_*` minus `composite_client`; `atomic` -> only `atomic`; `composite-atomic` == composite | atomic; `client | composite-atomic` covers the full registry."""
        async with TasArchitecture(cfg=_profile_cfg, method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="client") as _arch_client:
            assert _arch_client.registry is not None
            _client = set(_arch_client.local_services())
            _reg = _arch_client.registry
        for _n in _client:
            assert _reg.table[_n].role == "composite_client"

        async with TasArchitecture(cfg=_profile_cfg, method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="composite") as _arch_comp:
            _comp = set(_arch_comp.local_services())
        for _n in _comp:
            assert _reg.table[_n].role.startswith("composite_")
            assert _reg.table[_n].role != "composite_client"

        async with TasArchitecture(cfg=_profile_cfg, method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="atomic") as _arch_atomic:
            _atomic = set(_arch_atomic.local_services())
        for _n in _atomic:
            assert _reg.table[_n].role == "atomic"

        async with TasArchitecture(cfg=_profile_cfg, method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="composite-atomic"
                                   ) as _arch_ca:
            _ca = set(_arch_ca.local_services())
        assert _ca == (_comp | _atomic)
        assert (_client | _ca) == set(_reg.list_names())

    @pytest.mark.asyncio
    async def test_unknown_role_empty(self,
                                      _profile_cfg: NetCfg,
                                      _method_cfg: Dict[str, Any]) -> None:
        """*test_unknown_role_empty()* an unrecognised `launcher_role` returns `[]` from `local_services()`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline",
                                   launcher_role="not-a-role") as _arch:
            assert _arch.local_services() == []

    def test_local_services_unentered_raises(
            self,
            _profile_cfg: NetCfg,
            _method_cfg: Dict[str, Any]) -> None:
        """*test_local_services_unentered_raises()* `local_services()` on a fresh (un-entered) `TasArchitecture` raises `RuntimeError` whose message contains `"__aenter__"`."""
        _arch = TasArchitecture(cfg=_profile_cfg,
                                method_cfg=_method_cfg,
                                adaptation="baseline")
        with pytest.raises(RuntimeError) as _exc:
            _arch.local_services()
        assert "__aenter__" in str(_exc.value)

    @pytest.mark.asyncio
    async def test_default_resolves_localhost_all(
            self,
            _method_cfg: Dict[str, Any],
            _profile_cfg: NetCfg) -> None:
        """*test_default_resolves_localhost_all()* default deployment is `"localhost"`, default launcher_role is `"all"`, and `local_services()` lists every entry in `arch.registry.table`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.registry is not None
            assert _arch.resolved_deployment == "localhost"
            assert _arch.resolved_launcher_role == "all"
            assert len(_arch.local_services()) == len(_arch.registry.table)

    @pytest.mark.asyncio
    async def test_multiprocess_gated(
            self,
            _method_cfg: Dict[str, Any],
            _profile_cfg: NetCfg) -> None:
        """*test_multiprocess_gated()* entering an architecture with `deployment="multiprocess"` raises `NotImplementedError` whose message contains `"multiprocess"` and `"launch_services"`."""
        with pytest.raises(NotImplementedError) as _exc:
            async with TasArchitecture(cfg=_profile_cfg,
                                       method_cfg=_method_cfg,
                                       adaptation="baseline",
                                       deployment="multiprocess"):
                pass
        assert "multiprocess" in str(_exc.value)
        assert "launch_services" in str(_exc.value)

    @pytest.mark.asyncio
    async def test_remote_gated(self,
                                _method_cfg: Dict[str, Any],
                                _profile_cfg: NetCfg) -> None:
        """*test_remote_gated()* entering an architecture with `deployment="remote"` raises `NotImplementedError` whose message contains `"remote"` and `"launch_services"`."""
        with pytest.raises(NotImplementedError) as _exc:
            async with TasArchitecture(cfg=_profile_cfg,
                                       method_cfg=_method_cfg,
                                       adaptation="baseline",
                                       deployment="remote"):
                pass
        assert "remote" in str(_exc.value)
        assert "launch_services" in str(_exc.value)
