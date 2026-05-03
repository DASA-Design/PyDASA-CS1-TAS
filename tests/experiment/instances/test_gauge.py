# -*- coding: utf-8 -*-
"""
Module test_gauge.py
====================

Pin the boundary contract of `build_gauge` and `make_gauge_factory`: the in-process build returns a FastAPI app with `/healthz` + `/invoke` registered and `app.state.ctx` populated; the picklable factory variant survives the Windows `multiprocessing.spawn` boundary so `UvicornProcess` can spawn the gauge in a child worker.

    - **TestGauge** in-process app shape (routes, ctx, title), factory contract (callable, returns same-shape app, `pickle.dumps` round-trip preserves bound args), and (live-mesh) end-to-end spawn -> healthz 200 via `UvicornProcess`.
"""
# native python modules
import pickle
import socket

# testing framework
import pytest

# scientific stack
from fastapi.testclient import TestClient

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.instances import build_gauge, make_gauge_factory
from src.experiment.runtime import UvicornProcess
from src.experiment.services import SvcSpec


def _free_port() -> int:
    """*_free_port()* return an ephemeral port the kernel just gave us; bind immediately, the kernel may reassign it before the next call.

    Returns:
        int: ephemeral TCP port number.
    """
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    _port = int(_s.getsockname()[1])
    _s.close()
    return _port


def _vernier_spec(port: int = 8765) -> SvcSpec:
    """*_vernier_spec()* build the canonical calibration vernier spec: `c=1, K=10, mu=0, epsilon=0` so the loopback floor stays honest with no service-time draw and no failures.

    Args:
        port (int): TCP port for the spec.

    Returns:
        SvcSpec: vernier spec with name `"CALIB"`, role `"atomic"`.
    """
    return SvcSpec(name="CALIB",
                   role="atomic",
                   port=int(port),
                   mu=0.0,
                   epsilon=0.0,
                   c=1,
                   K=10,
                   seed=0,
                   mem_per_buffer=0)


class TestGauge:
    """**TestGauge** in-process build + factory contract: `build_gauge(spec)` returns a FastAPI app with `/healthz` registered, default title `"calibration-vernier::CALIB"`, and `app.state.ctx` populated; `make_gauge_factory(spec, ...)` returns a zero-arg callable whose invocation matches the direct build and which survives `pickle.dumps` round-trip. The live-mesh test runs the full spawn -> `/healthz` 200 -> shutdown lifecycle through `UvicornProcess`."""

    def test_app_returned(self) -> None:
        """*test_app_returned()* `build_gauge(spec)` returns a `FastAPI` instance."""
        _app = build_gauge(_vernier_spec())
        assert isinstance(_app, FastAPI)

    def test_default_title(self) -> None:
        """*test_default_title()* with no `title` kwarg, `app.title == "calibration-vernier::CALIB"`."""
        _app = build_gauge(_vernier_spec())
        assert _app.title == "calibration-vernier::CALIB"

    def test_override_title(self) -> None:
        """*test_override_title()* explicit `title="custom"` survives into `app.title`."""
        _app = build_gauge(_vernier_spec(), title="custom")
        assert _app.title == "custom"

    def test_healthz_route(self) -> None:
        """*test_healthz_route()* `GET /healthz` via `TestClient` returns 200."""
        _app = build_gauge(_vernier_spec())
        with TestClient(_app) as _client:
            _r = _client.get("/healthz")
        assert _r.status_code == 200

    def test_ctx_attached(self) -> None:
        """*test_ctx_attached()* `mount_vernier_svc` sets `app.state.ctx` to a non-None `SvcCtx`."""
        _app = build_gauge(_vernier_spec())
        assert hasattr(_app.state, "ctx")
        assert _app.state.ctx is not None

    def test_factory_callable(self) -> None:
        """*test_factory_callable()* `make_gauge_factory(spec)` returns an object that is callable with no args."""
        _factory = make_gauge_factory(_vernier_spec())
        assert callable(_factory)

    def test_factory_returns_app(self) -> None:
        """*test_factory_returns_app()* invoking the factory returns a `FastAPI` instance with `app.title == "calibration-vernier::CALIB"`."""
        _factory = make_gauge_factory(_vernier_spec())
        _app = _factory()
        assert isinstance(_app, FastAPI)
        assert _app.title == "calibration-vernier::CALIB"

    def test_factory_matches_direct(self) -> None:
        """*test_factory_matches_direct()* factory-built app has the same title and `app.state.ctx` invariants as `build_gauge` called with the same args."""
        _spec = _vernier_spec()
        _direct = build_gauge(_spec, payload_size_bytes=1024, title="custom")
        _via_factory = make_gauge_factory(_spec, payload_size_bytes=1024,
                                          title="custom")()
        assert _direct.title == _via_factory.title
        assert hasattr(_direct.state, "ctx")
        assert hasattr(_via_factory.state, "ctx")

    def test_factory_pickles(self) -> None:
        """*test_factory_pickles()* `pickle.dumps(factory)` succeeds without `PicklingError`; `pickle.loads` returns a callable that still produces a `FastAPI` app with the expected title."""
        _factory = make_gauge_factory(_vernier_spec(), payload_size_bytes=1024)
        _blob = pickle.dumps(_factory)
        _restored = pickle.loads(_blob)
        assert callable(_restored)
        _app = _restored()
        assert isinstance(_app, FastAPI)
        assert _app.title == "calibration-vernier::CALIB"

    @pytest.mark.live_mesh
    def test_spawn_via_factory(self) -> None:
        """*test_spawn_via_factory()* `make_gauge_factory(spec)` -> `UvicornProcess(factory, port)` -> `start` -> `wait_ready(10.0)` -> `is_alive() is True` -> `httpx.get("/healthz").status_code == 200` -> `shutdown` -> `is_alive() is False`. Validates the gauge app survives the Windows `spawn` argument-pickling boundary end-to-end."""
        _port = _free_port()
        _factory = make_gauge_factory(_vernier_spec(_port),
                                      payload_size_bytes=1024)
        _proc = UvicornProcess(_factory, port=_port)
        try:
            _proc.start()
            _proc.wait_ready(timeout_s=10.0)
            assert _proc.is_alive() is True
            _r = httpx.get(f"http://127.0.0.1:{_port}/healthz", timeout=2.0)
            assert _r.status_code == 200
        finally:
            _proc.shutdown()
        assert _proc.is_alive() is False
