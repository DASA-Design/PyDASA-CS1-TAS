# -*- coding: utf-8 -*-
"""
Module test_base.py
===================

Unit tests for `src/experiment/services/base.py`:

    - **TestServiceSpec** frozen dataclass fields + `buffer_budget_bytes`.
    - **TestDeriveSeed** deterministic per-component seed derivation.
    - **TestServiceContextRng** per-service seeded RNG draws + log buffer wiring.
    - **TestLogColumns** the frozen CSV schema.
    - **TestMakeBaseApp** bare app + `/healthz` + custom callback.
    - **TestHttpForward** async `(target, req) -> ServiceResponse` callback over HTTP.
"""
# testing framework
import pytest

# web stack
import httpx

# modules under test
from src.experiment.services import (LOG_COLUMNS,
                                     HttpForward,
                                     ServiceContext,
                                     ServiceRequest,
                                     ServiceSpec,
                                     derive_seed,
                                     make_base_app)


# ---- helpers ------------------------------------------------------------


def _spec(**kwargs) -> ServiceSpec:
    """*_spec()* build a ServiceSpec with sensible defaults; override via kwargs."""
    _defaults = dict(name="MAS_{1}", role="atomic", port=8006,
                     mu=1000.0, epsilon=0.0, c=1, K=10, seed=42)
    _defaults.update(kwargs)
    return ServiceSpec(**_defaults)


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


# ---- HttpForward -------------------------------------------------------


class TestHttpForward:
    """**TestHttpForward** async `(target, req) -> ServiceResponse` callback over HTTP."""

    def _registry(self):
        """Minimal registry with one third-party + one TAS member."""
        from src.experiment.registry import ServiceRegistry
        return ServiceRegistry.from_config({
            "host": "127.0.0.1",
            "base_port": 9000,
            "service_registry": {
                "MAS_{1}": {"port_offset": 0, "role": "atomic"},
                "TAS_{4}": {"port_offset": 1, "role": "composite_drug"},
            },
        })

    @pytest.mark.asyncio
    async def test_headers_and_url_round_trip(self):
        """POST lands at the registry-resolved URL with the three X-Request headers."""
        _captured = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            _captured["url"] = str(request.url)
            _captured["headers"] = dict(request.headers)
            _body = {"request_id": request.headers.get("x-request-id"),
                     "service_name": "MAS_{1}",
                     "success": True,
                     "message": "ok"}
            return httpx.Response(200, json=_body)

        _client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        _fwd = HttpForward(_client, self._registry())
        _req = ServiceRequest(kind="analyse", size_bytes=256)
        async with _client:
            _resp = await _fwd("MAS_{1}", _req)
        assert _resp.success is True
        assert _captured["url"] == "http://127.0.0.1:9000/invoke"
        assert _captured["headers"].get("x-request-id") == _req.request_id
        assert _captured["headers"].get("x-request-size-bytes") == "256"
        assert _captured["headers"].get("x-request-kind") == "analyse"

    @pytest.mark.asyncio
    async def test_tas_component_target_uses_per_component_url(self):
        """Registry returns `/TAS_<i>/invoke` for TAS names; HttpForward hits that URL."""
        _captured = {}

        def _handler(request: httpx.Request) -> httpx.Response:
            _captured["url"] = str(request.url)
            _body = {"request_id": "x", "service_name": "TAS_{4}",
                     "success": True, "message": "ok"}
            return httpx.Response(200, json=_body)

        _client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        _fwd = HttpForward(_client, self._registry())
        async with _client:
            await _fwd("TAS_{4}", ServiceRequest())
        assert _captured["url"].endswith("/TAS_4/invoke")

    @pytest.mark.asyncio
    async def test_business_failure_passes_through_as_200(self):
        """HTTP 200 with body.success=False is a business failure; HttpForward returns it without raising."""
        def _handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "request_id": "x",
                "service_name": "MAS_{1}",
                "success": False,
                "message": "bernoulli failure",
            })

        _client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        _fwd = HttpForward(_client, self._registry())
        async with _client:
            _resp = await _fwd("MAS_{1}", ServiceRequest())
        assert _resp.success is False
        assert _resp.message == "bernoulli failure"

    @pytest.mark.asyncio
    async def test_infrastructure_failure_raises_http_status_error(self):
        """Non-2xx responses raise `httpx.HTTPStatusError` so the caller can treat them as infra failures."""
        def _handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "buffer full"})

        _client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        _fwd = HttpForward(_client, self._registry())
        async with _client:
            with pytest.raises(httpx.HTTPStatusError):
                await _fwd("MAS_{1}", ServiceRequest())
