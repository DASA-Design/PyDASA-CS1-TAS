# -*- coding: utf-8 -*-
"""
Module test_third_party.py
==========================

Pin the `build_third_party` instance contract: one FastAPI app per MAS / AS / DS, atomic handler at `/invoke`, `/healthz` echoing the spec knobs, `app.state.ctx` exposing the per-service `SvcCtx`.

    - **TestAppStructure** routes (`/healthz` GET + `/invoke` POST) and `app.state.ctx` are present after `build_third_party` returns.
    - **TestTerminalService** an empty `targets` row returns `success=True` and never calls `ext_fwd`.
    - **TestExternalForward** a single-target row forwards exactly one call to that target through `ext_fwd`.
    - **TestBernoulliEpsilon** `epsilon=1.0` returns `success=False / message="bernoulli failure"` and skips the forward.
    - **TestLogRow** every POST to `/invoke` appends one row covering `LOG_COLUMNS` to `ctx.log`.
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
from src.experiment.services import (LOG_COLUMNS,
                                     SvcReq,
                                     SvcResp,
                                     SvcSpec)

# helper modules
from tests.utils.helpers import _SpecBuilder


# ---------------------------------------------------------------- helpers


async def _no_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_no_forward()* fail loudly when the test path calls it; used for terminal services."""
    raise AssertionError(f"unexpected external forward to {_tgt!r}")


class _RecordedForward:
    """*_RecordedForward* append `(target, req.req_id)` to `self.calls` and return `SvcResp(success=True, message="recorded")`. Used as the test-side `ext_fwd` so each test can assert which targets the handler tried to forward to."""

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
def _app_terminal(specs: _SpecBuilder) -> Tuple[FastAPI, SvcSpec]:
    """*_app_terminal()* return a `(app, spec)` pair for a terminal MAS_{1} (empty `targets`, `mu=1e9` to keep service time near zero)."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, seed=1)
    _app = build_third_party(_spec, targets=[], ext_fwd=_no_forward)
    return _app, _spec


@pytest.fixture
def _app_with_forward(specs: _SpecBuilder) -> Tuple[FastAPI,
                                                    SvcSpec,
                                                    List[Tuple[str, str]]]:
    """*_app_with_forward()* return a `(app, spec, calls)` triple for a MAS_{1} that forwards every call to DS_{3} via a `_RecordedForward(calls)`."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, seed=1)
    _calls: List[Tuple[str, str]] = []
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             ext_fwd=_RecordedForward(_calls))
    return _app, _spec, _calls


@pytest.fixture
def _app_failing(specs: _SpecBuilder) -> Tuple[FastAPI, SvcSpec]:
    """*_app_failing()* return a `(app, spec)` pair for a MAS_{1} whose Bernoulli fires on every call (`epsilon=1.0`)."""
    _spec = specs(name="MAS_{1}", port=8006, mu=1e9, epsilon=1.0, seed=1)
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             ext_fwd=_no_forward)
    return _app, _spec


# --------------------------------------------------------------- classes


class TestAppStructure:
    """**TestAppStructure** the built app exposes `/healthz`, `/invoke`, and `app.state.ctx` so the launcher can flush per-service logs."""

    @pytest.mark.asyncio
    async def test_healthz_echoes_spec(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_healthz_echoes_spec()* `GET /healthz` returns 200 with body `{"name": spec.name, "role": "third_party", "c": spec.c, "K": spec.K}`."""
        _app, _spec = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.get("/healthz")
        assert _r.status_code == 200
        _body = _r.json()
        assert _body == {"name": _spec.name, "role": "third_party",
                         "c": _spec.c, "K": _spec.K}

    def test_ctx_on_app_state(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_ctx_on_app_state()* `app.state.ctx.spec is spec` and `len(app.state.ctx.log) == 0` right after `build_third_party` returns."""
        _app, _spec = _app_terminal
        _ctx = _app.state.ctx
        assert _ctx.spec is _spec
        assert len(_ctx.log) == 0


class TestTerminalService:
    """**TestTerminalService** an empty routing row returns success and never invokes the forward."""

    @pytest.mark.asyncio
    async def test_terminal_returns_success(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_terminal_returns_success()* one POST to `/invoke` returns 200 with `body.success is True`, `body.srv_name == "MAS_{1}"`, `body.message == "terminal"`."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is True
        assert _body["srv_name"] == "MAS_{1}"
        assert _body["message"] == "terminal"


class TestExternalForward:
    """**TestExternalForward** a non-empty routing row forwards through `ext_fwd`."""

    @pytest.mark.asyncio
    async def test_forward_called(self, _app_with_forward: Tuple[FastAPI, SvcSpec, List[Tuple[str, str]]]) -> None:
        """*test_forward_called()* one POST to `/invoke` produces `len(calls) == 1` and `calls[0] == ("DS_{3}", req.req_id)`."""
        _app, _, _calls = _app_with_forward
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0] == ("DS_{3}", _req.req_id)


class TestBernoulliEpsilon:
    """**TestBernoulliEpsilon** `epsilon=1.0` returns a Bernoulli failure and skips the forward."""

    @pytest.mark.asyncio
    async def test_epsilon_one_fails(self, _app_failing: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_epsilon_one_fails()* every POST returns 200 with `body.success is False` and `body.message == "bernoulli failure"`."""
        _app, _ = _app_failing
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = SvcReq(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is False
        assert _body["message"] == "bernoulli failure"


class TestLogRow:
    """**TestLogRow** every `/invoke` POST appends one row covering `LOG_COLUMNS` to `ctx.log`."""

    @pytest.mark.asyncio
    async def test_one_row_per_call(self, _app_terminal: Tuple[FastAPI, SvcSpec]) -> None:
        """*test_one_row_per_call()* after 3 POSTs `len(ctx.log) == 3`, every row's keys are a superset of `LOG_COLUMNS`, every row has `srv_name == "MAS_{1}"` and `success is True`."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _i in range(3):
                _req = SvcReq(kind="analyse", size_bytes=64)
                _r = await _c.post("/invoke", json=_req.model_dump())
                assert _r.status_code == 200

        _log = _app.state.ctx.log
        assert len(_log) == 3
        for _row in _log:
            assert set(LOG_COLUMNS).issubset(set(_row.keys()))
            assert _row["srv_name"] == "MAS_{1}"
            assert _row["success"] is True
