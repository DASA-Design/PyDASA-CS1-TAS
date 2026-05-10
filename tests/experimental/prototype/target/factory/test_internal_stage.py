"""Tests for `src.experimental.prototype.target.factory.internal_stage`.

**TestInternalStageFactory**:

- `test_round_trip`: a POST to a TAS_{2} app dispatches to the configured `medical_analysis` third-party (mounted as a sibling ASGI app) and returns the third-party reply with status 200.
- `test_status_zero_to_502`: when the third-party transport raises (mapped to status 0 by `ServiceClient`), the internal-stage atomic surfaces 502 to its caller.
- `test_inject_5xx`: a request with `inject_failure="5xx"` returns 502 without invoking the downstream call.
- `test_csv_row`: when `csv_dir` + `run_id` are set, one POST writes one row with the internal-stage column set (downstream_svc_id / downstream_status).
- `test_mu_zero_no_sleep`: `mu=0.0` makes the atomic skip the exponential sleep entirely (verified by patching `asyncio.sleep`).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.factory import internal_stage
from src.experimental.prototype.target.factory.internal_stage import (
    INTERNAL_CSV_COLUMNS,
    build_internal_stage_fastapi_app,
)
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)


class _MeshTransport(httpx.AsyncBaseTransport):
    """Route requests by host:port to one of several mounted ASGI apps."""

    def __init__(self, host_to_transport: dict[str, httpx.ASGITransport]) -> None:
        self._lt = host_to_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _key = f"{request.url.host}:{request.url.port}"
        _t = self._lt.get(_key)
        if _t is None:
            _msg = f"no transport for {_key!r}"
            raise httpx.ConnectError(_msg)
        return await _t.handle_async_request(request)


class _AlwaysDropTransport(httpx.AsyncBaseTransport):
    """Drop-in async transport that always raises `httpx.ConnectError`."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("synthetic")


def _patch_async_client(monkeypatch: pytest.MonkeyPatch,
                        mesh_transport: httpx.AsyncBaseTransport) -> None:
    """Patch `service.client.httpx.AsyncClient` to inject `mesh_transport` when no explicit transport is supplied."""
    _orig = httpx.AsyncClient

    class _Patched(_orig):
        def __init__(_self, *args: Any, **kwargs: Any) -> None:  # noqa: N805
            if kwargs.get("transport") is None:
                kwargs["transport"] = mesh_transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.experimental.prototype.target.service.client.httpx.AsyncClient",
                        _Patched)


class TestInternalStageFactory:
    """`TasInternalAtomic` + `build_internal_stage_fastapi_app` round-trip + side-effects."""

    @pytest.mark.asyncio
    async def test_round_trip(self,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_round_trip()* TAS_{2} dispatches to the first medical_analysis service in the catalogue and returns its reply."""
        # Mount one third-party MAS app + one TAS_{2} stage, both on in-memory ASGI transports.
        _mas_app = build_atomic_fastapi_app(svc_name="MAS_{1}", kind="medical_analysis", mu=0.0)
        _atomic_endpoint_lt = {"MAS_{1}": "http://127.0.0.1:18002"}
        _mesh_transport = _MeshTransport({"127.0.0.1:18002": httpx.ASGITransport(app=_mas_app)})
        _patch_async_client(monkeypatch, _mesh_transport)

        _stage_app = build_internal_stage_fastapi_app(
            svc_name="TAS_{2}",
            calls_kind="medical_analysis",
            operation="analyseData",
            mu=0.0,
            atomic_endpoint_lt=_atomic_endpoint_lt,
        )
        _stage_transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_stage_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "kind": "medical_analysis",
                                                    "operation": "analyseData"})
        assert _resp.status_code == 200
        _body = _resp.json()
        assert _body["downstream_svc_id"] == "MAS_{1}"
        assert _body["downstream_status"] == 200

    @pytest.mark.asyncio
    async def test_status_zero_to_502(self,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_status_zero_to_502()* when the third-party transport drops, the stage returns 502 to its caller."""
        _atomic_endpoint_lt = {"MAS_{1}": "http://127.0.0.1:18002"}
        _patch_async_client(monkeypatch, _AlwaysDropTransport())
        _stage_app = build_internal_stage_fastapi_app(
            svc_name="TAS_{2}",
            calls_kind="medical_analysis",
            operation="analyseData",
            mu=0.0,
            atomic_endpoint_lt=_atomic_endpoint_lt,
        )
        _stage_transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_stage_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "kind": "medical_analysis",
                                                    "operation": "analyseData"})
        assert _resp.status_code == 502

    @pytest.mark.asyncio
    async def test_inject_5xx(self) -> None:
        """*test_inject_5xx()* `inject_failure="5xx"` returns 502 without invoking the downstream call."""
        _stage_app = build_internal_stage_fastapi_app(
            svc_name="TAS_{2}",
            calls_kind="medical_analysis",
            operation="analyseData",
            mu=0.0,
            atomic_endpoint_lt={"MAS_{1}": "http://127.0.0.1:18002"},
        )
        _stage_transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_stage_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "inject_failure": "5xx"})
        assert _resp.status_code == 502

    @pytest.mark.asyncio
    async def test_csv_row(self,
                                                  tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_csv_row()* one POST writes one row with the internal-stage column set; INTERNAL_CSV_COLUMNS is honoured."""
        # Reset the module-level writer cache so the test starts clean.
        internal_stage._INTERNAL_CSV_WRITERS.clear()
        _mas_app = build_atomic_fastapi_app(svc_name="MAS_{1}", kind="medical_analysis", mu=0.0)
        _mesh_transport = _MeshTransport({"127.0.0.1:18002": httpx.ASGITransport(app=_mas_app)})
        _patch_async_client(monkeypatch, _mesh_transport)
        _stage_app = build_internal_stage_fastapi_app(
            svc_name="TAS_{2}",
            calls_kind="medical_analysis",
            operation="analyseData",
            mu=0.0,
            atomic_endpoint_lt={"MAS_{1}": "http://127.0.0.1:18002"},
            csv_dir=str(tmp_path),
            run_id="rid-test",
        )
        _stage_transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_stage_transport,
                                         base_url="http://stage") as _http:
                await _http.post("/", json={"req_id": "rA",
                                            "kind": "medical_analysis",
                                            "operation": "analyseData"})
        for _w in list(internal_stage._INTERNAL_CSV_WRITERS.values()):
            _w.close()
        internal_stage._INTERNAL_CSV_WRITERS.clear()
        _files = sorted(tmp_path.glob("*.csv"))
        assert len(_files) == 1
        _content = _files[0].read_text(encoding="utf-8")
        # Column header should match INTERNAL_CSV_COLUMNS exactly.
        _header = _content.splitlines()[0].split(",")
        assert _header == INTERNAL_CSV_COLUMNS
        assert "rA" in _content
        # The CSV is for the stage itself (TAS_{2}), not the downstream MAS.
        assert "TAS_2" in _files[0].name
        assert "rid-test" in _content
        assert "downstream_svc_id" in _header
        assert "downstream_status" in _header
        # The actual downstream id and status should land in the row body.
        assert "MAS_{1}" in _content

    @pytest.mark.asyncio
    async def test_mu_zero_no_sleep(self,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_mu_zero_no_sleep()* `mu=0.0` skips the exponential sleep entirely."""
        _slept: list[float] = []

        async def _fake_sleep(_t: float) -> None:
            _slept.append(_t)

        monkeypatch.setattr("src.experimental.prototype.target.factory.internal_stage.asyncio.sleep",
                            _fake_sleep)
        # Mount one MAS so the dispatch succeeds.
        _mas_app = build_atomic_fastapi_app(svc_name="MAS_{1}", kind="medical_analysis", mu=0.0)
        _mesh_transport = _MeshTransport({"127.0.0.1:18002": httpx.ASGITransport(app=_mas_app)})
        _patch_async_client(monkeypatch, _mesh_transport)

        _stage_app = build_internal_stage_fastapi_app(
            svc_name="TAS_{2}",
            calls_kind="medical_analysis",
            operation="analyseData",
            mu=0.0,  # sleep disabled
            atomic_endpoint_lt={"MAS_{1}": "http://127.0.0.1:18002"},
        )
        _stage_transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_stage_transport,
                                         base_url="http://stage") as _http:
                await _http.post("/", json={"req_id": "r0",
                                            "kind": "medical_analysis",
                                            "operation": "analyseData"})
        # No sleeps recorded by the internal-stage handler (the third-party MAS app uses random.expovariate too,
        # but that lives in third_party.py, not this module's asyncio.sleep — so _slept stays empty).
        assert _slept == []
