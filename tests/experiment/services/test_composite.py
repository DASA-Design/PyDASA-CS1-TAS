# -*- coding: utf-8 -*-
"""
Module test_composite.py
========================

Unit tests for `src/experiment/services/composite.py`:

    - **TestMountCompositeService** mount a 2-member composite and assert: distinct `SvcCtx` per member, in-process hop logs one row per member, unknown `req.kind` returns HTTP 400 at the entry `KindPick`.
    - **TestParseConstituentIdx** `_parse_constituent_idx("TAS_{i}") == i` on valid names; raises `ValueError` on anything not matching `^TAS_\\{(\\d+)\\}$`.
"""
# native python modules
from typing import Dict, List, Tuple

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.services import (SvcReq,
                                     SvcResp,
                                     SvcSpec,
                                     make_base_app,
                                     mount_composite_svc)
from src.experiment.services.composite import _parse_constituent_idx

# helper modules
from tests.utils.helpers import _SpecBuilder


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


class _RecordedForward:
    """*_RecordedForward* append `(target, req.req_id)` to `self.calls` and return a `SvcResp(success=True, message="recorded")`. Used as the test-side `ext_fwd` so each test can assert which targets were hit and in what order."""

    def __init__(self, calls: List[Tuple[str, str]]) -> None:
        self.calls = calls

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        self.calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                       srv_name=target,
                       success=True,
                       message="recorded")


class TestMountCompositeService:
    """**TestMountCompositeService** mount + run a 2-member composite (TAS_{1} entry, TAS_{2} forwards to external MAS_{1}) and assert: each member gets its own `SvcCtx` on `app.state.tas_components`, an in-process hop logs one row per member, an unknown `kind` gets HTTP 400 at the entry."""

    def _build_tas_like(self,
                        specs: _SpecBuilder,
                        forward: _RecordedForward) -> FastAPI:
        """*_build_tas_like()* return a FastAPI app with two members mounted: TAS_{1} (entry, routes by `req.kind`) and TAS_{2} (Jackson-routes to MAS_{1} via the supplied `forward`). The `kind_to_tgt` table maps `kind="TAS_{2}"` to TAS_{2}; everything else returns 400 at TAS_{1}."""
        _specs: Dict[str, SvcSpec] = {
            "TAS_{1}": specs(name="TAS_{1}",
                             role="composite_client",
                             port=8001,
                             mu=10_000.0,
                             seed=1),
            "TAS_{2}": specs(name="TAS_{2}",
                             role="composite_medical",
                             port=8001,
                             mu=10_000.0,
                             seed=2),
        }

        _rows: Dict[str, List[Tuple[str, float]]] = {
            "TAS_{1}": [],
            "TAS_{2}": [("MAS_{1}", 1.0)],
        }
        _k2t: Dict[str, str] = {"TAS_{2}": "TAS_{2}"}
        _app = make_base_app("test::TAS")
        mount_composite_svc(_app,
                            _specs,
                            _rows,
                            _k2t,
                            forward,
                            entry_name="TAS_{1}")
        return _app

    @pytest.mark.asyncio
    async def test_distinct_ctx_per_member(self,
                                           specs: _SpecBuilder) -> None:
        """*test_distinct_ctx_per_member()* `app.state.tas_components` has one `SvcCtx` per member name, and `tas_components["TAS_{1}"] is not tas_components["TAS_{2}"]`."""
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(specs, _RecordedForward(_calls))
        _ctxs = _app.state.tas_components
        assert set(_ctxs.keys()) == {"TAS_{1}", "TAS_{2}"}
        assert _ctxs["TAS_{1}"] is not _ctxs["TAS_{2}"]

    @pytest.mark.asyncio
    async def test_in_process_hop_logs_per_member(self,
                                                  specs: _SpecBuilder) -> None:
        """*test_in_process_hop_logs_per_member()* one POST with `kind="TAS_{2}"` produces `len(ctx_TAS_{1}.log) == 1`, `len(ctx_TAS_{2}.log) == 1`, and `recorded_forward.calls == [("MAS_{1}", req.req_id)]`."""
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(specs, _RecordedForward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _ctxs = _app.state.tas_components
        assert len(_ctxs["TAS_{1}"].log) == 1
        assert len(_ctxs["TAS_{2}"].log) == 1
        assert _calls == [("MAS_{1}", _req.req_id)]

    @pytest.mark.asyncio
    async def test_unknown_kind_raises_400(self,
                                           specs: _SpecBuilder) -> None:
        """*test_unknown_kind_raises_400()* a POST with `kind="NOT_A_KIND"` returns HTTP 400 from the entry `KindPick`, and `recorded_forward.calls == []` (the downstream forward is never called)."""
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(specs, _RecordedForward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="NOT_A_KIND", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
        assert _r.status_code == 400
        assert _calls == []


class TestParseConstituentIdx:
    """**TestParseConstituentIdx** extract the numeric index from a `TAS_{i}` artifact key."""

    @pytest.mark.parametrize("_name, _expected",
                             [("TAS_{1}", 1),
                              ("TAS_{2}", 2),
                              ("TAS_{6}", 6),
                              ("TAS_{42}", 42),])
    def test_valid_names(self, _name: str, _expected: int) -> None:
        """*test_valid_names()* `_parse_constituent_idx("TAS_{i}") == i` for i in {1, 2, 6, 42}."""
        assert _parse_constituent_idx(_name) == _expected

    @pytest.mark.parametrize("_bad",
                             ["MAS_{1}",
                              "tas_{1}",
                              "TAS{1}",
                              "TAS_1",
                              "TAS_{a}",
                              "",
                              "foo"])
    def test_non_tas_name_raises(self, _bad: str) -> None:
        """*test_non_tas_name_raises()* `_parse_constituent_idx(s)` for `s` not matching `^TAS_\\{(\\d+)\\}$` raises `ValueError` with `"not a TAS component name"` in the message."""
        with pytest.raises(ValueError, match="not a TAS component name"):
            _parse_constituent_idx(_bad)
