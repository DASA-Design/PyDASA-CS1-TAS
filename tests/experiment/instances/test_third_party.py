# -*- coding: utf-8 -*-
"""
Module test_third_party.py
==========================

Pins the `build_third_party` instance contract: one FastAPI app per
MAS / AS / DS, atomic handler mounted at `/invoke`, `/healthz`
echoing the spec knobs, `app.state.ctx` exposing the per-service
`ServiceContext` (so the launcher can flush its log).

    - **TestAppStructure** the returned app has `/healthz` + `/invoke` and a `ServiceContext` on `app.state.ctx`.
    - **TestTerminalService** empty `targets` returns `success=True` after service-time + epsilon; external-forward is never called.
    - **TestExternalForward** non-empty `targets` picks one hop (seeded) and forwards through `external_forward`.
    - **TestBernoulliEpsilon** epsilon = 1.0 always returns `success=False` with `message="bernoulli failure"`; no forward is called.
    - **TestLogRow** every POST appends exactly one row with the `LOG_COLUMNS` schema to `ctx.log`.
"""
# native python modules
from typing import List, Tuple

# testing framework
import pytest

# web stack
import httpx

# modules under test
from src.experiment.instances import build_third_party
from src.experiment.services import (LOG_COLUMNS,
                                     ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec)


# ---------------------------------------------------------------- helpers


def _mas_spec(*, mu: float = 1e9, epsilon: float = 0.0,
              c: int = 1, K: int = 10, seed: int = 1) -> ServiceSpec:
    """*_mas_spec()* build a stock `ServiceSpec` for a third-party leaf (MAS_{1}).

    Defaults to `mu=1e9` so the exponential service time collapses to
    near-zero, keeping the test's wall clock dominated by the asyncio
    scheduler rather than by the simulated service.
    """
    return ServiceSpec(name="MAS_{1}", role="atomic", port=8006,
                       mu=mu, epsilon=epsilon, c=c, K=K, seed=seed)


async def _no_forward(_target: str, _req: ServiceRequest) -> ServiceResponse:
    """*_no_forward()* assertion-raising forward; fails loudly if the test path calls it."""
    raise AssertionError(f"unexpected external forward to {_target!r}")


def _recorded_forward(_calls: List[Tuple[str, str]]):
    """*_recorded_forward()* forward closure that appends `(target, request_id)` to `_calls` and returns success."""

    async def _fwd(target: str, req: ServiceRequest) -> ServiceResponse:
        _calls.append((target, req.request_id))
        return ServiceResponse(request_id=req.request_id,
                               service_name=target,
                               success=True,
                               message="recorded")

    return _fwd


# ------------------------------------------------------------- fixtures


@pytest.fixture
def _app_terminal():
    """*_app_terminal()* build a terminal third-party app (empty routing row)."""
    _spec = _mas_spec()
    _app = build_third_party(_spec, targets=[], external_forward=_no_forward)
    return _app, _spec


@pytest.fixture
def _app_with_forward():
    """*_app_with_forward()* build a third-party app that forwards to a single downstream."""
    _spec = _mas_spec()
    _calls: List[Tuple[str, str]] = []
    _fwd = _recorded_forward(_calls)
    _app = build_third_party(_spec, targets=[("DS_{3}", 1.0)],
                             external_forward=_fwd)
    return _app, _spec, _calls


@pytest.fixture
def _app_failing():
    """*_app_failing()* build a third-party app whose Bernoulli fires on every call (eps=1.0)."""
    _spec = _mas_spec(epsilon=1.0)
    _app = build_third_party(_spec, targets=[("DS_{3}", 1.0)],
                             external_forward=_no_forward)
    return _app, _spec


# --------------------------------------------------------------- classes


class TestAppStructure:
    """**TestAppStructure** the built app exposes the contract the launcher relies on."""

    @pytest.mark.asyncio
    async def test_healthz_returns_spec_knobs(self, _app_terminal):
        """*test_healthz_returns_spec_knobs()* `/healthz` echoes name / role / c / K from the spec."""
        _app, _spec = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.get("/healthz")
        assert _r.status_code == 200
        _body = _r.json()
        assert _body == {"name": _spec.name, "role": "third_party",
                         "c": _spec.c, "K": _spec.K}

    def test_app_state_exposes_service_context(self, _app_terminal):
        """*test_app_state_exposes_service_context()* the launcher reaches the per-service log through `app.state.ctx`."""
        _app, _spec = _app_terminal
        _ctx = _app.state.ctx
        assert _ctx.spec is _spec
        assert _ctx.log == []


class TestTerminalService:
    """**TestTerminalService** an empty routing row returns success without forwarding."""

    @pytest.mark.asyncio
    async def test_terminal_returns_success(self, _app_terminal):
        """*test_terminal_returns_success()* POST /invoke on a terminal service returns `success=True`."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is True
        assert _body["service_name"] == "MAS_{1}"
        assert _body["message"] == "terminal"


class TestExternalForward:
    """**TestExternalForward** non-empty routing forwards through `external_forward`."""

    @pytest.mark.asyncio
    async def test_forward_called_for_downstream_target(self, _app_with_forward):
        """*test_forward_called_for_downstream_target()* the closure fires exactly once with the routing-row target."""
        _app, _, _calls = _app_with_forward
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0] == ("DS_{3}", _req.request_id)


class TestBernoulliEpsilon:
    """**TestBernoulliEpsilon** eps = 1.0 returns a business failure and skips the forward."""

    @pytest.mark.asyncio
    async def test_epsilon_one_always_fails(self, _app_failing):
        """*test_epsilon_one_always_fails()* every call returns `success=False, message="bernoulli failure"`."""
        _app, _ = _app_failing
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _req = ServiceRequest(kind="analyse", size_bytes=64)
            _r = await _c.post("/invoke", json=_req.model_dump())
        assert _r.status_code == 200
        _body = _r.json()
        assert _body["success"] is False
        assert _body["message"] == "bernoulli failure"


class TestLogRow:
    """**TestLogRow** every POST /invoke appends exactly one row to `ctx.log` with the `LOG_COLUMNS` schema."""

    @pytest.mark.asyncio
    async def test_one_row_per_invocation(self, _app_terminal):
        """*test_one_row_per_invocation()* three POSTs produce three log rows with the pinned columns."""
        _app, _ = _app_terminal
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            for _i in range(3):
                _req = ServiceRequest(kind="analyse", size_bytes=64)
                _r = await _c.post("/invoke", json=_req.model_dump())
                assert _r.status_code == 200

        _log = _app.state.ctx.log
        assert len(_log) == 3
        for _row in _log:
            assert set(LOG_COLUMNS).issubset(set(_row.keys()))
            assert _row["service_name"] == "MAS_{1}"
            assert _row["success"] is True
