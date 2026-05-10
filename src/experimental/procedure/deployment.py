"""Mount HTTP spawners as context managers; yield their URLs.

Two helpers, both `mount -> wait_ready -> yield -> shutdown` context managers:

- `bring_up`: one app on N ports (calibration vernier).
- `bring_up_mesh`: N apps on N ports (TAS service mesh).

Three deployment modes: `localhost` (one process), `multiprocess` (N processes on consecutive ports), `remote` (reserved). Tests pass `adapter_factory` to skip real spawning.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MeshSpec:
    """One mesh entry: an id paired with the factory that builds its app.

    Attributes:
        svc_id (str): catalogue key (e.g. `MAS_{1}`, `TAS`).
        app_factory (AppFactory): zero-arg picklable callable returning the app.
    """

    svc_id: str
    app_factory: AppFactory

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
    """Mount one app on N ports for `dpl`; yield URLs while the body runs.

    `localhost` mounts one spawner; `multiprocess` mounts `workers` copies of the same app on consecutive ports.

    Args:
        dpl (Dpl): deployment mode.
        app_factory (AppFactory): zero-arg picklable callable returning the app.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        host (str, optional): bind address. Defaults to `"127.0.0.1"`.
        base_port (int, optional): first TCP port.
        workers (int, optional): spawner count for `multiprocess`.
        ready_timeout_s (float, optional): per-spawner readiness timeout.
        adapter_factory (AdapterFactory | None, optional): test seam; defaults to the real adapter.

    Yields:
        list[str]: one base URL per spawner.

    Raises:
        ValueError: unknown `dpl`.
        NotImplementedError: `dpl="remote"` (not yet wired).
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
    """Pick which TCP ports to bind for the given mode.

    Args:
        dpl (Dpl): deployment mode.
        base_port (int): first port.
        workers (int): spawner count for `multiprocess`.

    Returns:
        list[int]: ports in mounting order.

    Raises:
        ValueError: unknown `dpl`.
        NotImplementedError: `dpl="remote"` (not yet wired).
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


@contextmanager
def bring_up_mesh(specs: list[MeshSpec],
                  *,
                  framework: Framework = "fastapi",
                  wsgi_server: WsgiServer = "waitress",
                  host: str = "127.0.0.1",
                  base_port: int = _DFLT_BASE_PORT,
                  ready_timeout_s: float = _DFLT_READY_TIMEOUT_S,
                  adapter_factory: AdapterFactory | None = None) -> Iterator[dict[str, str]]:
    """Mount one spawner per spec on consecutive ports; yield a `svc_id -> URL` map.

    Specs mount in order on `base_port + i`. The helper waits for every spawner to pass its readiness probe before yielding; exits shut down spawners in reverse order. Each spawner runs one process (`mount` is one-process-per-adapter); duplicate specs on consecutive ports if you need multiple workers per service.

    Args:
        specs (list[MeshSpec]): mesh entries in mounting order.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        host (str, optional): bind address. Defaults to `"127.0.0.1"`.
        base_port (int, optional): first TCP port.
        ready_timeout_s (float, optional): per-spawner readiness timeout.
        adapter_factory (AdapterFactory | None, optional): test seam.

    Yields:
        dict[str, str]: `svc_id -> base URL` for every mounted spawner.

    Raises:
        ValueError: when `specs` is empty.
    """
    if not specs:
        _msg = "bring_up_mesh requires at least one MeshSpec"
        raise ValueError(_msg)
    _spawners: list[ServerAdapter] = []
    _urls: dict[str, str] = {}
    try:
        for _idx, _spec in enumerate(specs):
            _port = base_port + _idx
            if adapter_factory is None:
                _adp = make_server_adapter(framework, wsgi_server)
            else:
                _adp = adapter_factory()
            _adp.mount(_spec.app_factory, port=_port, host=host)
            _spawners.append(_adp)
            _urls[_spec.svc_id] = f"http://{host}:{_port}"
        for _adp in _spawners:
            _adp.wait_ready(timeout_s=ready_timeout_s)
        yield _urls
    finally:
        for _adp in reversed(_spawners):
            _adp.shutdown()


__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "MeshSpec",
    "WsgiServer",
    "bring_up",
    "bring_up_mesh",
]
