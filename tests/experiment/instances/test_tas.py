# -*- coding: utf-8 -*-
"""
Module test_tas.py
==================

Pin the `build_tas` instance contract: ONE FastAPI app hosting six embedded atomic members (TAS_{1..6}), each with its own `SvcCtx` (own CSV log, own seeded RNG). TAS-to-TAS hops are in-process via a shared handler dict; TAS-to-third-party hops use `ext_fwd`. Queueing is emergent; no admission counters or semaphores are enforced by the apparatus itself.

    - **TestTasComponentIsolation** each member has its own `SvcCtx` + log; seeded RNGs are distinct per member.
    - **TestInternalRoutingInProcess** kind-based entry dispatch + Jackson-weighted hops stay inside the app and log one row per visited member.
    - **TestExternalForward** `ext_fwd` is invoked exactly when the routing picks a non-TAS target.
    - **TestPerComponentFlush** `launcher.flush_logs()` writes one CSV per TAS member when there is traffic.
"""
# native python modules
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.instances import build_tas
from src.experiment.launcher import ExperimentLauncher
from src.experiment.services import (LOG_COLUMNS,
                                     SvcReq,
                                     SvcResp,
                                     SvcSpec)
from src.io import load_method_cfg, load_profile

# helper modules
from tests.utils.helpers import _SpecBuilder


# ---------------------------------------------------------------- helpers


async def _no_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_no_forward()* fail loudly when the test path calls it; used for in-process-only paths."""
    raise AssertionError(f"unexpected external forward to {_tgt!r}")


class _RecordedForward:
    """*_RecordedForward* append `(target, req.req_id)` to `self.calls` and return `SvcResp(success=True, message="recorded")`. Used as the test-side `ext_fwd` so each test can assert which non-TAS targets were forwarded to."""

    def __init__(self, calls: List[Tuple[str, str]]) -> None:
        self.calls = calls

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        self.calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                       srv_name=target,
                       success=True,
                       message="recorded")


# ------------------------------------------------------------- fixtures


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


@pytest.fixture
def _app_internal_only(specs: _SpecBuilder) -> Tuple[FastAPI, Dict[str, SvcSpec]]:
    """*_app_internal_only()* return a `(app, specs_dict)` pair for a 3-member TAS where TAS_{1} kind-routes to TAS_{2} and TAS_{2} Jackson-routes to TAS_{3}, so traffic never leaves the app."""
    _specs: Dict[str, SvcSpec] = {
        "TAS_{1}": specs(name="TAS_{1}", role="composite", port=8001, seed=1),
        "TAS_{2}": specs(name="TAS_{2}", role="composite", port=8001, seed=2),
        "TAS_{3}": specs(name="TAS_{3}", role="composite", port=8001, seed=3),
    }
    _rows: Dict[str, List[Tuple[str, float]]] = {
        "TAS_{1}": [],
        "TAS_{2}": [("TAS_{3}", 1.0)],
        "TAS_{3}": [],
    }
    _k2t: Dict[str, str] = {"TAS_{2}": "TAS_{2}"}
    return build_tas(_specs, _rows, _k2t, _no_forward), _specs


@pytest.fixture
def _app_with_external(specs: _SpecBuilder) -> Tuple[FastAPI,
                                                     Dict[str, SvcSpec],
                                                     List[Tuple[str, str]]]:
    """*_app_with_external()* return an `(app, specs_dict, calls)` triple for a 2-member TAS where TAS_{2} forwards to MAS_{1} via a `_RecordedForward(calls)`."""
    _specs: Dict[str, SvcSpec] = {
        "TAS_{1}": specs(name="TAS_{1}", role="composite", port=8001, seed=1),
        "TAS_{2}": specs(name="TAS_{2}", role="composite", port=8001, seed=2),
    }
    _rows: Dict[str, List[Tuple[str, float]]] = {
        "TAS_{1}": [],
        "TAS_{2}": [("MAS_{1}", 1.0)],
    }
    _k2t: Dict[str, str] = {"TAS_{2}": "TAS_{2}"}
    _calls: List[Tuple[str, str]] = []
    _fwd = _RecordedForward(_calls)
    return build_tas(_specs, _rows, _k2t, _fwd), _specs, _calls


# --------------------------------------------------------------- classes


class TestTasComponentIsolation:
    """**TestTasComponentIsolation** each TAS member has its own `SvcCtx` and the seeded RNGs draw distinct values."""

    def test_per_member_ctx(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_per_member_ctx()* `set(app.state.tas_components.keys()) == set(specs.keys())` and the values are distinct objects (`len({id(s) for s in tas_components.values()}) == len(specs)`)."""
        _app, _specs = _app_internal_only
        _states = _app.state.tas_components
        assert set(_states.keys()) == set(_specs.keys())
        _ids = {id(_s) for _s in _states.values()}
        assert len(_ids) == len(_specs)

    def test_distinct_rngs(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_distinct_rngs()* `[ctx_TAS_{1}.draw_svc_time() for _ in range(10)] != [ctx_TAS_{2}.draw_svc_time() for _ in range(10)]` (different seeds produce different draw sequences)."""
        _app, _ = _app_internal_only
        _s1 = _app.state.tas_components["TAS_{1}"]
        _s2 = _app.state.tas_components["TAS_{2}"]
        _draws_1 = [_s1.draw_svc_time() for _ in range(10)]
        _draws_2 = [_s2.draw_svc_time() for _ in range(10)]
        assert _draws_1 != _draws_2


class TestInternalRoutingInProcess:
    """**TestInternalRoutingInProcess** TAS-to-TAS hops never reach `ext_fwd`."""

    @pytest.mark.asyncio
    async def test_three_hop_chain(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_three_hop_chain()* one POST at `/TAS_1/invoke` with `kind="TAS_{2}"` produces `len(ctx[name].log) == 1` for `name in ("TAS_{1}", "TAS_{2}", "TAS_{3}")`, every row has the same `req_id`, and every row's keys are a superset of `LOG_COLUMNS`."""
        _app, _ = _app_internal_only
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _c:
            _req = SvcReq(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
            assert _r.json()["success"] is True
        _states = _app.state.tas_components
        for _name in ("TAS_{1}", "TAS_{2}", "TAS_{3}"):
            _log = _states[_name].log
            assert len(_log) == 1, f"{_name} log has {len(_log)} rows"
            assert _log[0]["req_id"] == _req.req_id
            assert set(LOG_COLUMNS).issubset(set(_log[0].keys()))


class TestExternalForward:
    """**TestExternalForward** `ext_fwd` fires iff the routing picks a non-TAS target."""

    @pytest.mark.asyncio
    async def test_forward_called_for_external(self, _app_with_external: Tuple[FastAPI, Dict[str, SvcSpec], List[Tuple[str, str]]]) -> None:
        """*test_forward_called_for_external()* one POST that routes TAS_{1} -> TAS_{2} -> MAS_{1} produces `len(calls) == 1` and `calls[0][0] == "MAS_{1}"`."""
        _app, _, _calls = _app_with_external
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _c:
            _req = SvcReq(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0][0] == "MAS_{1}"


class TestPerComponentFlush:
    """**TestPerComponentFlush** `launcher.flush_logs()` writes one CSV per TAS member with traffic."""

    @pytest.mark.asyncio
    async def test_per_member_csv_on_flush(self) -> None:
        """*test_per_member_csv_on_flush()* after seeding one log row per TAS member and calling `_lnc.flush_logs(out_dir)`, every `out_dir / f"TAS__{i}_.csv"` for i in 1..6 exists, and `_counts[f"TAS_{{{i}}}"] >= 1` for the same range."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            # force every TAS member's log to have at least one row so the flush path produces distinct per-member files
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
                for _i in range(1, 7):
                    _key = f"TAS_{{{_i}}}"
                    assert _counts.get(_key, 0) >= 1, f"no rows flushed for {_key}"
