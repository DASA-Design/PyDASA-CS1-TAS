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

from src.experimental.prototype.runtime.ports import pick_free_port
from src.experimental.prototype.runtime.server import (
    ServerAdapter,
    make_server_adapter,
)

Dpl = Literal["localhost", "multiprocess", "remote"]
Framework = Literal["fastapi", "flask"]
WsgiServer = Literal["waitress", "gunicorn"]
Granularity = Literal["collapsed", "expanded"]
AppFactory = Callable[[], Any]
AdapterFactory = Callable[[], ServerAdapter]


@dataclass(frozen=True)
class MeshSpec:
    """One mesh entry: an id paired with the factory that builds its app.

    `workers` defaults to 1 (one process per service); set higher to spawn multiple uvicorn / waitress workers on consecutive ports behind the same logical service id. `bring_up_mesh` yields a `dict[svc_id, list[str]]` of worker URLs; downstream registries / caches treat the list as the worker set the client should round-robin across.

    Attributes:
        svc_id (str): catalogue key (e.g. `MAS_{1}`, `TAS`).
        app_factory (AppFactory): zero-arg picklable callable returning the app.
        workers (int): number of worker processes to spawn for this service. Defaults to 1.
    """

    svc_id: str
    app_factory: AppFactory
    workers: int = 1

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
                  adapter_factory: AdapterFactory | None = None) -> Iterator[dict[str, list[str]]]:
    """Mount each spec's app on `spec.workers` consecutive ports; yield a `svc_id -> [URL, ...]` map.

    Total port count = `sum(spec.workers for spec in specs)`. The helper picks a contiguous block large enough to hold every worker, then assigns each spec `workers` consecutive ports starting at the running offset. Waits for every spawner to pass its readiness probe before yielding; on exit, spawners shut down in reverse order.

    Args:
        specs (list[MeshSpec]): mesh entries in mounting order; each spec may carry `workers > 1`.
        framework (Framework, optional): server stack. Defaults to `"fastapi"`.
        wsgi_server (WsgiServer, optional): WSGI engine when `framework="flask"`. Defaults to `"waitress"`.
        host (str, optional): bind address. Defaults to `"127.0.0.1"`.
        base_port (int, optional): first TCP port.
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
    _total_workers = sum(max(1, _spec.workers) for _spec in specs)
    _effective_base = _find_contiguous_block(host=host,
                                             start_port=base_port,
                                             n_ports=_total_workers)
    _spawners: list[ServerAdapter] = []
    _urls: dict[str, list[str]] = {}
    try:
        _offset = 0
        for _spec in specs:
            _n_workers = max(1, _spec.workers)
            _spec_urls: list[str] = []
            for _wi in range(_n_workers):
                _port = _effective_base + _offset + _wi
                if adapter_factory is None:
                    _adp = make_server_adapter(framework, wsgi_server)
                else:
                    _adp = adapter_factory()
                _adp.mount(_spec.app_factory, port=_port, host=host)
                _spawners.append(_adp)
                _spec_urls.append(f"http://{host}:{_port}")
            _urls[_spec.svc_id] = _spec_urls
            _offset += _n_workers
        for _adp in _spawners:
            _adp.wait_ready(timeout_s=ready_timeout_s)
        yield _urls
    finally:
        for _adp in reversed(_spawners):
            _adp.shutdown()


def _find_contiguous_block(*,
                           host: str,
                           start_port: int,
                           n_ports: int,
                           max_blocks: int = 8) -> int:
    """Pick the first start port whose `[start, start + n_ports)` window is fully bindable.

    Used to relocate the whole mesh in one shift when the canonical block is held (TIME_WAIT after a prior iteration, an orphan, etc.). Probes each candidate block by walking it; the first port that fails to bind disqualifies that block.

    Args:
        host (str): bind address.
        start_port (int): preferred first port.
        n_ports (int): block size.
        max_blocks (int, optional): how many `n_ports`-aligned blocks to try (canonical, then shifted up by `n_ports` each step). Defaults to 8.

    Returns:
        int: a `start` such that ports `start..start+n_ports-1` are all bindable.

    Raises:
        RuntimeError: when no clean block is found after `max_blocks` attempts.
    """
    for _block in range(max_blocks):
        _candidate_base = start_port + _block * n_ports
        try:
            for _offset in range(n_ports):
                pick_free_port(host=host,
                               start_port=_candidate_base + _offset,
                               max_skip=1)
        except RuntimeError:
            continue
        return _candidate_base
    _msg = (f"no contiguous {n_ports}-port block found starting at {host}:{start_port} "
            f"after {max_blocks} attempts; orphaned processes may be hoarding the range.")
    raise RuntimeError(_msg)


__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "Granularity",
    "MeshSpec",
    "WsgiServer",
    "bring_up",
    "bring_up_mesh",
]
