"""Bring up calibration spawners and yield their target URLs.

Three modes:

- `localhost`: one spawner on `<host>:<base_port>`.
- `multiprocess`: N spawners on consecutive ports; the rate driver round-robins across them.
- `remote`: reserved for the distributed deployment; raises `NotImplementedError` for now.

`bring_up(...)` is a context manager: mount, wait for ready, yield URLs, shut down on exit. Tests pass `adapter_factory` to exercise the orchestration without real spawns.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

from src.experimental.prototype.runtime.server import (
    ServerAdapter,
    make_server_adapter,
)

Dpl = Literal["localhost", "multiprocess", "remote"]
Framework = Literal["fastapi", "flask"]
WsgiServer = Literal["waitress", "gunicorn"]
AppFactory = Callable[[], Any]
AdapterFactory = Callable[[], ServerAdapter]

# Runtime fallbacks for data/config/method/experimental.json::dpl.*.
_DFLT_BASE_PORT = 8001
_DFLT_WORKERS = 4
_DFLT_READY_TIMEOUT_S = 20.0


@contextmanager
def bring_up(dpl: Dpl,
             *,
             app_factory: AppFactory,
             framework: Framework = "fastapi",
             wsgi_server: WsgiServer = "waitress",
             host: str = "127.0.0.1",
             base_port: int = _DFLT_BASE_PORT,
             workers: int = _DFLT_WORKERS,
             ready_timeout_s: float = _DFLT_READY_TIMEOUT_S,
             adapter_factory: AdapterFactory | None = None) -> Iterator[list[str]]:
    """Mount calibration spawners for `dpl`, yield their target URLs, shut them down on exit.

    Args:
        dpl (Dpl): deployment mode. `"localhost"` mounts one spawner; `"multiprocess"` mounts `workers` spawners on consecutive ports.
        app_factory (AppFactory): zero-arg picklable callable returning the app to serve (e.g. `build_vernier_fastapi_app`).
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        host (str, optional): bind address. Defaults to `"127.0.0.1"`.
        base_port (int, optional): first TCP port. Defaults to the runtime fallback.
        workers (int, optional): worker count for the multiprocess mode. Defaults to the runtime fallback.
        ready_timeout_s (float, optional): per-spawner readiness timeout. Defaults to the runtime fallback.
        adapter_factory (AdapterFactory | None, optional): callable returning a fresh `ServerAdapter` per spawner. Defaults to None, which uses the real `make_server_adapter`. Tests inject a fake.

    Yields:
        list[str]: target URLs for the mounted spawners (one per port). Caller drives the rate sweep against these URLs.

    Raises:
        ValueError: if `dpl` is not a recognised mode.
        NotImplementedError: if `dpl="remote"` (not yet wired).
    """
    _ports = _resolve_ports(dpl, base_port, workers)
    _spawners: list[ServerAdapter] = []
    _urls: list[str] = []
    try:
        for _port in _ports:
            if adapter_factory is None:
                _adp = make_server_adapter(framework, wsgi_server)
            else:
                _adp = adapter_factory()
            _adp.mount(app_factory, port=_port, host=host)
            _spawners.append(_adp)
            _urls.append(f"http://{host}:{_port}")
        for _adp in _spawners:
            _adp.wait_ready(timeout_s=ready_timeout_s)
        yield _urls
    finally:
        for _adp in _spawners:
            _adp.shutdown()


def _resolve_ports(dpl: Dpl, base_port: int, workers: int) -> list[int]:
    """Resolve the list of TCP ports to bind for the given deployment mode.

    Args:
        dpl (Dpl): deployment mode.
        base_port (int): first port.
        workers (int): worker count for the multiprocess mode.

    Returns:
        list[int]: ports to bind, in order.

    Raises:
        ValueError: if `dpl` is not recognised.
        NotImplementedError: if `dpl="remote"` (not yet wired).
    """
    _ans: list[int]
    if dpl == "localhost":
        _ans = [base_port]
    elif dpl == "multiprocess":
        _ans = [base_port + _i for _i in range(workers)]
    elif dpl == "remote":
        _msg = "remote dpl is not yet wired"
        raise NotImplementedError(_msg)
    else:
        _msg = f"unknown dpl {dpl!r}; expected 'localhost', 'multiprocess', or 'remote'"
        raise ValueError(_msg)
    return _ans


__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "WsgiServer",
    "bring_up",
]
