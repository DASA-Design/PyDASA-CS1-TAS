# -*- coding: utf-8 -*-
"""
Module test_atomic.py
=====================

Unit tests for `src/experiment/services/atomic.py`:

    - **TestMountAtomicService** healthz + terminal path + ε=1 business failure + non-terminal single-target forward.
    - **TestAtomicKGate** K-bounded admission gate produces 503 at capacity, releases on every exit path, and disables when `spec.K<=0`.
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
from src.experiment.services import (SvcReq,
                                     SvcResp,
                                     SvcSpec,
                                     make_base_app,
                                     mount_atomic_svc)


def _spec(**kwargs) -> SvcSpec:
    """*_spec()* build a SvcSpec with sensible defaults; override via kwargs."""
    _defaults = dict(name="MAS_{1}", role="atomic", port=8006,
                     mu=1000.0, epsilon=0.0, c=1, K=10, seed=42)
    _defaults.update(kwargs)
    return SvcSpec(**_defaults)


async def _noop_forward(_target: str, _req: SvcReq) -> SvcResp:
    """*_noop_forward()* asserts the external-forward hook never fires (used for terminal services)."""
    raise AssertionError(
        f"terminal service must not forward; target={_target!r}")


def _recorded_forward(calls: List[Tuple[str, str]]):
    """*_recorded_forward()* external-forward stub that logs `(target, request_id)` and returns success."""
    async def _fwd(target: str, req: SvcReq) -> SvcResp:
        calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                               srv_name=target,
                               success=True,
                               message="recorded")
    return _fwd


class TestMountAtomicService:
    """**TestMountAtomicService** atomic-service module: healthz, terminal path, ε=1 business failure."""

    def _make_app(self, spec: SvcSpec,
                  targets=None, forward=None) -> FastAPI:
        _app = make_base_app(f"test::{spec.name}",
                             healthz_fn=lambda: {"name": spec.name,
                                                 "role": spec.role,
                                                 "c": spec.c, "K": spec.K})
        mount_atomic_svc(_app, spec,
                             targets or [],
                             forward or _noop_forward)
        return _app

    @pytest.mark.asyncio
    async def test_terminal_returns_success_and_logs_one_row(self):
        """*test_terminal_returns_success_and_logs_one_row()* an atomic with no outbound targets returns `success=True / message="terminal"` and appends exactly one log row."""
        _s = _spec()
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is True
        assert _body["message"] == "terminal"
        assert len(_app.state.ctx.log) == 1
        assert _app.state.ctx.log[0]["req_id"] == _req.req_id

    @pytest.mark.asyncio
    async def test_epsilon_one_always_business_fails(self):
        """*test_epsilon_one_always_business_fails()* `epsilon=1.0` forces every call to return HTTP 200 with `body.success=False / message="bernoulli failure"`."""
        _s = _spec(epsilon=1.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=SvcReq().model_dump()))
                for _ in range(5)]
            _responses = await asyncio.gather(*_tasks)
        for _r in _responses:
            assert _r.status_code == 200
            _b = _r.json()
            assert _b["success"] is False
            assert _b["message"] == "bernoulli failure"

    @pytest.mark.asyncio
    async def test_epsilon_zero_never_fails(self):
        """*test_epsilon_zero_never_fails()* `epsilon=0.0` makes every response succeed; run 20 calls to confirm the Bernoulli never fires at the floor. Concurrency stays under K (gate-disabled via K=0) so the test isolates epsilon behaviour from admission rejection."""
        _s = _spec(epsilon=0.0, K=0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=SvcReq().model_dump()))
                for _ in range(20)]
            _responses = await asyncio.gather(*_tasks)
        assert all(_r.json()["success"] for _r in _responses)

    @pytest.mark.asyncio
    async def test_K_zero_skips_gate(self):
        """*test_K_zero_skips_gate()* `spec.K=0` disables the gate; every concurrent call gets through (no 503)."""
        _s = _spec(K=0, mu=0.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=SvcReq().model_dump()))
                for _ in range(20)]
            _responses = await asyncio.gather(*_tasks)
        assert all(_r.status_code == 200 for _r in _responses)

    @pytest.mark.asyncio
    async def test_K_release_after_response(self):
        """*test_K_release_after_response()* in_flight returns to 0 after every successful completion."""
        _s = _spec(K=4, mu=10000.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(5):
                _r = await _c.post("/invoke", json=SvcReq().model_dump())
                assert _r.status_code == 200
        assert _app.state.ctx.in_flight == 0

    @pytest.mark.asyncio
    async def test_non_terminal_forwards_to_single_target(self):
        """*test_non_terminal_forwards_to_single_target()* a non-empty routing row of one `(target, weight=1.0)` pair forwards exactly one call to that target via `external_forward`."""
        _s = _spec()
        _calls: List[Tuple[str, str]] = []
        _app = self._make_app(_s,
                              targets=[("TAS_{4}", 1.0)],
                              forward=_recorded_forward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert _calls == [("TAS_{4}", _req.req_id)]


class TestAtomicKGate:
    """**TestAtomicKGate** K-bounded admission rejects with HTTP 503 once `in_flight >= K`; counter releases on every exit path; CSV records the rejection."""

    def _make_app(self, spec: SvcSpec) -> FastAPI:
        _app = make_base_app(f"test::{spec.name}",
                             healthz_fn=lambda: {"name": spec.name})
        mount_atomic_svc(_app, spec, [], _noop_forward)
        return _app

    @pytest.mark.asyncio
    async def test_returns_503_when_in_flight_exceeds_K(self):
        """*test_returns_503_when_in_flight_exceeds_K()* fire 12 concurrent requests at a slow service with c=1, K=3 -> at least 9 see HTTP 503; counter respects K."""
        _s = _spec(c=1, K=3, mu=20.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=SvcReq().model_dump()))
                for _ in range(12)]
            _responses = await asyncio.gather(*_tasks)
        _codes = [_r.status_code for _r in _responses]
        _503 = sum(1 for _x in _codes if _x == 503)
        _200 = sum(1 for _x in _codes if _x == 200)
        assert _503 >= 9
        assert _200 <= 3
        assert _app.state.ctx.in_flight == 0

    @pytest.mark.asyncio
    async def test_csv_row_records_503_status(self):
        """*test_csv_row_records_503_status()* every rejected request lands one CSV row with `status_code=503` and `success=False`."""
        _s = _spec(c=1, K=2, mu=20.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=SvcReq().model_dump()))
                for _ in range(8)]
            await asyncio.gather(*_tasks)
        _rows = list(_app.state.ctx.log)
        _503_rows = [_r for _r in _rows if _r["status_code"] == 503]
        assert len(_503_rows) >= 6
        for _r in _503_rows:
            assert _r["success"] is False
            assert _r["srv_name"] == _s.name

    @pytest.mark.asyncio
    async def test_K_release_after_handler_exception(self):
        """*test_K_release_after_handler_exception()* downstream forward raises -> `in_flight` still decrements via the finally branch."""
        async def _raising_forward(_t: str, _req: SvcReq) -> SvcResp:
            raise httpx.HTTPError("simulated downstream failure")

        _s = _spec(c=2, K=4, mu=2000.0)
        _app = make_base_app(f"test::{_s.name}",
                             healthz_fn=lambda: {"name": _s.name})
        mount_atomic_svc(_app, _s, [("DOWNSTREAM", 1.0)], _raising_forward)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            for _ in range(5):
                try:
                    await _c.post("/invoke", json=SvcReq().model_dump())
                except Exception:
                    pass
        assert _app.state.ctx.in_flight == 0
