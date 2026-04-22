# -*- coding: utf-8 -*-
"""
Module test_services.py
=======================

Unit tests for the generic `src/experiment/services/` layer. The layer
intentionally has NO queue-state classes (no admission counters, no
semaphores, no `AtomicQueue` / `CompositeQueue`); queueing behaviour
emerges from FastAPI + asyncio running many requests concurrently. The
tests below exercise only what the layer DOES implement:

    - **TestServiceSpec** frozen dataclass fields + `buffer_budget_bytes()`.
    - **TestDeriveSeed** deterministic per-component seed derivation.
    - **TestServiceContextRng** per-service seeded RNG draws.
    - **TestLogColumns** the frozen CSV schema is stable.
    - **TestMakeBaseApp** `/healthz` works and honours the supplied callback.
    - **TestInstrumented** the `@logger(ctx)` decorator appends one row per call with the right shape.
    - **TestMountAtomicService** the atomic module: healthz + terminal path + ε=1 business failure + handler logs one row per request.
    - **TestMountCompositeService** the composite module: per-member CSVs + in-process dispatch between members + external forward for non-members.
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
from src.experiment.services import (LOG_COLUMNS,
                                     ServiceContext,
                                     ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec,
                                     derive_seed,
                                     logger,
                                     make_base_app,
                                     mount_atomic_service,
                                     mount_composite_service)


# ---- helpers ------------------------------------------------------------


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


# ---- ServiceSpec --------------------------------------------------------


class TestServiceSpec:
    """**TestServiceSpec** frozen dataclass fields + budget helper."""

    def test_required_fields_are_stored(self):
        _s = _spec(mu=500.0, c=2, K=20, epsilon=0.05)
        assert _s.name == "MAS_{1}"
        assert _s.mu == 500.0
        assert _s.c == 2
        assert _s.K == 20
        assert _s.epsilon == 0.05

    def test_defaults(self):
        _s = ServiceSpec(name="X", role="atomic", port=9000,
                         mu=100.0, epsilon=0.0, c=1, K=10)
        assert _s.seed == 0
        assert _s.mem_per_buffer == 0
        assert _s.buffer_budget_bytes == 0

    def test_buffer_budget_reports_declared(self):
        _s = _spec(mem_per_buffer=4096)
        assert _s.buffer_budget_bytes == 4096

    def test_headroom_factor_is_1_5(self):
        assert ServiceSpec.MEM_HEADROOM_FACTOR == 1.5

    def test_frozen_dataclass(self):
        _s = _spec()
        with pytest.raises(Exception):
            _s.mu = 1.0  # type: ignore[misc]


# ---- derive_seed --------------------------------------------------------


class TestDeriveSeed:
    """**TestDeriveSeed** deterministic per-component seed derivation."""

    def test_stable_across_calls(self):
        assert derive_seed(42, "TAS_{1}") == derive_seed(42, "TAS_{1}")

    def test_different_names_diverge(self):
        assert derive_seed(42, "TAS_{1}") != derive_seed(42, "TAS_{2}")

    def test_different_roots_diverge(self):
        assert derive_seed(42, "TAS_{1}") != derive_seed(7, "TAS_{1}")

    def test_64bit_non_negative(self):
        _s = derive_seed(42, "MAS_{3}")
        assert 0 <= _s < (1 << 64)


# ---- ServiceContext -----------------------------------------------------


class TestServiceContextRng:
    """**TestServiceContextRng** per-service seeded RNG draws + log buffer wiring."""

    def test_same_seed_same_draw_sequence(self):
        _s = _spec(seed=12345)
        _a = ServiceContext(spec=_s)
        _b = ServiceContext(spec=_s)
        assert [_a.draw_svc_time() for _ in range(10)] \
            == [_b.draw_svc_time() for _ in range(10)]

    def test_different_seed_diverges(self):
        _a = ServiceContext(spec=_spec(seed=1))
        _b = ServiceContext(spec=_spec(seed=2))
        assert [_a.draw_svc_time() for _ in range(10)] \
            != [_b.draw_svc_time() for _ in range(10)]

    def test_fail_draw_reflects_epsilon(self):
        _a = ServiceContext(spec=_spec(epsilon=0.0, seed=1))
        _z = ServiceContext(spec=_spec(epsilon=1.0, seed=1))
        assert all(_a.draw_eps() is False for _ in range(50))
        assert all(_z.draw_eps() is True for _ in range(50))

    def test_log_buffer_starts_empty(self):
        _ctx = ServiceContext(spec=_spec())
        assert _ctx.log == []


# ---- LOG_COLUMNS frozen schema -----------------------------------------


class TestLogColumns:
    """**TestLogColumns** schema is frozen and covers the downstream re-estimator inputs."""

    def test_exact_tuple(self):
        assert LOG_COLUMNS == (
            "request_id", "service_name", "kind",
            "recv_ts", "start_ts", "end_ts",
            "success", "status_code",
            "size_bytes",
        )


# ---- make_base_app ------------------------------------------------------


class TestMakeBaseApp:
    """**TestMakeBaseApp** bare app exposes `/healthz` and routes the custom callback."""

    @pytest.mark.asyncio
    async def test_default_healthz_returns_ok(self):
        _app = make_base_app("test")
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.get("/healthz")
            assert _r.status_code == 200
            assert _r.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_healthz_uses_supplied_callback(self):
        _app = make_base_app("test",
                             healthz_fn=lambda: {"name": "x", "alive": True})
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://t") as _c:
            _r = await _c.get("/healthz")
            assert _r.json() == {"name": "x", "alive": True}


# ---- @logger decorator -------------------------------------------


class TestInstrumented:
    """**TestInstrumented** the decorator appends one correctly-shaped row per successful call."""

    @pytest.mark.asyncio
    async def test_one_row_per_successful_call(self):
        _ctx = ServiceContext(spec=_spec())

        @logger(_ctx)
        async def _handler(req: ServiceRequest) -> ServiceResponse:
            return ServiceResponse(request_id=req.request_id,
                                   service_name=_ctx.spec.name,
                                   success=True)

        _req = ServiceRequest(kind="analyse", size_bytes=128)
        _resp = await _handler(_req)
        assert _resp.success is True
        assert len(_ctx.log) == 1
        _row = _ctx.log[0]
        assert set(LOG_COLUMNS).issubset(_row.keys())
        assert _row["request_id"] == _req.request_id
        assert _row["service_name"] == _ctx.spec.name
        assert _row["kind"] == "analyse"
        assert _row["success"] is True
        assert _row["status_code"] == 200
        assert _row["size_bytes"] == 128
        assert _row["end_ts"] >= _row["recv_ts"]

    @pytest.mark.asyncio
    async def test_local_success_not_contaminated_by_downstream(self):
        """When the handler returns a DOWNSTREAM response (different service_name) with success=False, THIS context's row stays success=True (local Bernoulli didn't fire)."""
        _ctx = ServiceContext(spec=_spec(name="TAS_{2}"))

        @logger(_ctx)
        async def _handler(req: ServiceRequest) -> ServiceResponse:
            # simulate a downstream that failed its own Bernoulli
            return ServiceResponse(request_id=req.request_id,
                                   service_name="MAS_{1}",
                                   success=False,
                                   message="bernoulli failure")

        await _handler(ServiceRequest())
        assert _ctx.log[-1]["success"] is True

    @pytest.mark.asyncio
    async def test_exception_recorded_as_failure_row(self):
        _ctx = ServiceContext(spec=_spec())

        @logger(_ctx)
        async def _handler(_req: ServiceRequest) -> ServiceResponse:
            raise RuntimeError("downstream blew up")

        with pytest.raises(RuntimeError):
            await _handler(ServiceRequest())
        assert len(_ctx.log) == 1
        assert _ctx.log[0]["success"] is False


# ---- mount_atomic_service ----------------------------------------------


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


# ---- mount_composite_service -------------------------------------------


class TestMountCompositeService:
    """**TestMountCompositeService** composite module: per-member state + internal routing + external forward boundary."""

    def _build_tas_like(self, *, forward) -> FastAPI:
        """A mini TAS-shaped composite: TAS_{1} kind-routes to TAS_{2}, TAS_{2} → external MAS."""
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
