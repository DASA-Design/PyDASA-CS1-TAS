"""Tests for `src.experimental.prototype.runtime.server`.

**TestServerAdapter**:

- `test_make_fastapi`: the factory routes the FastAPI choice to a FastAPI adapter.
- `test_make_flask_waitress`: the factory routes the Flask + waitress combo to a Flask adapter wired to waitress.
- `test_make_flask_gunicorn`: the factory routes the Flask + gunicorn combo to a Flask adapter wired to gunicorn.
- `test_unknown_framework`: an unknown framework name is rejected with `ValueError`.
- `test_unknown_wsgi`: an unknown WSGI engine name is rejected with `ValueError`.
- `test_wait_ready_pre_mount`: probing for readiness before mount is rejected (no child to probe).
- `test_shutdown_pre_mount`: shutdown before mount is a safe no-op.
- `test_fastapi_lifecycle`: a FastAPI adapter completes the full mount-ready-serve-shutdown cycle over real TCP.
- `test_flask_lifecycle`: a Flask (waitress) adapter completes the full mount-ready-serve-shutdown cycle over real TCP.
- `test_double_mount`: mounting the same adapter twice is rejected.
"""

from __future__ import annotations

import httpx
import pytest

from src.experimental.prototype.runtime.server import (
    FastAPIAdapter,
    FlaskAdapter,
    make_server_adapter,
)
from src.experimental.prototype.runtime.uvicorn_process import UvicornProcess
from src.experimental.prototype.runtime.waitress_process import WaitressProcess
from tests.utils.exp.apps import (
    build_healthz_fastapi_app,
    build_healthz_flask_app,
)
from tests.utils.exp.ports import free_port


class TestServerAdapter:
    """`ServerAdapter` facade over the FastAPI / Flask process spawners."""

    def test_make_fastapi(self) -> None:
        """`make_server_adapter("fastapi")` returns a `FastAPIAdapter`."""
        _adp = make_server_adapter("fastapi")
        assert isinstance(_adp, FastAPIAdapter)

    def test_make_flask_waitress(self) -> None:
        """`make_server_adapter("flask", "waitress")` returns a `FlaskAdapter` configured with the waitress engine."""
        _adp = make_server_adapter("flask", "waitress")
        assert isinstance(_adp, FlaskAdapter)
        assert _adp._wsgi_server == "waitress"  # noqa: SLF001

    def test_make_flask_gunicorn(self) -> None:
        """`make_server_adapter("flask", "gunicorn")` returns a `FlaskAdapter` configured with the gunicorn engine."""
        _adp = make_server_adapter("flask", "gunicorn")
        assert isinstance(_adp, FlaskAdapter)
        assert _adp._wsgi_server == "gunicorn"  # noqa: SLF001

    def test_unknown_framework(self) -> None:
        """An unknown framework raises `ValueError` so config typos surface at run start."""
        with pytest.raises(ValueError, match="unknown framework"):
            make_server_adapter("django")  # type: ignore[arg-type]

    def test_unknown_wsgi(self) -> None:
        """`FlaskAdapter` constructor rejects unknown WSGI engines with `ValueError`."""
        with pytest.raises(ValueError, match="unknown wsgi_server"):
            FlaskAdapter(wsgi_server="bjoern")  # type: ignore[arg-type]

    def test_wait_ready_pre_mount(self) -> None:
        """Calling `wait_ready` before `mount` raises so callers cannot probe a non-existent child."""
        _adp = FastAPIAdapter()
        with pytest.raises(RuntimeError, match="before mount"):
            _adp.wait_ready()

    def test_shutdown_pre_mount(self) -> None:
        """`shutdown()` is a no-op when nothing has been mounted, so cleanup paths run in both branches."""
        _adp = FastAPIAdapter()
        _adp.shutdown()
        assert _adp.is_alive() is False

    def test_fastapi_lifecycle(self) -> None:
        """`FastAPIAdapter.mount` spawns a uvicorn-backed FastAPI process; the resulting service answers `/healthz` over real TCP and shuts down cleanly."""
        _port = free_port()
        _adp = FastAPIAdapter()
        _adp.mount(build_healthz_fastapi_app, port=_port)
        try:
            assert isinstance(_adp._proc, UvicornProcess)  # noqa: SLF001
            _adp.wait_ready(timeout_s=20.0)
            _resp = httpx.get(f"http://127.0.0.1:{_port}/healthz", timeout=2.0)
            assert _resp.status_code == 200
            assert _adp.is_alive() is True
        finally:
            _adp.shutdown()
        assert _adp.is_alive() is False

    def test_flask_lifecycle(self) -> None:
        """`FlaskAdapter` (waitress) mounts a Flask `/healthz` app, the resulting service answers over real TCP, and `shutdown` ends the child."""
        _port = free_port()
        _adp = FlaskAdapter(wsgi_server="waitress")
        _adp.mount(build_healthz_flask_app, port=_port)
        try:
            assert isinstance(_adp._proc, WaitressProcess)  # noqa: SLF001
            _adp.wait_ready(timeout_s=20.0)
            _resp = httpx.get(f"http://127.0.0.1:{_port}/healthz", timeout=2.0)
            assert _resp.status_code == 200
        finally:
            _adp.shutdown()
        assert _adp.is_alive() is False

    def test_double_mount(self) -> None:
        """A second `mount` on the same adapter raises so the one-process-per-adapter invariant holds."""
        _port = free_port()
        _adp = FastAPIAdapter()
        _adp.mount(build_healthz_fastapi_app, port=_port)
        try:
            with pytest.raises(RuntimeError, match="called twice"):
                _adp.mount(build_healthz_fastapi_app, port=_port + 1)
        finally:
            _adp.shutdown()
