"""Cross-stack facade over the FastAPI / Flask process spawners.

Lets callers mount any HTTP app behind either stack without knowing which spawner backs it.

- `FastAPIAdapter`: ASGI, backed by `UvicornProcess`.
- `FlaskAdapter`: WSGI, backed by `WaitressProcess` (cross-platform default) or `GunicornProcess` (Linux only).

Both share the same lifecycle: `mount` -> `wait_ready` -> `shutdown`. Use `make_server_adapter(framework, wsgi_server)` to get the right instance for a run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, TypeAlias, runtime_checkable

from src.experimental.prototype.runtime.gunicorn_process import GunicornProcess
from src.experimental.prototype.runtime.uvicorn_process import UvicornProcess
from src.experimental.prototype.runtime.waitress_process import WaitressProcess

Framework = Literal["fastapi", "flask"]
WsgiServer = Literal["waitress", "gunicorn"]
FlaskProcess: TypeAlias = WaitressProcess | GunicornProcess
ManagedProcess: TypeAlias = UvicornProcess | FlaskProcess


@runtime_checkable
class Handler(Protocol):
    """Request -> response handler contract honoured by both adapters.

    Takes a payload dict and returns one (sync) or an awaitable resolving to one (async). Lets service code be written once and run under either stack.
    """

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any] | Awaitable[dict[str, Any]]:
        """Handle one request payload and return the response payload.

        Args:
            payload (dict[str, Any]): parsed request body (already JSON-decoded).

        Returns:
            dict[str, Any] | Awaitable[dict[str, Any]]: response body. Async handlers return a coroutine; sync handlers return the dict directly.
        """
        ...


class ServerAdapter(ABC):
    """Cross-stack server-process facade.

    Wraps one of the three spawners. `mount` builds and starts it; `wait_ready` and `shutdown` delegate.

    Attributes:
        _proc (ManagedProcess | None): spawner instance; None until `mount` is called.
    """

    def __init__(self) -> None:
        """Initialise the adapter with no live spawner."""
        self._proc: ManagedProcess | None = None

    @abstractmethod
    def mount(self,
              app_factory: Callable[[], Any],
              port: int,
              *,
              host: str = "127.0.0.1") -> None:
        """Build the spawner and start the child process.

        Args:
            app_factory (Callable[[], Any]): zero-arg picklable callable that builds the framework-specific app inside the child process.
            port (int): TCP port to bind on.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.

        Raises:
            RuntimeError: if `mount` is called twice on the same adapter (one process per adapter).
        """
        ...

    def wait_ready(self, timeout_s: float | None = None) -> None:
        """Delegate readiness probing to the underlying spawner.

        Args:
            timeout_s (float | None, optional): seconds to wait for the first 200 from `/healthz`. Defaults to None, which uses the spawner's configured `_ready_timeout_s` (sourced from `experimental.json::server.<spawner>.ready_timeout_s`).

        Raises:
            RuntimeError: when `mount` has not been called, or when the spawner reports the child failed to become ready.
        """
        if self._proc is None:
            _msg = "ServerAdapter.wait_ready called before mount"
            raise RuntimeError(_msg)
        self._proc.wait_ready(timeout_s=timeout_s)

    def shutdown(self) -> None:
        """End the child process; safe to call before `mount` (no-op) and idempotent afterwards."""
        if self._proc is not None:
            self._proc.shutdown()

    def is_alive(self) -> bool:
        """Report whether the child process exists and has not yet exited.

        Returns:
            bool: False before `mount` or after the child has terminated; True while the worker is running.
        """
        _ans = False
        if self._proc is not None and self._proc.is_alive():
            _ans = True
        return _ans


class FastAPIAdapter(ServerAdapter):
    """ASGI / FastAPI adapter backed by `UvicornProcess`."""

    def mount(self,
              app_factory: Callable[[], Any],
              port: int,
              *,
              host: str = "127.0.0.1") -> None:
        """Construct a `UvicornProcess` for the given factory and start it.

        Args:
            app_factory (Callable[[], Any]): zero-arg picklable callable returning a FastAPI app.
            port (int): TCP port.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.

        Raises:
            RuntimeError: if `mount` is called twice on the same adapter.
        """
        if self._proc is not None:
            _msg = "FastAPIAdapter.mount() called twice; one process per adapter"
            raise RuntimeError(_msg)
        _proc = UvicornProcess(app_factory, port, host=host)
        _proc.start()
        self._proc = _proc


class FlaskAdapter(ServerAdapter):
    """WSGI / Flask adapter backed by waitress (default) or gunicorn (Linux-only).

    Attributes:
        _wsgi_server (WsgiServer): which WSGI server backs this adapter.
    """

    def __init__(self, wsgi_server: WsgiServer = "waitress") -> None:
        """Pick the WSGI server; the spawner is built lazily inside `mount`.

        Args:
            wsgi_server (WsgiServer, optional): `"waitress"` (cross-platform default) or `"gunicorn"` (Linux only). Defaults to `"waitress"`.

        Raises:
            ValueError: if `wsgi_server` is neither `"waitress"` nor `"gunicorn"`.
        """
        super().__init__()
        if wsgi_server not in ("waitress", "gunicorn"):
            _msg = f"unknown wsgi_server {wsgi_server!r}; expected 'waitress' or 'gunicorn'"
            raise ValueError(_msg)
        self._wsgi_server: WsgiServer = wsgi_server

    def mount(self,
              app_factory: Callable[[], Any],
              port: int,
              *,
              host: str = "127.0.0.1") -> None:
        """Construct the chosen WSGI process spawner and start it.

        Args:
            app_factory (Callable[[], Any]): zero-arg picklable callable returning a Flask / WSGI app.
            port (int): TCP port.
            host (str, optional): bind address. Defaults to `"127.0.0.1"`.

        Raises:
            RuntimeError: if `mount` is called twice on the same adapter, or if `wsgi_server="gunicorn"` is selected on Windows.
        """
        if self._proc is not None:
            _msg = "FlaskAdapter.mount() called twice; one process per adapter"
            raise RuntimeError(_msg)
        if self._wsgi_server == "gunicorn":
            _proc: FlaskProcess = GunicornProcess(app_factory, port, host=host)
        else:
            _proc = WaitressProcess(app_factory, port, host=host)
        _proc.start()
        self._proc = _proc


def make_server_adapter(framework: Framework,
                        wsgi_server: WsgiServer = "waitress") -> ServerAdapter:
    """Return the right concrete `ServerAdapter` for the run's config.

    Args:
        framework (Framework): `"fastapi"` (ASGI) or `"flask"` (WSGI).
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`; ignored otherwise. Defaults to `"waitress"`.

    Returns:
        ServerAdapter: a `FastAPIAdapter` for `"fastapi"`, or a `FlaskAdapter` configured with the chosen WSGI engine for `"flask"`.

    Raises:
        ValueError: if `framework` is neither `"fastapi"` nor `"flask"`.
    """
    if framework == "fastapi":
        return FastAPIAdapter()
    if framework == "flask":
        return FlaskAdapter(wsgi_server=wsgi_server)
    _msg = f"unknown framework {framework!r}; expected 'fastapi' or 'flask'"
    raise ValueError(_msg)
