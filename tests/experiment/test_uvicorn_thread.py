# -*- coding: utf-8 -*-
"""
Module test_uvicorn_thread.py
=============================

Unit tests for `src.experiment.uvicorn_thread.UvicornThread`:

    - **TestInit** the constructor configures host/port/backlog without spawning the thread.
    - **TestLifecycle** `start() -> wait_ready() -> shutdown()` round-trips against a real `/healthz` endpoint on a free loopback port.
    - **TestWaitReadyTimeout** `wait_ready()` raises `RuntimeError` when nothing is listening on the bound port within `timeout_s`.
"""
# native python modules
import socket

# testing framework
import pytest

# web stack
from fastapi import FastAPI

# module under test
from src.experiment.uvicorn_thread import UvicornThread


def _free_port() -> int:
    """*_free_port()* return a TCP port that is free at the moment the call returns. The kernel may reassign it before the next bind, so callers should bind immediately."""
    _s = socket.socket()
    _s.bind(("127.0.0.1", 0))
    _port = int(_s.getsockname()[1])
    _s.close()
    return _port


def _healthz_app() -> FastAPI:
    """*_healthz_app()* return a tiny FastAPI app whose only route is `GET /healthz` returning `{"ok": True}` with status 200."""
    _app = FastAPI()

    @_app.get("/healthz")
    def _healthz() -> dict:
        return {"ok": True}

    return _app


class TestInit:
    """**TestInit** the constructor stores host/port and configures the underlying `uvicorn.Server` but does not start the thread."""

    def test_fields_recorded(self) -> None:
        """*test_fields_recorded()* `t._host == "127.0.0.1"`, `t._port == port`, `t.is_alive() is False` immediately after construction."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        assert _t._host == "127.0.0.1"
        assert _t._port == _port
        assert _t.is_alive() is False

    def test_custom_host_and_backlog(self) -> None:
        """*test_custom_host_and_backlog()* a non-default `host` and `backlog` reach the underlying `uvicorn.Server.config`."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(),
                           port=_port,
                           host="0.0.0.0",
                           backlog=4096)
        assert _t._host == "0.0.0.0"
        assert _t._server.config.backlog == 4096
        assert _t._server.config.port == _port


class TestLifecycle:
    """**TestLifecycle** start, wait for `/healthz`, shut down."""

    def test_start_wait_ready_shutdown(self) -> None:
        """*test_start_wait_ready_shutdown()* `start()` + `wait_ready(timeout_s=5.0)` returns without raising; `is_alive() is True` while the server is up; `shutdown()` joins the thread and drives `is_alive()` to False."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        _t.start()
        try:
            _t.wait_ready(timeout_s=5.0)
            assert _t.is_alive() is True
        finally:
            _t.shutdown()
        assert _t.is_alive() is False


class TestWaitReadyTimeout:
    """**TestWaitReadyTimeout** `wait_ready()` raises `RuntimeError` when the server is not bound."""

    def test_timeout_raises_runtime_error(self) -> None:
        """*test_timeout_raises_runtime_error()* an UvicornThread that was never `start()`-ed has no listener on its port; `wait_ready(timeout_s=0.2)` raises `RuntimeError` whose message contains `"did not become ready"` and the `/healthz` URL."""
        _port = _free_port()
        _t = UvicornThread(_healthz_app(), port=_port)
        with pytest.raises(RuntimeError, match="did not become ready"):
            _t.wait_ready(timeout_s=0.2)
