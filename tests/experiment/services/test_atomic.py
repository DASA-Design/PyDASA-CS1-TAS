# -*- coding: utf-8 -*-
"""
Module test_atomic.py
=====================

Unit tests for `src/experiment/services/atomic.py`:

    - **TestMountAtomicService** healthz + terminal path + ε=1 business failure + non-terminal single-target forward.
"""
# native python modules
import asyncio
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
                                     mount_atomic_service)


def _spec(**kwargs) -> ServiceSpec:
    """*_spec()* build a ServiceSpec with sensible defaults; override via kwargs."""
    _defaults = dict(name="MAS_{1}", role="atomic", port=8006,
                     mu=1000.0, epsilon=0.0, c=1, K=10, seed=42)
    _defaults.update(kwargs)
    return ServiceSpec(**_defaults)


async def _noop_forward(_target: str, _req: ServiceRequest) -> ServiceResponse:
    """*_noop_forward()* asserts the external-forward hook never fires (used for terminal services)."""
    raise AssertionError(
        f"terminal service must not forward; target={_target!r}")


def _recorded_forward(calls: List[Tuple[str, str]]):
    """*_recorded_forward()* external-forward stub that logs `(target, request_id)` and returns success."""
    async def _fwd(target: str, req: ServiceRequest) -> ServiceResponse:
        calls.append((target, req.request_id))
        return ServiceResponse(request_id=req.request_id,
                               service_name=target,
                               success=True,
                               message="recorded")
    return _fwd


class TestMountAtomicService:
    """**TestMountAtomicService** atomic-service module: healthz, terminal path, ε=1 business failure."""

    def _make_app(self, spec: ServiceSpec,
                  targets=None, forward=None) -> FastAPI:
        _app = make_base_app(f"test::{spec.name}",
                             healthz_fn=lambda: {"name": spec.name,
                                                 "role": spec.role,
                                                 "c": spec.c, "K": spec.K})
        mount_atomic_service(_app, spec,
                             targets or [],
                             forward or _noop_forward)
        return _app

    @pytest.mark.asyncio
    async def test_terminal_returns_success_and_logs_one_row(self):
        _s = _spec()
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is True
        assert _body["message"] == "terminal"
        assert len(_app.state.ctx.log) == 1
        assert _app.state.ctx.log[0]["request_id"] == _req.request_id

    @pytest.mark.asyncio
    async def test_epsilon_one_always_business_fails(self):
        _s = _spec(epsilon=1.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=ServiceRequest().model_dump()))
                for _ in range(5)]
            _responses = await asyncio.gather(*_tasks)
        for _r in _responses:
            assert _r.status_code == 200
            _b = _r.json()
            assert _b["success"] is False
            assert _b["message"] == "bernoulli failure"

    @pytest.mark.asyncio
    async def test_epsilon_zero_never_fails(self):
        _s = _spec(epsilon=0.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=ServiceRequest().model_dump()))
                for _ in range(20)]
            _responses = await asyncio.gather(*_tasks)
        assert all(_r.json()["success"] for _r in _responses)

    @pytest.mark.asyncio
    async def test_non_terminal_forwards_to_single_target(self):
        _s = _spec()
        _calls: List[Tuple[str, str]] = []
        _app = self._make_app(_s,
                              targets=[("TAS_{4}", 1.0)],
                              forward=_recorded_forward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert _calls == [("TAS_{4}", _req.request_id)]
