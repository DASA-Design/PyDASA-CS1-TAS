# -*- coding: utf-8 -*-
"""
Module test_uvicorn_thread.py
=============================

Pin the boundary contract of `UvicornThread`: construction must wire bind args into the embedded `uvicorn.Server` config without spawning anything, the `active` loop guard must default to cleared and respond to `shutdown()`, and the readiness poll must surface a clear failure when nothing is listening on the bound port within the deadline.

End-to-end lifecycle (`start()` -> `wait_ready()` -> `shutdown()` against a live FastAPI app) is exercised by `tests/experiment/test_launcher.py`. Repeating the live-server path here trips pytest-asyncio's global `asyncio.run` patch (which lacks the `loop_factory` kwarg uvicorn passes on Python 3.12+) and turns the suite flaky, so this file stays scoped to the in-process boundaries.

    - **TestUvicornThread** constructor field-recording, custom bind args reaching `uvicorn.Config`, `active` flag default + `shutdown()` clearing, `wait_ready()` deadline raise + URL in the error message.
"""
# native python modules
import socket

# testing framework
import pytest

# web stack
from fastapi import FastAPI

# module under test
from src.experiment.runtime import UvicornThread


def _free_port() -> int:
    """*_free_port()* ask the kernel for an ephemeral port, close the probe socket, and return the number; the kernel may reassign the port before the next bind, so callers should bind immediately."""
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    _port = int(_s.getsockname()[1])
    _s.close()
    return _port


def _healthz_app() -> FastAPI:
    """*_healthz_app()* build a minimal FastAPI app whose only route is `GET /healthz` returning `{"ok": True}` with status 200, suitable for readiness-probe assertions."""
    _app = FastAPI()

    @_app.get("/healthz")
    def _healthz() -> dict:
        return {"ok": True}

    return _app


class TestUvicornThread:
    """**TestUvicornThread** in-process boundary checks for `UvicornThread`: constructor records bind fields and forwards `host` / `port` / `backlog` into the embedded `uvicorn.Config` without starting the worker; `active` defaults to `False` and `shutdown()` clears it; `wait_ready()` raises `RuntimeError` with the probed `/healthz` URL when no listener answers before the deadline."""

    def test_fields_recorded(self) -> None:
        """*test_fields_recorded()* `t._host == "127.0.0.1"`, `t._port == port`, `t.is_alive() is False` immediately after construction."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        assert _t._host == "127.0.0.1"
        assert _t._port == _port
        assert _t.is_alive() is False

    def test_custom_host_and_backlog(self) -> None:
        """*test_custom_host_and_backlog()* `host="0.0.0.0"` and `backlog=4096` survive into `t._host`, `t._server.config.backlog`, and `t._server.config.port`."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(),
                           port=_port,
                           host="0.0.0.0",
                           backlog=4096)
        assert _t._host == "0.0.0.0"
        assert _t._server.config.backlog == 4096
        assert _t._server.config.port == _port

    def test_active_starts_cleared(self) -> None:
        """*test_active_starts_cleared()* `t.active is False` immediately after construction (no poll has started yet)."""
        _t = UvicornThread(_healthz_app(), port=_free_port())
        assert _t.active is False

    def test_shutdown_clears_active(self) -> None:
        """*test_shutdown_clears_active()* setting `t.active = True` by hand then calling `shutdown()` brings it back to `False`. The trailing `self.join()` raises `RuntimeError` because the worker thread was never started; the assertion runs against the side effect that landed before the raise."""
        _t = UvicornThread(_healthz_app(), port=_free_port())
        _t.active = True
        with pytest.raises(RuntimeError, match="cannot join thread before it is started"):
            _t.shutdown()
        assert _t.active is False

    def test_wait_ready_times_out(self) -> None:
        """*test_wait_ready_times_out()* `wait_ready(timeout_s=0.2)` on a never-started thread raises `RuntimeError` whose message contains `"did not become ready"`."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        with pytest.raises(RuntimeError, match="did not become ready"):
            _t.wait_ready(timeout_s=0.2)

    def test_wait_ready_error_names_url(self) -> None:
        """*test_wait_ready_error_names_url()* the raised `RuntimeError` message contains the probed `http://127.0.0.1:<port>/healthz` URL so the failure points at the unreachable endpoint, not just the elapsed time."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        with pytest.raises(RuntimeError, match=f"127.0.0.1:{_port}/healthz"):
            _t.wait_ready(timeout_s=0.2)
