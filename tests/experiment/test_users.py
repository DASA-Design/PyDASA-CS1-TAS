# -*- coding: utf-8 -*-
"""
Module test_users.py
====================

Boundary tests for `TasUser`: independent of `TasArchitecture`, borrows the supplied transport / registry by identity, propagates `kind_prob` into `cfg`, resets the stop guard on exit, raises before entry, and forwards `run_ramp()` verbatim. One live test through a real `TasArchitecture` exercises the executor-layer bridge.

    - **TestTasUser** ctxmgr lifecycle, borrow chain, kind-prob propagation, guard reset, pre-entry raise, delegation, end-to-end ramp.
"""
# native python modules
from typing import Any, Dict, cast

# testing framework
import pytest

# web stack
import httpx

# modules under test
from src.experiment.architecture import TasArchitecture
from src.experiment.client import ClientSimulator
from src.experiment.users import TasUser
from src.experiment.wire import SvcRegistry
from src.io import NetCfg, load_method_cfg, load_profile


_KP_SOLO: Dict[str, float] = {"MAS_{1}": 1.0}


@pytest.fixture(scope="module")
def _method_cfg() -> Dict[str, Any]:
    """*_method_cfg()* parsed `experiment.json`, cached for the module."""
    return load_method_cfg("experiment")


@pytest.fixture(scope="module")
def _profile_cfg() -> NetCfg:
    """*_profile_cfg()* baseline profile `dflt.json`, cached for the module."""
    return load_profile(adaptation="baseline")


def _tiny_ramp_block(rate: float) -> Dict[str, Any]:
    """*_tiny_ramp_block()* single-rate ramp dict with permissive cascade thresholds; keeps in-test ramps fast.

    Args:
        rate (float, req/s): target rate placed in `rates`.

    Returns:
        Dict[str, Any]: ramp block matching `load_ramp_cfg`'s JSON shape.
    """
    return {
        "rates": [rate],
        "min_samples_per_kind": 32,
        "max_probe_window_s": 10.0,
        "cascade": {"mode": "rolling",
                    "threshold": 0.5,
                    "window": 50},
    }


def _stub_client() -> httpx.AsyncClient:
    """*_stub_client()* fresh `httpx.AsyncClient` whose `MockTransport` always responds 404.

    Returns:
        httpx.AsyncClient: caller owns the lifecycle and must `aclose()` at end-of-test.
    """
    async def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=404)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _stub_registry(method_cfg: Dict[str, Any]) -> SvcRegistry:
    """*_stub_registry()* `SvcRegistry` from a method config; standalone (no architecture needed).

    Args:
        method_cfg (Dict[str, Any]): parsed method-config dict.

    Returns:
        SvcRegistry: populated registry.
    """
    return SvcRegistry.from_config(method_cfg)


class TestTasUser:
    """**TestTasUser** boundary contract for `TasUser`: independent constructor, identity borrow of transport / registry, kind-prob round-trip, guard reset on exit, raise before entry, verbatim `run_ramp` delegation, plus one end-to-end ramp through a live `TasArchitecture`."""

    @pytest.mark.asyncio
    async def test_aenter_returns_self(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_aenter_returns_self()* `as user` binds to the constructed `TasUser`; `cfg` and `simulator` populated."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        _user_obj = TasUser(client=_client,
                            registry=_registry,
                            method_cfg=_method_cfg,
                            kind_prob=_KP_SOLO)
        async with _user_obj as _user:
            assert _user is _user_obj
            assert _user.cfg is not None
            assert isinstance(_user.simulator, ClientSimulator)
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_borrows_supplied_transport(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_borrows_supplied_transport()* `simulator.sender.client` and `simulator.sender.registry` are the exact instances passed to the constructor."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        async with TasUser(client=_client,
                           registry=_registry,
                           method_cfg=_method_cfg,
                           kind_prob=_KP_SOLO) as _user:
            assert _user.simulator is not None
            assert _user.simulator.sender.client is _client
            assert _user.simulator.sender.registry is _registry
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_kind_prob_propagates_to_cfg(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_kind_prob_propagates_to_cfg()* `dict(user.cfg.kind_prob) == kind_prob` after entry."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        async with TasUser(client=_client,
                           registry=_registry,
                           method_cfg=_method_cfg,
                           kind_prob=_KP_SOLO) as _user:
            assert _user.cfg is not None
            assert dict(_user.cfg.kind_prob) == _KP_SOLO
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_aexit_resets_guard(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_aexit_resets_guard()* `guard._window` populated to len 2 inside the block is empty after `__aexit__`."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        _user_obj = TasUser(client=_client,
                            registry=_registry,
                            method_cfg=_method_cfg,
                            kind_prob=_KP_SOLO)
        async with _user_obj as _user:
            assert _user.simulator is not None
            _guard = _user.simulator.guard
            _guard._window.append(False)
            _guard._window.append(True)
            assert len(_guard._window) == 2
        assert len(_guard._window) == 0
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_run_ramp_unentered_raises(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_run_ramp_unentered_raises()* `run_ramp()` on a never-entered `TasUser` raises `RuntimeError` matching `"async with"`."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        _user = TasUser(client=_client,
                        registry=_registry,
                        method_cfg=_method_cfg,
                        kind_prob=_KP_SOLO)
        with pytest.raises(RuntimeError, match="async with"):
            await _user.run_ramp()
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_run_ramp_delegates(self, _method_cfg: Dict[str, Any]) -> None:
        """*test_run_ramp_delegates()* with `simulator.run_ramp` patched to return a sentinel, `TasUser.run_ramp()` returns that exact object."""
        _client = _stub_client()
        _registry = _stub_registry(_method_cfg)
        _sentinel: Dict[str, Any] = {"probes": [],
                                     "saturation_rate": None,
                                     "stopped_reason": "schedule_complete",
                                     "client_effective_rate": 0.0}

        async def _fake_run_ramp() -> Dict[str, Any]:
            return _sentinel

        async with TasUser(client=_client,
                           registry=_registry,
                           method_cfg=_method_cfg,
                           kind_prob=_KP_SOLO) as _user:
            assert _user.simulator is not None
            cast(Any, _user.simulator).run_ramp = _fake_run_ramp
            _out = await _user.run_ramp()
            assert _out is _sentinel
        await _client.aclose()

    @pytest.mark.asyncio
    async def test_live_baseline_ramp(
            self,
            _profile_cfg: NetCfg,
            _method_cfg: Dict[str, Any]) -> None:
        """*test_live_baseline_ramp()* a one-rate ramp at lam_entry/10 against a live `TasArchitecture` collects >= 5 records with >= 1 success and `saturation_rate is None`."""
        async with TasArchitecture(cfg=_profile_cfg,
                                   method_cfg=_method_cfg,
                                   adaptation="baseline") as _arch:
            assert _arch.client is not None
            assert _arch.registry is not None
            _rate = _arch.get_lam_z_entry() / 10.0
            _patched_method_cfg = dict(_method_cfg)
            _patched_method_cfg["ramp"] = _tiny_ramp_block(_rate)
            async with TasUser(client=_arch.client,
                               registry=_arch.registry,
                               method_cfg=_patched_method_cfg,
                               kind_prob=dict(_arch.kind_prob)) as _user:
                _result = await _user.run_ramp()
        assert len(_result["probes"]) == 1
        _probe = _result["probes"][0]
        _records = _probe["records"]
        assert len(_records) >= 5
        _succ = sum(1 for _r in _records if _r.success)
        assert _succ >= 1
        assert _result["saturation_rate"] is None
