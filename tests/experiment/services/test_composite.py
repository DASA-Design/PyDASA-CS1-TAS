# -*- coding: utf-8 -*-
"""
Module test_composite.py
========================

Unit tests for `src/experiment/services/composite.py`:

    - **TestMountCompositeService** per-member context + internal routing
      between members + external forward boundary.
    - **TestParseTasIdx** extract the numeric index from a `TAS_{i}` key.
"""
# native python modules
from typing import List, Tuple

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.services import (ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec,
                                     make_base_app,
                                     mount_composite_service)
from src.experiment.services.composite import parse_tas_idx


def _recorded_forward(calls: List[Tuple[str, str]]):
    """*_recorded_forward()* external-forward stub that logs `(target, request_id)` and returns success."""
    async def _fwd(target: str, req: ServiceRequest) -> ServiceResponse:
        calls.append((target, req.request_id))
        return ServiceResponse(request_id=req.request_id,
                               service_name=target,
                               success=True,
                               message="recorded")
    return _fwd


class TestMountCompositeService:
    """**TestMountCompositeService** composite module: per-member state + internal routing + external forward boundary."""

    def _build_tas_like(self, *, forward) -> FastAPI:
        """A mini TAS-shaped composite: TAS_{1} kind-routes to TAS_{2}, TAS_{2} to external MAS."""
        _specs = {
            "TAS_{1}": ServiceSpec(name="TAS_{1}", role="composite_client",
                                   port=8001, mu=10_000.0, epsilon=0.0,
                                   c=1, K=10, seed=1),
            "TAS_{2}": ServiceSpec(name="TAS_{2}", role="composite_medical",
                                   port=8001, mu=10_000.0, epsilon=0.0,
                                   c=1, K=10, seed=2),
        }
        _rows = {
            "TAS_{1}": [],
            "TAS_{2}": [("MAS_{1}", 1.0)],
        }
        _k2t = {"TAS_{2}": "TAS_{2}"}
        _app = make_base_app("test::TAS")
        mount_composite_service(_app, _specs, _rows, _k2t,
                                forward,
                                entry_name="TAS_{1}")
        return _app

    @pytest.mark.asyncio
    async def test_each_member_has_its_own_context(self):
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(forward=_recorded_forward(_calls))
        _ctxs = _app.state.tas_components
        assert set(_ctxs.keys()) == {"TAS_{1}", "TAS_{2}"}
        # distinct ServiceContext objects
        assert _ctxs["TAS_{1}"] is not _ctxs["TAS_{2}"]

    @pytest.mark.asyncio
    async def test_in_process_hop_records_one_row_per_member(self):
        """TAS_{1} kind-routes to TAS_{2} in-process; TAS_{2} hits external MAS. Expect 1 row in TAS_{1}'s log and 1 row in TAS_{2}'s log; the external forward is called exactly once."""
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(forward=_recorded_forward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="TAS_{2}", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _ctxs = _app.state.tas_components
        assert len(_ctxs["TAS_{1}"].log) == 1
        assert len(_ctxs["TAS_{2}"].log) == 1
        assert _calls == [("MAS_{1}", _req.request_id)]

    @pytest.mark.asyncio
    async def test_unknown_kind_raises_400_at_entry(self):
        _calls: List[Tuple[str, str]] = []
        _app = self._build_tas_like(forward=_recorded_forward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="NOT_A_KIND", size_bytes=64)
            _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
        # FastAPI surfaces HTTPException(400) from the kind router
        assert _r.status_code == 400
        assert _calls == []


class TestParseTasIdx:
    """**TestParseTasIdx** extract the numeric index from a `TAS_{i}` artifact key."""

    @pytest.mark.parametrize("_name, _expected", [
        ("TAS_{1}", 1),
        ("TAS_{2}", 2),
        ("TAS_{6}", 6),
        ("TAS_{42}", 42),
    ])
    def test_valid_names(self, _name, _expected):
        assert parse_tas_idx(_name) == _expected

    @pytest.mark.parametrize("_bad", [
        "MAS_{1}", "tas_{1}", "TAS{1}", "TAS_1", "TAS_{a}", "", "foo"])
    def test_non_tas_name_raises(self, _bad):
        with pytest.raises(ValueError, match="not a TAS component name"):
            parse_tas_idx(_bad)
