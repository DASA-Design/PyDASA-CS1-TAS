# -*- coding: utf-8 -*-
"""
Module test_vernier.py
======================

Unit tests for `src/experiment/services/vernier.py`:

    - **TestVernierSvc** mount + route + terminal response + logger row writing + payload end-to-end read + Bernoulli epsilon + admission gate + mu service-time floor + drop-count zero on normal load.
"""
# native python modules
import asyncio

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# data types
from typing import Any, Dict

# modules under test
from src.experiment.payload import generate_payload
from src.experiment.services import (LOG_COLUMNS,
                                     SvcReq,
                                     SvcSpec,
                                     make_base_app,
                                     mount_vernier_svc)


_QUICK_SAMPLES = 20


def _spec(**kwargs: Any) -> SvcSpec:
    """*_spec()* build a SvcSpec with calibration defaults; override via kwargs."""
    _defaults = dict(name="CALIB", role="atomic", port=8765,
                     mu=0.0, epsilon=0.0, c=1, K=50, seed=42,
                     mem_per_buffer=0)
    _defaults.update(kwargs)
    return SvcSpec(**_defaults)


def _make_app(spec: SvcSpec, payload_size_bytes: int = 0) -> FastAPI:
    """*_make_app()* base app + vernier mount; mirrors the calibration runner shape."""
    _app = make_base_app(f"test::{spec.name}",
                         healthz_fn=lambda: {"name": spec.name})
    mount_vernier_svc(_app, spec, payload_size_bytes=payload_size_bytes)
    return _app


def _req_with_payload(size_bytes: int) -> Dict[str, Any]:
    """*_req_with_payload()* build a SvcReq dict whose payload blob is exactly `size_bytes` ASCII bytes."""
    _payload = generate_payload(kind="ping", size_bytes=size_bytes)
    _req = SvcReq(kind="ping",
                  size_bytes=size_bytes,
                  payload=_payload.to_dict())
    return _req.model_dump()


class TestVernierSvc:
    """**TestVernierSvc** vernier-service module: mount, route, response, logger rows, payload end-to-end read, Bernoulli, admission, mu, drop count."""

    @pytest.mark.asyncio
    async def test_mount_returns_ctx(self):
        """*test_mount_returns_ctx()* mount yields a SvcCtx with `spec.name='CALIB'`, attaches it to `app.state.ctx`, and stashes the bound handler on `_ctx.handler`."""
        _s = _spec()
        _app = _make_app(_s)
        _ctx = _app.state.ctx
        assert _ctx.spec.name == "CALIB"
        assert _ctx.handler is not None
        assert callable(_ctx.handler)

    @pytest.mark.asyncio
    async def test_route_is_post_invoke(self):
        """*test_route_is_post_invoke()* the only POST route is `/invoke`; `/healthz` is the only user-facing GET (FastAPI's `/openapi.json` / `/docs` / `/redoc` auto-routes are ignored)."""
        _s = _spec()
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
    async def test_terminal_response_ok(self):
        """*test_terminal_response_ok()* a default-eps POST returns `success=True / service_name='CALIB'` with a `terminal` message prefix."""
        _s = _spec()
        _app = _make_app(_s, payload_size_bytes=128)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.post("/invoke", json=_req_with_payload(128))
        assert _r.status_code == 200
        _b = _r.json()
        assert _b["success"] is True
        assert _b["service_name"] == "CALIB"
        assert _b["message"].startswith("terminal")

    @pytest.mark.asyncio
    async def test_logger_writes_one_row_per_call(self):
        """*test_logger_writes_one_row_per_call()* after N POSTs `len(_ctx.log) == N`, every row has the 10 LOG_COLUMNS keys, and `service_name == 'CALIB'`."""
        _s = _spec()
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
            assert _row["service_name"] == "CALIB"

    @pytest.mark.asyncio
    async def test_payload_is_read_end_to_end(self):
        """*test_payload_is_read_end_to_end()* the response message echoes `size_bytes=<n>` matching the declared payload length, proving FastAPI does not short-circuit before the body lands."""
        _s = _spec()
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
    async def test_bernoulli_eps_records_failure(self):
        """*test_bernoulli_eps_records_failure()* `epsilon=1.0` forces every call to return `success=False / message='bernoulli failure'`; CSV `success` column is `False`."""
        _s = _spec(epsilon=1.0)
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
    async def test_admission_gate_caps_concurrency(self):
        """*test_admission_gate_caps_concurrency()* with `c=2`, the maximum observed `c_used_at_start` across all logged rows is `<=2` even when 8 requests are fired in parallel."""
        _s = _spec(c=2, mu=200.0)
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
    async def test_mu_sleep_lower_bounds_response_time(self):
        """*test_mu_sleep_lower_bounds_response_time()* with `mu=200` (1/mu=5 ms expected), mean observed `end_ts - start_ts` is at least 1 ms; loose to absorb Windows scheduler jitter."""
        _s = _spec(mu=200.0)
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
    async def test_drop_count_zero_on_normal_load(self):
        """*test_drop_count_zero_on_normal_load()* after a routine probe (samples << log_maxlen), `_ctx.dropped_count == 0`."""
        _s = _spec()
        _app = _make_app(_s, payload_size_bytes=64)
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _ in range(_QUICK_SAMPLES):
                await _c.post("/invoke", json=_req_with_payload(64))
        _ctx = _app.state.ctx
        assert _ctx.dropped_count == 0
