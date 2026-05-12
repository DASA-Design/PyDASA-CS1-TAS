"""Tests for `src.experimental.prototype.target.factory.tas`.

**TestTasFactory**: composite `build_tas_fastapi_app` over an in-memory mesh of seven third-party ASGI apps.

- *test_round_trip()*: an `alarm` POST resolves through one atomic and writes one JSONL flow record.
- *test_healthz()*: `GET /healthz` answers 200 / `{"status": "ok"}` regardless of mesh state.
- *test_samples()*: `/samples?since=<offset>` returns the post-trial buffer; replaying with `next_offset` returns an empty list.
- *test_config()*: `POST /config` installs the named picker on the live workflow engine.

The mesh is in-process via `MeshTransport`: each "atomic endpoint" is a sibling ASGI app dispatched by host:port; the composite's `ServiceClient` picks up the transport via the `patch_async_client` helper. We never boot uvicorn here; the spawn-process path is exercised by `tests/demo/composite.py`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.factory.tas import build_tas_fastapi_app
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)
from tests.utils.exp.transports import MeshTransport, patch_async_client

_ATOMIC_IDS: tuple[str, ...] = (
    "AS_{1}", "AS_{2}", "AS_{3}",
    "MAS_{1}", "MAS_{2}", "MAS_{3}",
    "DS_{3}",
)


def _kind_from_svc_id(svc_id: str) -> str:
    """Return the catalogue kind for a Weyns 2015 atomic id (`AS_*` / `MAS_*` / `DS_*`)."""
    if svc_id.startswith("AS"):
        return "alarm"
    if svc_id.startswith("MAS"):
        return "medical_analysis"
    return "drug"


def _build_mesh_transport(catalogue_ids: tuple[str, ...] = _ATOMIC_IDS,
                          base_port: int = 8001) -> tuple[dict[str, str], MeshTransport]:
    """Build `(url_lt, transport)` routing per-host requests to one ASGI app each.

    Args:
        catalogue_ids (tuple[str, ...]): atomic ids to mount. Defaults to the canonical seven.
        base_port (int, optional): first port; each id gets the next consecutive port.

    Returns:
        tuple: `(svc_id -> URL map, MeshTransport routing by host:port)`.
    """
    _urls: dict[str, str] = {}
    _routes: dict[str, httpx.ASGITransport] = {}
    for _i, _svc_id in enumerate(catalogue_ids):
        _host = f"127.0.0.1:{base_port + _i}"
        _app = build_atomic_fastapi_app(svc_name=_svc_id,
                                        kind=_kind_from_svc_id(_svc_id),
                                        mu=0.0)
        _urls[_svc_id] = f"http://{_host}"
        _routes[_host] = httpx.ASGITransport(app=_app)
    return _urls, MeshTransport(_routes)


class TestTasFactory:
    """Composite factory wired through an in-memory mesh transport."""

    @pytest.mark.asyncio
    async def test_round_trip(self,
                              tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_round_trip()* POSTing a `kind='alarm'` request to TAS dispatches to one alarm atomic and writes one JSONL flow record."""
        _url_lt, _mesh_transport = _build_mesh_transport()
        patch_async_client(monkeypatch, _mesh_transport)
        _flows_path = tmp_path / "flows.jsonl"
        _app = build_tas_fastapi_app(url_lt=_url_lt,
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
        _app = build_tas_fastapi_app(url_lt={})
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://tas") as _http:
            _resp = await _http.get("/healthz")
        assert _resp.status_code == 200
        assert _resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_samples(self,
                           tmp_path: Path,
                           monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_samples()* after one POST, `/samples?since=0` returns one record; replaying with the returned `next_offset` returns an empty list."""
        _url_lt, _mesh_transport = _build_mesh_transport()
        patch_async_client(monkeypatch, _mesh_transport)
        _app = build_tas_fastapi_app(url_lt=_url_lt, run_id="rid")
        _transport = make_test_transport(_app, "fastapi")
        async with _app.router.lifespan_context(_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://tas") as _http:
                await _http.post("/", json={"req_id": "r0",
                                            "kind": "alarm",
                                            "client_id": "u",
                                            "submitted_ts": 0.0})
                _first = await _http.get("/samples", params={"since": 0})
                assert _first.status_code == 200
                _first_body = _first.json()
                assert len(_first_body["records"]) == 1
                assert _first_body["records"][0]["req_id"] == "r0"
                _next_offset = _first_body["next_offset"]
                _second = await _http.get("/samples", params={"since": _next_offset})
                assert _second.json()["records"] == []

    @pytest.mark.asyncio
    async def test_config(self) -> None:
        """*test_config()* `POST /config` installs the named picker on the live workflow engine."""
        _url_lt = {"AS_{1}": "http://127.0.0.1:8001",
                   "MAS_{1}": "http://127.0.0.1:8002",
                   "DS_{3}": "http://127.0.0.1:8003"}
        _app = build_tas_fastapi_app(url_lt=_url_lt)
        _transport = make_test_transport(_app, "fastapi")
        async with _app.router.lifespan_context(_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://tas") as _http:
                _resp = await _http.post("/config", json={
                    "picker_name": "retry_on_failure",
                    "op_weights": {"triggerAlarm": {"AS_{1}": 1.0}},
                    "max_attempts": 3,
                    "window_size": 100,
                })
        assert _resp.status_code == 200
        assert _resp.json() == {"applied": True, "picker_name": "retry_on_failure"}
        from src.experimental.prototype.controller.strategies import RetryOnFailurePicker
        assert isinstance(_app.state.composite.workflow.picker, RetryOnFailurePicker)
