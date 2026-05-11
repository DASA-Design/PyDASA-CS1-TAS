"""Build the composite TAS FastAPI app.

The composite app exposes:

- `POST /`: receives client requests; the workflow engine drives one or two atomic dispatches via a per-app `ServiceClient` over a `ServiceCache`. One JSONL record per request lands in `<flows_path>`. After the response, the handler appends one sample to `app.state.recent_samples` for the controller to pull.
- `GET /samples?since=<offset>`: returns samples appended since the caller's last offset (pull-style probe for the MAPE-K controller).
- `POST /config`: accepts `{picker_name, op_weights, max_attempts, window_size}` and installs the corresponding strategy picker on the live workflow engine.
- `GET /healthz`: readiness probe.

The `ServiceCache` is built at app construction time from the `endpoint_lt` mapping (`svc_id -> base URL`). FastAPI's `lifespan` owns the `ServiceClient`: the underlying `httpx.AsyncClient` opens once on startup and closes on shutdown; the JSONL writer is closed on shutdown.

The factory is top-level and `functools.partial`-bindable so it pickles across `multiprocessing.spawn` on Windows.
"""

from __future__ import annotations

import os
import time
from collections import deque
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
from src.experimental.prototype.controller.strategies import picker_from_wire
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

DFLT_SAMPLES_BUFFER_SIZE = 1024


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


def _append_sample(*,
                   app: FastAPI,
                   req_id: str,
                   status: int,
                   total_latency_s: float,
                   ts: float) -> None:
    """Append one probe sample to `app.state.recent_samples` and bump the offset counter.

    Args:
        app (FastAPI): the composite app holding the buffer.
        req_id (str): request identifier.
        status (int): final HTTP status of the response.
        total_latency_s (float): server-side total latency of the request.
        ts (float): epoch-seconds timestamp at the end of the response.
    """
    app.state.sample_offset += 1
    _record: dict[str, Any] = {
        "offset": app.state.sample_offset,
        "req_id": req_id,
        "status": status,
        "total_latency_s": total_latency_s,
        "ts": ts,
    }
    app.state.recent_samples.append(_record)


class TasRoutes:
    """FastAPI route adapter binding TAS_1's composite app to its three HTTP endpoints.

    Holds the per-app immutable settings (run_id, flow writer, picker knobs) so the route methods stay pickle-friendly and FastAPI's signature introspection works cleanly.
    """

    def __init__(self,
                 *,
                 app: FastAPI,
                 run_id: str | None,
                 flows_writer: JsonlWriter | None) -> None:
        """Configure the routes.

        Args:
            app (FastAPI): the composite app; mutated state lives on `app.state`.
            run_id (str | None): run identifier copied into each flow record.
            flows_writer (JsonlWriter | None): per-request JSONL writer; None disables the side-effect.
        """
        self._app = app
        self._run_id = run_id
        self._flows_writer = flows_writer

    async def post_root(self, payload: dict[str, Any]) -> JSONResponse:
        """POST `/`: drive the workflow, write the flow record, push a sample to the buffer, return the response.

        Args:
            payload (dict[str, Any]): inbound client request body.

        Returns:
            JSONResponse: workflow body + status returned by `CompositeService.invoke_operation`.
        """
        _composite: CompositeService = self._app.state.composite
        _t_start = time.time()
        _body, _status = await _composite.invoke_operation(payload)
        _t_end = time.time()
        if self._flows_writer is not None:
            _write_flow_record(writer=self._flows_writer,
                               payload=payload,
                               body=_body,
                               status=_status,
                               t_start=_t_start,
                               t_end=_t_end,
                               run_id=self._run_id)
        _append_sample(app=self._app,
                       req_id=str(payload.get("req_id", "")),
                       status=_status,
                       total_latency_s=_t_end - _t_start,
                       ts=_t_end)
        return JSONResponse(content=_body, status_code=_status)

    async def get_samples(self, since: int = 0) -> dict[str, Any]:
        """GET `/samples?since=<offset>`: return samples appended after `since`.

        Args:
            since (int, optional): caller's last seen offset. Defaults to 0.

        Returns:
            dict[str, Any]: `{records: [...], next_offset: <int>}`. `next_offset` is the current `app.state.sample_offset`; the caller passes it back on the next poll.
        """
        _samples: deque[dict[str, Any]] = self._app.state.recent_samples
        _records = [_s for _s in _samples if _s.get("offset", 0) > since]
        _ans: dict[str, Any] = {
            "records": _records,
            "next_offset": self._app.state.sample_offset,
        }
        return _ans

    async def post_config(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST `/config`: install a new picker on the live workflow engine.

        The controller calls this once at trial start with the run's `adp`-derived picker. Idempotent at the behaviour level: re-posting the same config rebuilds the picker but the dispatch outcome stays the same.

        Args:
            body (dict[str, Any]): `{picker_name, op_weights, max_attempts, window_size}`.

        Returns:
            dict[str, Any]: `{"applied": True, "picker_name": <name>}`.
        """
        _picker_name = str(body.get("picker_name", "first_of_kind"))
        _op_weights = body.get("op_weights") or {}
        _max_attempts = int(body.get("max_attempts", 1))
        _window_size = int(body.get("window_size", 100))
        _picker = picker_from_wire(_picker_name,
                                   op_weights=_op_weights,
                                   max_attempts=_max_attempts,
                                   window_size=_window_size)
        _composite: CompositeService = self._app.state.composite
        _composite.workflow.picker = _picker
        return {"applied": True, "picker_name": _picker_name}


@asynccontextmanager
async def _tas_lifespan_factory(app: FastAPI,
                                *,
                                cache: ServiceCache,
                                engine: WorkflowEngine,
                                timeout_s: float,
                                samples_buffer_size: int,
                                flows_writer: JsonlWriter | None) -> AsyncIterator[None]:
    """Open the dispatch client and composite on startup; close them on shutdown.

    Initialises `app.state.recent_samples` (rolling sample buffer the controller pulls) and `app.state.sample_offset` (monotonically-increasing counter for `?since=` lookups), then opens the `ServiceClient` inside `async with` so its `httpx.AsyncClient` lives across requests.

    Args:
        app (FastAPI): the app being started; `app.state.composite`, `recent_samples`, and `sample_offset` are populated for the route handlers.
        cache (ServiceCache): the resolved svc-id-to-endpoint cache.
        engine (WorkflowEngine): the workflow engine driving dispatch.
        timeout_s (float): per-dispatch HTTP timeout.
        samples_buffer_size (int): max records retained in `recent_samples`.
        flows_writer (JsonlWriter | None): writer to close on shutdown; None when no JSONL output is configured.

    Yields:
        None: control returns to FastAPI while the app serves requests.
    """
    _client = ServiceClient(client_id="TAS", cache=cache, timeout_s=timeout_s)
    app.state.recent_samples = deque(maxlen=samples_buffer_size)
    app.state.sample_offset = 0
    async with _client:
        app.state.composite = CompositeService(service_name="TAS",
                                               workflow=engine,
                                               client=_client)
        yield
    if flows_writer is not None:
        flows_writer.close()


def build_tas_fastapi_app(*,
                          endpoint_lt: dict[str, str],
                          catalogue_version: str | None = None,
                          workflow_name: str = DFLT_WORKFLOW_NAME,
                          flows_path: str | None = None,
                          run_id: str | None = None,
                          timeout_s: float = DFLT_TIMEOUT_S,
                          internal_endpoint_lt: dict[str, str] | None = None,
                          samples_buffer_size: int = DFLT_SAMPLES_BUFFER_SIZE) -> FastAPI:
    """Build the composite TAS FastAPI app over a fixed atomic-endpoint mesh.

    Args:
        endpoint_lt (dict[str, str]): mapping `svc_id -> base URL` for the third-party atomics.
        catalogue_version (str | None, optional): version layer of `external_services.json` to load. Defaults to None (reads `_setpoint`).
        workflow_name (str, optional): workflow stem to load. Defaults to `tas` (collapsed); pass `tas_expanded` for expanded mode.
        flows_path (str | None, optional): JSONL path for per-request flow records (string for picklability). Defaults to None.
        run_id (str | None, optional): run identifier written into every flow record. Defaults to None.
        timeout_s (float, optional): per-dispatch HTTP timeout. Defaults to `DFLT_TIMEOUT_S`.
        internal_endpoint_lt (dict[str, str] | None, optional): mapping `svc_id -> base URL` for the internal-stage atomics (`TAS_{2..6}`); None in collapsed mode. When set, the `ServiceCache` carries both maps so the engine can dispatch by either step-form.
        samples_buffer_size (int, optional): max records retained in `app.state.recent_samples`. The controller pulls them via `GET /samples`. Defaults to `DFLT_SAMPLES_BUFFER_SIZE` (1024).

    Returns:
        FastAPI: configured composite app with `POST /`, `GET /samples`, `POST /config`, and `GET /healthz`.
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

    def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        return _tas_lifespan_factory(app,
                                     cache=_cache,
                                     engine=_engine,
                                     timeout_s=timeout_s,
                                     samples_buffer_size=samples_buffer_size,
                                     flows_writer=_flows_writer)

    _app = FastAPI(lifespan=_lifespan)
    _routes = TasRoutes(app=_app, run_id=run_id, flows_writer=_flows_writer)
    add_healthz_route(_app)
    _app.add_api_route("/", _routes.post_root, methods=["POST"])
    _app.add_api_route("/samples", _routes.get_samples, methods=["GET"])
    _app.add_api_route("/config", _routes.post_config, methods=["POST"])
    return _app


__all__ = [
    "DFLT_SAMPLES_BUFFER_SIZE",
    "TasRoutes",
    "build_tas_fastapi_app",
]
