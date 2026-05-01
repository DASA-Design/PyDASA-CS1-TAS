# -*- coding: utf-8 -*-
"""
Module test_atomic.py
=====================

Unit tests for `src/experiment/services/atomic.py`:

    - **TestMountAtomicService** healthz + terminal path + ε=1 business failure + non-terminal single-target forward.
    - **TestAtomicKGate** K-bounded admission gate produces 503 at capacity, releases on every exit path, and disables when `specs.K<=0`.
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
from src.experiment.services.atomic import mount_atomic_svc
from src.experiment.services.base import (SvcReq,
                                          SvcResp,
                                          SvcSpec,
                                          make_base_app)

# helper modules
from tests.utils.helpers import _SpecBuilder


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


async def _noop_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_noop_forward()* assert the external-forward hook never fires (used for terminal services)."""
    raise AssertionError(
        f"terminal service must not forward; target={_tgt!r}")


async def _raising_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_raising_forward()* always raise `httpx.HTTPError` to simulate a downstream failure (used to verify the K counter releases on the exception path)."""
    raise httpx.HTTPError("simulated downstream failure")


class _RecordedForward:
    """*_RecordedForward* append `(target, req.req_id)` to `self.calls` and return `SvcResp(success=True, message="recorded")`. Used as the test-side `ext_fwd` so each test can assert which targets the handler tried to forward to and in what order."""

    def __init__(self, calls: List[Tuple[str, str]]) -> None:
        self.calls = calls

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        self.calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                       srv_name=target,
                       success=True,
                       message="recorded")


class TestMountAtomicService:
    """**TestMountAtomicService** atomic-service module: healthz, terminal path, ε=1 business failure."""

    def _make_app(self, specs: SvcSpec,
                  targets=None, forward=None) -> FastAPI:
        _app = make_base_app(f"test::{specs.name}",
                             healthz_fn=lambda: {"name": specs.name,
                                                 "role": specs.role,
                                                 "c": specs.c,
                                                 "K": specs.K})
        mount_atomic_svc(_app, specs,
                         targets or [],
                         forward or _noop_forward)
        return _app

    @pytest.mark.asyncio
    async def test_terminal_success_row(self, specs: _SpecBuilder) -> None:
        """*test_terminal_success_row()* an atomic with no outbound targets returns `success=True / message="terminal"` and appends exactly one log row."""
        _s = specs()
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
    async def test_epsilon_one_fails(self, specs: _SpecBuilder) -> None:
        """*test_epsilon_one_fails()* `epsilon=1.0` forces every call to return HTTP 200 with `body.success=False / message="bernoulli failure"`."""
        _s = specs(epsilon=1.0)
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
    async def test_epsilon_zero_succeeds(self, specs: _SpecBuilder) -> None:
        """*test_epsilon_zero_succeeds()* `epsilon=0.0` makes every response succeed; run 20 calls to confirm the Bernoulli never fires at the floor. K=0 disables admission so the test isolates epsilon behaviour."""
        _s = specs(epsilon=0.0, K=0)
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
    async def test_K_zero_skips(self, specs: _SpecBuilder) -> None:
        """*test_K_zero_skips()* `specs.K=0` disables the gate; every concurrent call gets through (no 503)."""
        _s = specs(K=0, mu=0.0)
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
    async def test_K_releases_after_success(self, specs: _SpecBuilder) -> None:
        """*test_K_releases_after_success()* `in_flight` returns to 0 after every successful completion."""
        _s = specs(K=4, mu=10000.0)
        _app = self._make_app(_s)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(5):
                _r = await _c.post("/invoke", json=SvcReq().model_dump())
                assert _r.status_code == 200
        assert _app.state.ctx.in_flight == 0

    @pytest.mark.asyncio
    async def test_forwards_single_target(self, specs: _SpecBuilder) -> None:
        """*test_forwards_single_target()* a non-empty routing row of one `(target, weight=1.0)` pair forwards exactly one call to that target via the external forward."""
        _s = specs()
        _calls: List[Tuple[str, str]] = []
        _app = self._make_app(_s,
                              targets=[("TAS_{4}", 1.0)],
                              forward=_RecordedForward(_calls))
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert _calls == [("TAS_{4}", _req.req_id)]


class TestAtomicKGate:
    """**TestAtomicKGate** K-bounded admission rejects with HTTP 503 once `in_flight >= K`; counter releases on every exit path; CSV records the rejection."""

    def _make_app(self, specs: SvcSpec) -> FastAPI:
        _app = make_base_app(f"test::{specs.name}",
                             healthz_fn=lambda: {"name": specs.name})
        mount_atomic_svc(_app, specs, [], _noop_forward)
        return _app

    @pytest.mark.asyncio
    async def test_503_at_K_capacity(self, specs: _SpecBuilder) -> None:
        """*test_503_at_K_capacity()* fire 12 concurrent requests at a slow service with c=1, K=3 -> at least 9 see HTTP 503; counter respects K."""
        _s = specs(c=1, K=3, mu=20.0)
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
    async def test_503_logged_as_failure(self, specs: _SpecBuilder) -> None:
        """*test_503_logged_as_failure()* every rejected request lands one CSV row with `status_code=503` and `success=False`."""
        _s = specs(c=1, K=2, mu=20.0)
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
    async def test_K_releases_on_exception(self, specs: _SpecBuilder) -> None:
        """*test_K_releases_on_exception()* downstream forward raises -> `in_flight` still decrements via the finally branch."""
        _s = specs(c=2, K=4, mu=2000.0)
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
