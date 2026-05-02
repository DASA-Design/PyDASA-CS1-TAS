# -*- coding: utf-8 -*-
"""
Module test_vernier.py
======================

Unit tests for `src/experiment/services/vernier.py`:

    - **TestVernierSvc** mount + `/invoke` POST + terminal response + one log row per call + payload round-trip + Bernoulli row + concurrency cap + service-time floor + drop-count clean.
    - **TestVernierKGate** rejects with HTTP 503 once `in_flight >= K`, releases the counter on every exit path, and disables the gate when `spec.K <= 0`.
"""
# native python modules
import asyncio
from typing import Any, Dict

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.wire import generate_payload
from src.experiment.services import (LOG_COLUMNS,
                                     SvcReq,
                                     SvcSpec,
                                     make_base_app,
                                     mount_vernier_svc)

# helper modules
from tests.utils.helpers import _SpecBuilder


_QUICK_SAMPLES = 20


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


def _make_app(spec: SvcSpec, payload_size_bytes: int = 0) -> FastAPI:
    """*_make_app()* return a FastAPI app with a `VernierHandler` mounted at `/invoke` and a `/healthz` GET that echoes `spec.name`."""
    _app = make_base_app(f"test::{spec.name}",
                         healthz_fn=lambda: {"name": spec.name})
    mount_vernier_svc(_app, spec, payload_size_bytes=payload_size_bytes)
    return _app


def _req_with_payload(size_bytes: int) -> Dict[str, Any]:
    """*_req_with_payload()* return the `model_dump()` of a `SvcReq(kind="ping", size_bytes=N)` whose `payload["blob"]` is exactly `N` ASCII bytes."""
    _payload = generate_payload(kind="ping", size_bytes=size_bytes)
    _req = SvcReq(kind="ping",
                  size_bytes=size_bytes,
                  payload=_payload.to_dict())
    return _req.model_dump()


class TestVernierSvc:
    """**TestVernierSvc** mount + run a single-vernier app and assert: route shape, terminal response body, one log row per call, payload round-trip, Bernoulli rows, concurrency cap, service-time floor, drop count."""

    @pytest.mark.asyncio
    async def test_mount_returns_ctx(self, specs: _SpecBuilder) -> None:
        """*test_mount_returns_ctx()* `app.state.ctx` is a `SvcCtx` whose `spec.name == "CALIB"` and whose `handler` is a callable (the bound `VernierHandler` instance)."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _app = _make_app(_s)
        _ctx = _app.state.ctx
        assert _ctx.spec.name == "CALIB"
        assert _ctx.handler is not None
        assert callable(_ctx.handler)

    @pytest.mark.asyncio
    async def test_route_is_post_invoke(self, specs: _SpecBuilder) -> None:
        """*test_route_is_post_invoke()* user-facing routes are exactly `POST /invoke` and `GET /healthz`; FastAPI's auto-routes (`/openapi.json`, `/docs`, `/redoc`, `/docs/oauth2-redirect`) are filtered out before the assertion."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _app = _make_app(_s)
        _user_paths_post = []
        _user_paths_get = []
        _fastapi_internal = {"/openapi.json", "/docs",
                             "/docs/oauth2-redirect", "/redoc"}
        for _r in _app.routes:
            _methods = getattr(_r, "methods", None) or set()
            _path = getattr(_r, "path", "")
            if _path in _fastapi_internal:
                continue
            if "POST" in _methods:
                _user_paths_post.append(_path)
            if "GET" in _methods:
                _user_paths_get.append(_path)
        assert _user_paths_post == ["/invoke"]
        assert _user_paths_get == ["/healthz"]

    @pytest.mark.asyncio
    async def test_terminal_response_ok(self, specs: _SpecBuilder) -> None:
        """*test_terminal_response_ok()* one POST with a 128-byte payload returns HTTP 200 with `body.success is True`, `body.srv_name == "CALIB"`, and `body.message.startswith("terminal")`."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _app = _make_app(_s, payload_size_bytes=128)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.post("/invoke", json=_req_with_payload(128))
        assert _r.status_code == 200
        _b = _r.json()
        assert _b["success"] is True
        assert _b["srv_name"] == "CALIB"
        assert _b["message"].startswith("terminal")

    @pytest.mark.asyncio
    async def test_one_row_per_call(self, specs: _SpecBuilder) -> None:
        """*test_one_row_per_call()* after `_QUICK_SAMPLES` POSTs, `len(ctx.log) == _QUICK_SAMPLES`, every row's keys are a superset of `LOG_COLUMNS`, and every row's `srv_name == "CALIB"`."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(_QUICK_SAMPLES):
                await _c.post("/invoke", json=_req_with_payload(64))
        _ctx = _app.state.ctx
        assert len(_ctx.log) == _QUICK_SAMPLES
        for _row in _ctx.log:
            for _k in LOG_COLUMNS:
                assert _k in _row, f"missing column {_k!r}"
            assert _row["srv_name"] == "CALIB"

    @pytest.mark.asyncio
    async def test_payload_round_trips(self, specs: _SpecBuilder) -> None:
        """*test_payload_round_trips()* the response message contains both `size_bytes=256` (length the handler observed) and `declared=256` (length passed at mount), proving the request body is read end-to-end before the response is built."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _size = 256
        _app = _make_app(_s, payload_size_bytes=_size)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.post("/invoke", json=_req_with_payload(_size))
        _msg = _r.json()["message"]
        assert f"size_bytes={_size}" in _msg
        assert f"declared={_size}" in _msg

    @pytest.mark.asyncio
    async def test_bernoulli_failure_row(self, specs: _SpecBuilder) -> None:
        """*test_bernoulli_failure_row()* with `epsilon=1.0`, every POST returns HTTP 200 with `body.success is False` and `body.message == "bernoulli failure"`, and every CSV row has `success is False`."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50, epsilon=1.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(_QUICK_SAMPLES):
                _r = await _c.post("/invoke", json=_req_with_payload(64))
                _b = _r.json()
                assert _b["success"] is False
                assert _b["message"] == "bernoulli failure"
        _ctx = _app.state.ctx
        for _row in _ctx.log:
            assert _row["success"] is False

    @pytest.mark.asyncio
    async def test_admission_gate_caps_concurrency(self, specs: _SpecBuilder) -> None:
        """*test_admission_gate_caps_concurrency()* with `c=2` and 8 requests fired in parallel, `max(row["c_used_at_start"] for row in ctx.log) <= 2` (the c-permit semaphore never lets more than 2 calls hold a permit at once)."""
        _s = specs(name="CALIB", port=8765, K=50, c=2, mu=200.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=_req_with_payload(64)))
                for _ in range(8)]
            await asyncio.gather(*_tasks)
        _ctx = _app.state.ctx
        _max_c = max(_row["c_used_at_start"] for _row in _ctx.log)
        assert _max_c <= 2, f"c_used_at_start exceeded c=2: {_max_c}"

    @pytest.mark.asyncio
    async def test_mu_lower_bounds_W(self, specs: _SpecBuilder) -> None:
        """*test_mu_lower_bounds_W()* with `mu=200` (expected service time 5 ms), the mean of `end_ts - start_ts` across `_QUICK_SAMPLES` rows is at least 1 ms; the floor is loose to absorb Windows scheduler jitter."""
        _s = specs(name="CALIB", port=8765, K=50, mu=200.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(_QUICK_SAMPLES):
                await _c.post("/invoke", json=_req_with_payload(64))
        _ctx = _app.state.ctx
        _service_times = [_row["end_ts"] - _row["start_ts"]
                          for _row in _ctx.log]
        _mean = sum(_service_times) / len(_service_times)
        assert _mean >= 1e-3, f"mean svc time {_mean * 1e3:.2f} ms below 1 ms floor"

    @pytest.mark.asyncio
    async def test_drop_count_zero(self, specs: _SpecBuilder) -> None:
        """*test_drop_count_zero()* after `_QUICK_SAMPLES` calls (well below `ctx.log_maxlen`), `ctx.dropped_count == 0` (the bounded log buffer never overflowed)."""
        _s = specs(name="CALIB", port=8765, mu=0.0, K=50)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(_QUICK_SAMPLES):
                await _c.post("/invoke", json=_req_with_payload(64))
        _ctx = _app.state.ctx
        assert _ctx.dropped_count == 0


class TestVernierKGate:
    """**TestVernierKGate** push concurrent load past `K` and assert: HTTP 503 returned at capacity, the in-flight counter releases on every exit path, the CSV records the rejection, and `K=0` disables the gate entirely."""

    @pytest.mark.asyncio
    async def test_503_at_K_capacity(self, specs: _SpecBuilder) -> None:
        """*test_503_at_K_capacity()* with `c=1, K=3, mu=20.0` and 12 concurrent POSTs, at least 9 responses have status 503 and `ctx.in_flight == 0` after `gather` returns."""
        _s = specs(name="CALIB", port=8765, c=1, K=3, mu=20.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=_req_with_payload(64)))
                for _ in range(12)]
            _responses = await asyncio.gather(*_tasks)
        _codes = [_r.status_code for _r in _responses]
        assert sum(1 for _x in _codes if _x == 503) >= 9
        assert _app.state.ctx.in_flight == 0

    @pytest.mark.asyncio
    async def test_503_logged_as_failure(self, specs: _SpecBuilder) -> None:
        """*test_503_logged_as_failure()* with `c=1, K=2, mu=20.0` and 8 concurrent POSTs, at least 6 CSV rows have `status_code == 503`, and every such row has `success is False` and `srv_name == spec.name`."""
        _s = specs(name="CALIB", port=8765, c=1, K=2, mu=20.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=_req_with_payload(64)))
                for _ in range(8)]
            await asyncio.gather(*_tasks)
        _rows = list(_app.state.ctx.log)
        _503_rows = [_r for _r in _rows if _r["status_code"] == 503]
        assert len(_503_rows) >= 6
        for _r in _503_rows:
            assert _r["success"] is False
            assert _r["srv_name"] == _s.name

    @pytest.mark.asyncio
    async def test_K_zero_skips(self, specs: _SpecBuilder) -> None:
        """*test_K_zero_skips()* with `K=0` (gate disabled) and 20 concurrent POSTs, every response has status 200 and `ctx.in_flight == 0` after `gather` returns."""
        _s = specs(name="CALIB", port=8765, K=0, mu=0.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            _tasks = [asyncio.create_task(
                _c.post("/invoke", json=_req_with_payload(64)))
                for _ in range(20)]
            _responses = await asyncio.gather(*_tasks)
        assert all(_r.status_code == 200 for _r in _responses)
        assert _app.state.ctx.in_flight == 0

    @pytest.mark.asyncio
    async def test_K_releases_after_success(self, specs: _SpecBuilder) -> None:
        """*test_K_releases_after_success()* after 5 sequential POSTs that all return 200, `ctx.in_flight == 0`."""
        _s = specs(name="CALIB", port=8765, c=1, K=4, mu=10000.0)
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t",
                                     timeout=10.0) as _c:
            for _ in range(5):
                _r = await _c.post("/invoke", json=_req_with_payload(64))
                assert _r.status_code == 200
        assert _app.state.ctx.in_flight == 0
