# -*- coding: utf-8 -*-
"""
Module test_third_party.py
==========================

Pin the `build_third_party` contract: one FastAPI app per MAS / AS / DS, atomic handler at `/invoke`, `/healthz` echoing the spec, `app.state.ctx` exposing the per-service `SvcCtx`.

    - **TestThirdPartyInstance** app structure, terminal vs forwarding behaviour, Bernoulli failure path, per-call log row.
"""
# native python modules
from typing import List, Tuple

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.instances import build_third_party
from src.experiment.services import LOG_COLUMNS, SvcReq, SvcSpec

# helper modules
from tests.utils.helpers import (_RecordedForward,
                                 _SpecBuilder,
                                 _no_forward)


# ------------------------------------------------------------- fixtures


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`."""
    return _SpecBuilder()


@pytest.fixture
def _app_terminal(specs: _SpecBuilder) -> Tuple[FastAPI, SvcSpec]:
    """*_app_terminal()* terminal MAS_{1} (empty `targets`, `mu=1e9`)."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, seed=1)
    _app = build_third_party(_spec, targets=[], ext_fwd=_no_forward)
    return _app, _spec


@pytest.fixture
def _app_with_forward(specs: _SpecBuilder) -> Tuple[FastAPI,
                                                    SvcSpec,
                                                    List[Tuple[str, str]]]:
    """*_app_with_forward()* MAS_{1} forwarding every call to DS_{3} via `_RecordedForward(calls)`."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, seed=1)
    _calls: List[Tuple[str, str]] = []
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             ext_fwd=_RecordedForward(_calls))
    return _app, _spec, _calls


@pytest.fixture
def _app_failing(specs: _SpecBuilder) -> Tuple[FastAPI, SvcSpec]:
    """*_app_failing()* MAS_{1} with `epsilon=1.0` (Bernoulli fires every call)."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, epsilon=1.0, seed=1)
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             ext_fwd=_no_forward)
    return _app, _spec


# --------------------------------------------------------------- classes


class TestThirdPartyInstance:
    """**TestThirdPartyInstance** structure, terminal / forwarding / Bernoulli behaviour, and per-call logging."""

    @pytest.mark.asyncio
    async def test_healthz_echoes_spec(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_healthz_echoes_spec()* `GET /healthz` returns 200 with body `{"role": "third_party", "components": [{"name": spec.name, "c": spec.c, "K": spec.K}]}`."""
        _app, _spec = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _client:
            _r = await _client.get("/healthz")
        assert _r.status_code == 200
        assert _r.json() == {"role": "third_party",
                             "components": [{"name": _spec.name,
                                             "c": _spec.c,
                                             "K": _spec.K}]}

    def test_ctx_on_app_state(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_ctx_on_app_state()* `app.state.ctx.spec is spec` and `len(app.state.ctx.log) == 0` after `build_third_party` returns."""
        _app, _spec = _app_terminal
        _ctx = _app.state.ctx
        assert _ctx.spec is _spec
        assert len(_ctx.log) == 0

    @pytest.mark.asyncio
    async def test_terminal_returns_success(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_terminal_returns_success()* one POST to `/invoke` returns 200 with `success is True`, `srv_name == "MAS_{1}"`, `message == "terminal"`."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _client:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _client.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is True
        assert _body["srv_name"] == "MAS_{1}"
        assert _body["message"] == "terminal"

    @pytest.mark.asyncio
    async def test_forwards_to_target(self, _app_with_forward: Tuple[FastAPI, SvcSpec, List[Tuple[str, str]]]) -> None:
        """*test_forwards_to_target()* one POST to `/invoke` produces `len(calls) == 1` and `calls[0] == ("DS_{3}", req.req_id)`."""
        _app, _, _calls = _app_with_forward
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _client:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _client.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0] == ("DS_{3}", _req.req_id)

    @pytest.mark.asyncio
    async def test_epsilon_one_fails(self, _app_failing: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_epsilon_one_fails()* one POST returns 200 with `success is False` and `message == "bernoulli failure"`; `ext_fwd` is never called."""
        _app, _ = _app_failing
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _client:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _client.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is False
        assert _body["message"] == "bernoulli failure"

    @pytest.mark.asyncio
    async def test_one_row_per_call(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_one_row_per_call()* after 3 POSTs `len(ctx.log) == 3`; every row's keys are a superset of `LOG_COLUMNS` with `srv_name == "MAS_{1}"` and `success is True`."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _client:
            for _i in range(3):
                _req = SvcReq(kind="analyse", size_bytes=64)
                _r = await _client.post("/invoke", json=_req.model_dump())
                assert _r.status_code == 200
        _log = _app.state.ctx.log
        assert len(_log) == 3
        for _row in _log:
            assert set(LOG_COLUMNS).issubset(set(_row.keys()))
            assert _row["srv_name"] == "MAS_{1}"
            assert _row["success"] is True
