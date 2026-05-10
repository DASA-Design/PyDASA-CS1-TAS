"""Tests for `src.experimental.prototype.target.factory.tas`.

**TestTasFactory**:

- `test_full_topology_round_trip`: build TAS over an in-memory mesh of 7 atomic ASGI apps; an end-to-end POST returns 200 with a populated `workflow.steps` audit trail; the JSONL flow record lands on disk.
- `test_healthz`: GET `/healthz` returns 200 with `{"status": "ok"}`.

The mesh is in-process: each "atomic endpoint" is its own ASGI app wired through a per-endpoint `httpx.AsyncClient` mount inside the composite's `ServiceClient`. We do not boot uvicorn; the smoke spawn-process path is exercised by `tests/demo/composite.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.factory.tas import build_tas_fastapi_app
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)


class _MeshTransport(httpx.AsyncBaseTransport):
    """Route each request to the right per-host ASGI transport based on the request URL.

    The composite holds endpoints like `http://127.0.0.1:8002`; we mount one ASGI transport per endpoint and dispatch by host:port. Used only for the in-process round-trip test.
    """

    def __init__(self, host_to_transport: dict[str, httpx.ASGITransport]) -> None:
        self._lt = host_to_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _key = f"{request.url.host}:{request.url.port}"
        _t = self._lt.get(_key)
        if _t is None:
            _msg = f"no transport for {_key!r}"
            raise httpx.ConnectError(_msg)
        return await _t.handle_async_request(request)


def _build_mesh_transport(catalogue_ids: list[str]) -> tuple[
    dict[str, str],
    _MeshTransport,
]:
    """Build (`endpoint_lt`, transport) routing per-host requests to one ASGI app each.

    Args:
        catalogue_ids (list[str]): atomic ids to mount.

    Returns:
        tuple: (mapping `svc_id -> URL`, transport that dispatches by host:port).
    """
    _endpoints: dict[str, str] = {}
    _routes: dict[str, httpx.ASGITransport] = {}
    for _i, _svc_id in enumerate(catalogue_ids, start=1):
        _host = f"127.0.0.1:{8000 + _i}"
        _kind = _kind_from_svc_id(_svc_id)
        _app = build_atomic_fastapi_app(svc_name=_svc_id,
                                        kind=_kind,
                                        mu=0.0)
        _endpoints[_svc_id] = f"http://{_host}"
        _routes[_host] = httpx.ASGITransport(app=_app)
    return _endpoints, _MeshTransport(_routes)


def _kind_from_svc_id(svc_id: str) -> str:
    """Return the catalogue kind for a Weyns 2015 atomic id (`AS_*` / `MAS_*` / `DS_*`)."""
    if svc_id.startswith("AS"):
        return "alarm"
    if svc_id.startswith("MAS"):
        return "medical_analysis"
    return "drug"


class TestTasFactory:
    """Composite factory over the mesh transport."""

    @pytest.mark.asyncio
    async def test_full_topology_round_trip(self,
                                            tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_full_topology_round_trip()* POSTing a `kind='alarm'` request to TAS dispatches to one alarm atomic and writes one JSONL flow record."""
        _ids = ["AS_{1}", "AS_{2}", "AS_{3}",
                "MAS_{1}", "MAS_{2}", "MAS_{3}",
                "DS_{3}"]
        _endpoint_lt, _mesh_transport = _build_mesh_transport(_ids)

        # Patch httpx.AsyncClient so the composite's ServiceClient picks up the mesh transport.
        _orig_async_client = httpx.AsyncClient

        class _PatchedAsyncClient(_orig_async_client):
            def __init__(_self, *args: Any, **kwargs: Any) -> None:  # noqa: N805
                if kwargs.get("transport") is None:
                    kwargs["transport"] = _mesh_transport
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("src.experimental.prototype.target.service.client.httpx.AsyncClient",
                            _PatchedAsyncClient)

        _flows_path = tmp_path / "flows.jsonl"
        _app = build_tas_fastapi_app(endpoint_lt=_endpoint_lt,
                                     flows_path=str(_flows_path),
                                     run_id="rid-test")
        _tas_transport = make_test_transport(_app, "fastapi")
        async with _app.router.lifespan_context(_app):
            async with httpx.AsyncClient(transport=_tas_transport,
                                         base_url="http://tas") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "kind": "alarm",
                                                    "client_id": "u-0",
                                                    "submitted_ts": 0.0})
        assert _resp.status_code == 200
        _body = _resp.json()
        _steps = _body["workflow"]["steps"]
        assert len(_steps) == 1
        assert _steps[0]["svc_id"].startswith("AS_")
        assert _flows_path.exists()
        _line = _flows_path.read_text(encoding="utf-8").splitlines()[0]
        assert "r0" in _line

    @pytest.mark.asyncio
    async def test_healthz(self) -> None:
        """*test_healthz()* `GET /healthz` returns 200 with `{"status": "ok"}` regardless of the mesh state."""
        _app = build_tas_fastapi_app(endpoint_lt={})
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://tas") as _http:
            _resp = await _http.get("/healthz")
        assert _resp.status_code == 200
        assert _resp.json() == {"status": "ok"}
