# -*- coding: utf-8 -*-
"""
Module test_uvicorn_process.py
==============================

Pin the boundary contract of `UvicornProcess`: spawn args land on the instance, the readiness-poll guard defaults to cleared, the readiness poll surfaces a clear failure when no listener answers in time, and a real spawn-and-serve smoke (`@pytest.mark.live_mesh`) exercises the Windows `spawn` + picklable-factory contract end-to-end.

`_healthz_app_factory` lives at module scope because `multiprocessing.spawn` re-imports it by name in the child; a nested factory would not survive the spawn boundary on Windows.

    - **TestUvicornProcess** field recording, `active` default, `is_alive` False before start, `wait_ready` deadline raise, URL in the error message, double-`start` guard, and (live-mesh) end-to-end spawn -> healthz 200 -> shutdown.
"""
# native python modules
import socket

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# module under test
from src.experiment.runtime import UvicornProcess


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


def _healthz_app_factory() -> FastAPI:
    """*_healthz_app_factory()* return a `FastAPI` app with a single `GET /healthz` route that responds `{"ok": True}` with status 200.

    Top-level so `multiprocessing.spawn` can re-import it by name in the worker process; a nested or fixture-scoped definition would break the spawn boundary on Windows. Routes are declared inside the function so the FastAPI instance is built in the worker's address space and never crosses the spawn boundary as a pickled object.

    Returns:
        FastAPI: app with one `/healthz` route.
    """
    _app = FastAPI()

    @_app.get("/healthz")
    def _healthz() -> dict:
        return {"ok": True}

    return _app


class TestUvicornProcess:
    """**TestUvicornProcess** boundary checks: constructor records spawn fields without forking; `active` defaults to False; `is_alive` is False pre-start; `wait_ready` raises `RuntimeError` whose message contains the probed `/healthz` URL when no listener answers; second `start` raises `RuntimeError`. The live-mesh test runs the full spawn -> healthz 200 -> shutdown lifecycle on a real loopback port."""

    def test_fields_recorded(self) -> None:
        """*test_fields_recorded()* `p._host == "127.0.0.1"`, `p._port == port`, `p._backlog == 16384`, `p.is_alive() is False`."""
        _port = _free_port()
        _p = UvicornProcess(_healthz_app_factory, port=_port)
        assert _p._host == "127.0.0.1"
        assert _p._port == _port
        assert _p._backlog == 16384
        assert _p.is_alive() is False

    def test_custom_host_and_backlog(self) -> None:
        """*test_custom_host_and_backlog()* `host="0.0.0.0"` and `backlog=4096` survive into `p._host` and `p._backlog`; `p._port` matches the constructor arg."""
        _port = _free_port()
        _p = UvicornProcess(_healthz_app_factory,
                            port=_port,
                            host="0.0.0.0",
                            backlog=4096)
        assert _p._host == "0.0.0.0"
        assert _p._backlog == 4096
        assert _p._port == _port

    def test_active_starts_cleared(self) -> None:
        """*test_active_starts_cleared()* `p.active is False` immediately after construction."""
        _p = UvicornProcess(_healthz_app_factory, port=_free_port())
        assert _p.active is False

    def test_shutdown_unstarted(self) -> None:
        """*test_shutdown_unstarted()* setting `p.active = True` then calling `shutdown` clears it back to False; `p._proc` stays None (early-return path)."""
        _p = UvicornProcess(_healthz_app_factory, port=_free_port())
        _p.active = True
        _p.shutdown()
        assert _p.active is False
        assert _p._proc is None

    def test_wait_ready_timeout(self) -> None:
        """*test_wait_ready_timeout()* `p.wait_ready(timeout_s=0.2)` on a never-started process raises `RuntimeError` whose message contains `"did not become ready"`."""
        _port = _free_port()
        _p = UvicornProcess(_healthz_app_factory, port=_port)
        with pytest.raises(RuntimeError, match="did not become ready"):
            _p.wait_ready(timeout_s=0.2)

    def test_wait_ready_error_url(self) -> None:
        """*test_wait_ready_error_url()* the raised `RuntimeError` message contains the literal `127.0.0.1:<port>/healthz` URL so the failure points at the unreachable endpoint."""
        _port = _free_port()
        _p = UvicornProcess(_healthz_app_factory, port=_port)
        with pytest.raises(RuntimeError, match=f"127.0.0.1:{_port}/healthz"):
            _p.wait_ready(timeout_s=0.2)

    def test_double_start_raises(self) -> None:
        """*test_double_start_raises()* `start` called twice raises `RuntimeError` with `"one process per instance"` in the message; `_proc` is stubbed to a sentinel so the test exercises the guard without actually spawning."""
        _p = UvicornProcess(_healthz_app_factory, port=_free_port())
        _p._proc = "stub"  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="one process per instance"):
            _p.start()

    @pytest.mark.live_mesh
    def test_spawn_lifecycle(self) -> None:
        """*test_spawn_lifecycle()* `start` spawns the child; `wait_ready(timeout_s=10.0)` returns; `is_alive() is True`; `httpx.get("/healthz").status_code == 200` with body `{"ok": True}`; `shutdown` returns; `is_alive() is False`. Validates the Windows `spawn` + picklable-factory contract end-to-end (the spike for SOA Phase A Stage A1 / calibration refactor Stage C1)."""
        _port = _free_port()
        _p = UvicornProcess(_healthz_app_factory, port=_port)
        try:
            _p.start()
            _p.wait_ready(timeout_s=10.0)
            assert _p.is_alive() is True
            _r = httpx.get(f"http://127.0.0.1:{_port}/healthz", timeout=2.0)
            assert _r.status_code == 200
            assert _r.json() == {"ok": True}
        finally:
            _p.shutdown()
        assert _p.is_alive() is False
