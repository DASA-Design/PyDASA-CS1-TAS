"""Build the composite TAS FastAPI app.

The composite app exposes:

- `POST /`: receives client requests; the workflow engine drives one or two atomic dispatches via a per-app `ServiceClient` over a `ServiceCache`. One JSONL record per request lands in `<flows_path>`.
- `GET /healthz`: readiness probe.

The `ServiceCache` is built at app construction time from the `endpoint_lt` mapping (`svc_id -> base URL`). FastAPI's `lifespan` owns the `ServiceClient`: the underlying `httpx.AsyncClient` opens once on startup and closes on shutdown; the JSONL writer is closed on shutdown.

The factory is top-level and `functools.partial`-bindable so it pickles across `multiprocessing.spawn` on Windows.
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.experimental.common.io.jsonl import JsonlWriter
from src.experimental.common.registry.cache import ServiceCache
from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import ServiceRegistry
from src.experimental.prototype.target.factory.healthz import add_healthz_route
from src.experimental.prototype.target.service.catalogue import (
    ServiceCatalogue,
    load_catalogue,
)
from src.experimental.prototype.target.service.client import (
    DFLT_TIMEOUT_S,
    ServiceClient,
)
from src.experimental.prototype.target.service.composite import CompositeService
from src.experimental.prototype.target.workflow.engine import WorkflowEngine
from src.experimental.prototype.target.workflow.loader import (
    DFLT_WORKFLOW_NAME,
    load_workflow,
)


def _filter_catalogue_to_mesh(catalogue: ServiceCatalogue,
                              endpoint_lt: dict[str, str]) -> ServiceCatalogue:
    """Return a new catalogue restricted to entries the active mesh actually spawned.

    The on-disk catalogue layer (e.g. `weyns_iftikhar_2016`) lists every service across all adp scenarios. The active mesh only spawns the services declared in the active profile (e.g. baseline gets DS_{3}; s2 gets DS_{1}). Without this filter, `catalogue.by_kind` would happily return services the cache can't reach and the picker would hand them to `ServiceClient.invoke_operation` which then raises `UnknownServiceError`.

    Args:
        catalogue (ServiceCatalogue): full on-disk catalogue.
        endpoint_lt (dict[str, str]): `svc_id -> URL` map of the active third-party mesh.

    Returns:
        ServiceCatalogue: same `name` / `source`, but `entries` filtered to ids in `endpoint_lt`.
    """
    _filtered = {_id: _entry for _id, _entry in catalogue.entries.items()
                 if _id in endpoint_lt}
    _ans = ServiceCatalogue(name=catalogue.name,
                            source=catalogue.source,
                            entries=_filtered)
    return _ans


def _build_registry(endpoint_lt: dict[str, str]) -> ServiceRegistry:
    """Build a `ServiceRegistry` from a `svc_id -> endpoint URL` mapping.

    Args:
        endpoint_lt (dict[str, str]): each entry registers one atomic.

    Returns:
        ServiceRegistry: populated registry.
    """
    _reg = ServiceRegistry()
    for _svc_id, _endpoint in endpoint_lt.items():
        _reg.register_service(ServiceDescription(_id=_svc_id,
                                                 name=_svc_id,
                                                 endpoint=_endpoint))
    return _reg


def _write_flow_record(*,
                       writer: JsonlWriter,
                       payload: dict[str, Any],
                       body: dict[str, Any],
                       status: int,
                       t_start: float,
                       t_end: float,
                       run_id: str | None) -> None:
    """Append one JSONL flow record summarising a client-to-TAS round trip.

    Args:
        writer (JsonlWriter): open JSONL writer.
        payload (dict[str, Any]): inbound request body.
        body (dict[str, Any]): final response body (includes `workflow.steps`).
        status (int): final HTTP status code.
        t_start (float): server-side timestamp before workflow execution.
        t_end (float): server-side timestamp after workflow execution.
        run_id (str | None): run identifier; written into the record.
    """
    _steps = (body or {}).get("workflow", {}).get("steps", [])
    _record: dict[str, Any] = {
        "req_id": payload.get("req_id", ""),
        "kind": payload.get("kind", ""),
        "client_id": payload.get("client_id", ""),
        "submitted_ts": payload.get("submitted_ts", t_start),
        "tas_recv_ts": t_start,
        "tas_send_ts": t_end,
        "total_latency_s": t_end - t_start,
        "status": status,
        "inject_failure": payload.get("inject_failure"),
        "run_id": run_id,
        "pid": os.getpid(),
        "steps": _steps,
    }
    writer.write(_record)


def build_tas_fastapi_app(*,
                          endpoint_lt: dict[str, str],
                          catalogue_version: str | None = None,
                          workflow_name: str = DFLT_WORKFLOW_NAME,
                          flows_path: str | None = None,
                          run_id: str | None = None,
                          timeout_s: float = DFLT_TIMEOUT_S,
                          internal_endpoint_lt: dict[str, str] | None = None) -> FastAPI:
    """Build the composite TAS FastAPI app over a fixed atomic-endpoint mesh.

    Args:
        endpoint_lt (dict[str, str]): mapping `svc_id -> base URL` for the third-party atomics.
        catalogue_version (str | None, optional): version layer of `external_services.json` to load. Defaults to None (reads `_setpoint`).
        workflow_name (str, optional): workflow stem to load. Defaults to `tas` (collapsed); pass `tas_expanded` for expanded mode.
        flows_path (str | None, optional): JSONL path for per-request flow records (string for picklability). Defaults to None.
        run_id (str | None, optional): run identifier written into every flow record. Defaults to None.
        timeout_s (float, optional): per-dispatch HTTP timeout. Defaults to `DFLT_TIMEOUT_S`.
        internal_endpoint_lt (dict[str, str] | None, optional): mapping `svc_id -> base URL` for the internal-stage atomics (`TAS_{2..6}`); None in collapsed mode. When set, the `ServiceCache` carries both maps so the engine can dispatch by either step-form.

    Returns:
        FastAPI: configured composite app with `POST /` and `GET /healthz`.
    """
    _all_endpoints: dict[str, str] = dict(endpoint_lt)
    if internal_endpoint_lt is not None:
        _all_endpoints.update(internal_endpoint_lt)
    _registry = _build_registry(_all_endpoints)
    _cache = ServiceCache(_registry)
    _catalogue = _filter_catalogue_to_mesh(load_catalogue(catalogue_version), endpoint_lt)
    _workflow_spec = load_workflow(workflow_name)
    _engine = WorkflowEngine(spec=_workflow_spec, catalogue=_catalogue)
    if flows_path is None:
        _flows_writer: JsonlWriter | None = None
    else:
        _flows_writer = JsonlWriter(Path(flows_path))

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the dispatch client and composite on startup; close them on shutdown.

        The `ServiceClient` is opened inside an `async with` block so the underlying `httpx.AsyncClient` stays alive for every request handled by `POST /`. On shutdown the client closes first (exiting `async with`), then the JSONL writer flushes and closes.

        Args:
            app (FastAPI): the app being started; `app.state.composite` is populated for `_post_root` to read.

        Yields:
            None: control returns to FastAPI while the app serves requests.
        """
        _client = ServiceClient(client_id="TAS",
                                cache=_cache,
                                timeout_s=timeout_s)
        async with _client:
            app.state.composite = CompositeService(service_name="TAS",
                                                   workflow=_engine,
                                                   client=_client)
            yield
        if _flows_writer is not None:
            _flows_writer.close()

    _app = FastAPI(lifespan=_lifespan)
    add_healthz_route(_app)

    async def _post_root(payload: dict[str, Any]) -> JSONResponse:
        """POST `/`: drive the workflow, write one flow record, return the workflow response.

        Args:
            payload (dict[str, Any]): inbound client request body.

        Returns:
            JSONResponse: workflow body + status returned by `CompositeService.invoke_operation`.
        """
        _composite: CompositeService = _app.state.composite
        _t_start = time.time()
        _body, _status = await _composite.invoke_operation(payload)
        _t_end = time.time()
        if _flows_writer is not None:
            _write_flow_record(writer=_flows_writer,
                               payload=payload,
                               body=_body,
                               status=_status,
                               t_start=_t_start,
                               t_end=_t_end,
                               run_id=run_id)
        return JSONResponse(content=_body, status_code=_status)

    _app.add_api_route("/", _post_root, methods=["POST"])
    return _app


__all__ = [
    "build_tas_fastapi_app",
]
