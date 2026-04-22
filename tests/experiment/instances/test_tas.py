# -*- coding: utf-8 -*-
"""
Module test_tas.py
==================

Pins the `build_tas` instance contract: ONE FastAPI app hosting six
embedded atomic members (TAS_{1..6}), each with its own
`ServiceContext` (own CSV log, own seeded RNG). TAS-to-TAS hops are
in-process via a shared handler dict; TAS-to-third-party hops use the
`external_forward` closure. Queueing is emergent; no admission
counters or semaphores are enforced by the apparatus.

    - **TestTasComponentIsolation** each member has its own `ServiceContext` + log; seeded RNGs are distinct per member.
    - **TestInternalRoutingInProcess** kind-based entry dispatch + Jackson-weighted hops stay inside the app and log one row per visited member.
    - **TestExternalForwardOnlyToThirdParty** the `external_forward` closure fires exactly when the routing picks a non-TAS target.
    - **TestPerComponentFlush** `launcher.flush_logs()` writes one CSV per TAS member when there is traffic.
"""
# native python modules
import tempfile
from pathlib import Path
from typing import List, Tuple

# testing framework
import pytest

# web stack
import httpx

# modules under test
from src.experiment.instances import build_tas
from src.experiment.launcher import ExperimentLauncher
from src.experiment.services import (LOG_COLUMNS,
                                     ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec)
from src.io import load_method_config, load_profile


# ---------------------------------------------------------------- helpers


def _tas_spec(name: str, *, mu: float = 1000.0, epsilon: float = 0.0,
              c: int = 1, K: int = 10, seed: int = 1) -> ServiceSpec:
    """*_tas_spec()* build a `ServiceSpec` for a TAS member with stock defaults."""
    return ServiceSpec(name=name, role="composite", port=8001,
                       mu=mu, epsilon=epsilon, c=c, K=K, seed=seed)


async def _no_forward(_target: str, _req: ServiceRequest) -> ServiceResponse:
    """*_no_forward()* fail loudly if invoked; used in tests that must stay in-process."""
    raise AssertionError(f"unexpected external forward to {_target!r}")


def _recorded_forward(_calls: List[Tuple[str, str]]):
    """*_recorded_forward()* forward closure that appends `(target, request_id)` to `_calls` and returns success."""

    async def _fwd(target: str, req: ServiceRequest) -> ServiceResponse:
        _calls.append((target, req.request_id))
        return ServiceResponse(request_id=req.request_id,
                               service_name=target,
                               success=True,
                               message="recorded")

    return _fwd


# ------------------------------------------------------------- fixtures


@pytest.fixture
def _app_internal_only():
    """*_app_internal_only()* a TAS app whose routing keeps traffic inside the app (TAS_{1} -> TAS_{2} -> TAS_{3})."""
    _specs = {
        "TAS_{1}": _tas_spec("TAS_{1}", seed=1),
        "TAS_{2}": _tas_spec("TAS_{2}", seed=2),
        "TAS_{3}": _tas_spec("TAS_{3}", seed=3),
    }
    _rows = {
        "TAS_{1}": [],
        "TAS_{2}": [("TAS_{3}", 1.0)],
        "TAS_{3}": [],
    }
    _k2t = {"TAS_{2}": "TAS_{2}"}
    return build_tas(_specs, _rows, _k2t, _no_forward), _specs


@pytest.fixture
def _app_with_external():
    """*_app_with_external()* a TAS app that forwards externally from TAS_{2} to MAS_{1}."""
    _specs = {
        "TAS_{1}": _tas_spec("TAS_{1}", seed=1),
        "TAS_{2}": _tas_spec("TAS_{2}", seed=2),
    }
    _rows = {
        "TAS_{1}": [],
        "TAS_{2}": [("MAS_{1}", 1.0)],
    }
    _k2t = {"TAS_{2}": "TAS_{2}"}
    _calls: List[Tuple[str, str]] = []
    _fwd = _recorded_forward(_calls)
    return build_tas(_specs, _rows, _k2t, _fwd), _specs, _calls


# --------------------------------------------------------------- classes


class TestTasComponentIsolation:
    """**TestTasComponentIsolation** each TAS member has its own `ServiceContext` + log buffer."""

    def test_app_exposes_per_component_states(self, _app_internal_only):
        """*test_app_exposes_per_component_states()* `app.state.tas_components` has one distinct `ServiceContext` per declared member."""
        _app, _specs = _app_internal_only
        _states = _app.state.tas_components
        assert set(_states.keys()) == set(_specs.keys())
        _ids = {id(_s) for _s in _states.values()}
        assert len(_ids) == len(_specs)

    def test_distinct_seeds_yield_distinct_rngs(self, _app_internal_only):
        """*test_distinct_seeds_yield_distinct_rngs()* different per-member seeds produce different service-time draws."""
        _app, _ = _app_internal_only
        _s1 = _app.state.tas_components["TAS_{1}"]
        _s2 = _app.state.tas_components["TAS_{2}"]
        _draws_1 = [_s1.draw_svc_time() for _ in range(10)]
        _draws_2 = [_s2.draw_svc_time() for _ in range(10)]
        assert _draws_1 != _draws_2


class TestInternalRoutingInProcess:
    """**TestInternalRoutingInProcess** TAS-to-TAS hops never hit the forward closure."""

    @pytest.mark.asyncio
    async def test_request_flows_through_three_tas_components(self, _app_internal_only):
        """*test_request_flows_through_three_tas_components()* one POST at TAS_{1} produces one log row at every visited member."""
        _app, _specs = _app_internal_only
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _c:
            _req = ServiceRequest(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
            assert _r.json()["success"] is True
        _states = _app.state.tas_components
        for _name in ("TAS_{1}", "TAS_{2}", "TAS_{3}"):
            _log = _states[_name].log
            assert len(_log) == 1, f"{_name} log has {len(_log)} rows"
            assert _log[0]["request_id"] == _req.request_id
            assert set(LOG_COLUMNS).issubset(set(_log[0].keys()))


class TestExternalForwardOnlyToThirdParty:
    """**TestExternalForwardOnlyToThirdParty** forward closure fires iff target is NOT a TAS member."""

    @pytest.mark.asyncio
    async def test_forward_called_for_non_tas_target(self, _app_with_external):
        """*test_forward_called_for_non_tas_target()* routing from TAS_{2} to MAS_{1} invokes the closure exactly once."""
        _app, _specs, _calls = _app_with_external
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _c:
            _req = ServiceRequest(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0][0] == "MAS_{1}"


class TestPerComponentFlush:
    """**TestPerComponentFlush** `launcher.flush_logs()` writes one CSV per TAS member when there is traffic."""

    @pytest.mark.asyncio
    async def test_six_tas_csvs_after_baseline_run(self):
        """*test_six_tas_csvs_after_baseline_run()* forcing one row per member produces six `TAS__<i>_.csv` files on flush."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            # force every TAS member's log to have at least one row so
            # the flush path produces distinct per-member files
            _seen = set()
            for _name, _app in _lnc.apps.items():
                if not _name.startswith("TAS_"):
                    continue
                _comp = _app.state.tas_components
                if id(_comp) in _seen:
                    continue
                _seen.add(id(_comp))
                for _n, _s in _comp.items():
                    _s.log.append({_col: 0 for _col in LOG_COLUMNS})

            with tempfile.TemporaryDirectory() as _td:
                _out = Path(_td)
                _counts = _lnc.flush_logs(_out)
                for _i in range(1, 7):
                    _path = _out / f"TAS__{_i}_.csv"
                    assert _path.exists(), f"missing {_path}"
                # every TAS member key shows up in counts with >= 1 row
                for _i in range(1, 7):
                    _key = f"TAS_{{{_i}}}"
                    assert _counts.get(_key, 0) >= 1, f"no rows flushed for {_key}"
