"""Mount HTTP spawners as context managers; yield their URLs.

Two helpers, both `mount -> wait_ready -> yield -> shutdown` context managers:

- `bring_up`: one app on N ports (calibration vernier).
- `bring_up_mesh`: N apps on N ports (TAS service mesh).

Ports sit on a `PORT_STRIDE` grid (`base_port`, `+PORT_STRIDE`, `+2*PORT_STRIDE`, ...) so each service has breathing room and the layout reads as round numbers. Three deployment modes: `localhost` (one process), `multiprocess` (N processes on the strided grid), `remote` (reserved). Tests pass `adapter_factory` to skip real spawning.

Each real bring-up records its ports in the spawn registry (`runtime.sockets`) and reaps any orphan a prior crash left behind; tests that pass `adapter_factory` skip that bookkeeping.
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
from src.experimental.prototype.runtime.sockets import PortRegistry

Dpl = Literal["localhost", "multiprocess", "remote"]
Framework = Literal["fastapi", "flask"]
WsgiServer = Literal["waitress", "gunicorn"]
Granularity = Literal["collapsed", "expanded"]
AppFactory = Callable[[], Any]
AdapterFactory = Callable[[], ServerAdapter]

# Spacing between consecutive services / spawners on the port grid. Each service
# owns a PORT_STRIDE-wide slot; a multi-worker service takes consecutive ports
# inside its own slot (so up to PORT_STRIDE workers per service).
PORT_STRIDE = 20


@dataclass(frozen=True)
class MeshSpec:
    """One mesh entry: an id paired with the factory that builds its app.

    `workers` defaults to 1 (one process per service); set higher to spawn multiple uvicorn / waitress workers behind the same logical service id, on consecutive ports inside this service's `PORT_STRIDE` slot. `bring_up_mesh` yields a `dict[svc_id, list[str]]` of worker URLs; downstream registries / caches treat the list as the worker set the client should round-robin across.

    Attributes:
        svc_id (str): catalogue key (e.g. `MAS_{1}`, `TAS`).
        app_factory (AppFactory): zero-arg picklable callable returning the app.
        workers (int): number of worker processes to spawn for this service. Defaults to 1.
    """

    svc_id: str
    app_factory: AppFactory
    workers: int = 1

# Runtime fallbacks for data/config/method/experimental.json::dpl.*.
_DFLT_BASE_PORT = 8000
_DFLT_WORKERS = 4
_DFLT_READY_TIMEOUT_S = 20.0

# Shared spawn registry: every real bring-up reaps prior crash debris, records
# its ports, and releases them on clean shutdown.
_REGISTRY = PortRegistry()


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

    `localhost` mounts one spawner; `multiprocess` mounts `workers` copies of the same app on the `PORT_STRIDE` grid.

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
    _real = adapter_factory is None
    if _real:
        _REGISTRY.reap()
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
        if _real:
            _REGISTRY.register(_ports)
        yield _urls
    finally:
        for _adp in _spawners:
            _adp.shutdown()
        if _real:
            _REGISTRY.release(_ports)


def _resolve_ports(dpl: Dpl, base_port: int, workers: int) -> list[int]:
    """Pick which TCP ports to bind for the given mode.

    Args:
        dpl (Dpl): deployment mode.
        base_port (int): first port.
        workers (int): spawner count for `multiprocess`.

    Returns:
        list[int]: ports in mounting order, spaced by `PORT_STRIDE` for `multiprocess`.

    Raises:
        ValueError: unknown `dpl`.
        NotImplementedError: `dpl="remote"` (not yet wired).
    """
    _ans: list[int]
    if dpl == "localhost":
        _ans = [base_port]
    elif dpl == "multiprocess":
        _ans = [base_port + _i * PORT_STRIDE for _i in range(workers)]
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
                  adapter_factory: AdapterFactory | None = None) -> Iterator[dict[str, list[str]]]:
    """Mount each spec's app on the `PORT_STRIDE` grid; yield a `svc_id -> [URL, ...]` map.

    Spec `i` (in list order) owns the slot starting at `base_port + i * PORT_STRIDE`; its workers take consecutive ports inside that slot. Waits for every spawner to pass its readiness probe before yielding; on exit, spawners shut down in reverse order.

    Args:
        specs (list[MeshSpec]): mesh entries in mounting order; each spec may carry `workers > 1`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        host (str, optional): bind address. Defaults to `"127.0.0.1"`.
        base_port (int, optional): first TCP port (the TAS slot).
        ready_timeout_s (float, optional): per-spawner readiness timeout.
        adapter_factory (AdapterFactory | None, optional): test seam.

    Yields:
        dict[str, list[str]]: `svc_id -> list of base URLs`. The list has one entry per worker; a single-worker spec yields a single-element list.

    Raises:
        ValueError: when `specs` is empty.
    """
    if not specs:
        _msg = "bring_up_mesh requires at least one MeshSpec"
        raise ValueError(_msg)
    _real = adapter_factory is None
    if _real:
        _REGISTRY.reap()
    _spawners: list[ServerAdapter] = []
    _urls: dict[str, list[str]] = {}
    _all_ports: list[int] = []
    try:
        for _idx, _spec in enumerate(specs):
            _slot_base = base_port + _idx * PORT_STRIDE
            _n_workers = max(1, _spec.workers)
            _spec_urls: list[str] = []
            for _wi in range(_n_workers):
                _port = _slot_base + _wi
                if adapter_factory is None:
                    _adp = make_server_adapter(framework, wsgi_server)
                else:
                    _adp = adapter_factory()
                _adp.mount(_spec.app_factory, port=_port, host=host)
                _spawners.append(_adp)
                _spec_urls.append(f"http://{host}:{_port}")
                _all_ports.append(_port)
            _urls[_spec.svc_id] = _spec_urls
        for _adp in _spawners:
            _adp.wait_ready(timeout_s=ready_timeout_s)
        if _real:
            _REGISTRY.register(_all_ports)
        yield _urls
    finally:
        for _adp in reversed(_spawners):
            _adp.shutdown()
        if _real:
            _REGISTRY.release(_all_ports)


__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "Granularity",
    "MeshSpec",
    "PORT_STRIDE",
    "WsgiServer",
    "bring_up",
    "bring_up_mesh",
]
