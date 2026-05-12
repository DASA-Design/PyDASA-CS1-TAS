"""Tests for `src.experimental.prototype.target.factory.internal_stage`.

**TestInternalStageFactory**: `TasInternalAtomic` + `build_internal_stage_fastapi_app` round-trip + side-effects.

- *test_round_trip()*: TAS_{2} dispatches to the first `medical_analysis` service and surfaces its reply.
- *test_status_zero_to_502()*: when the downstream transport drops, status 0 from `ServiceClient` rewrites to 502.
- *test_inject_5xx()*: `inject_failure="5xx"` returns 502 without invoking the downstream.
- *test_csv_row()*: one POST writes one row with the internal-stage column set (downstream_svc_id / downstream_status).
- *test_mu_zero_no_sleep()*: `mu=0.0` skips the exponential sleep entirely.

The downstream mesh runs in-process via the shared `MeshTransport` helper; the stage's `ServiceClient` is wired through it via `patch_async_client`.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.factory import internal_stage
from src.experimental.prototype.target.factory.internal_stage import (
    INTERNAL_CSV_COLUMNS,
    build_internal_stage_fastapi_app,
)
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)
from tests.utils.exp.transports import DropTransport, MeshTransport, patch_async_client

_MAS_URL = "http://127.0.0.1:18002"
_MAS_HOST = "127.0.0.1:18002"


def _build_mas_mesh() -> MeshTransport:
    """Mount one `MAS_{1}` ASGI app on the shared `MeshTransport` so downstream dispatches resolve in-process."""
    _mas_app = build_atomic_fastapi_app(svc_name="MAS_{1}",
                                        kind="medical_analysis",
                                        mu=0.0)
    return MeshTransport({_MAS_HOST: httpx.ASGITransport(app=_mas_app)})


def _build_stage_app(*,
                     csv_dir: str | None = None,
                     run_id: str | None = None) -> FastAPI:
    """Build a TAS_{2} stage app pointed at the single-MAS mesh.

    Caller enters `.router.lifespan_context(app)` to open the dispatch client, then mounts a `make_test_transport` over the app to issue requests.

    Args:
        csv_dir (str | None): per-pid CSV directory; None disables the side-effect.
        run_id (str | None): run identifier written into CSV rows.

    Returns:
        FastAPI: configured internal-stage app; pre-lifespan.
    """
    return build_internal_stage_fastapi_app(
        svc_name="TAS_{2}",
        calls_kind="medical_analysis",
        operation="analyseData",
        mu=0.0,
        atomic_url_lt={"MAS_{1}": _MAS_URL},
        csv_dir=csv_dir,
        run_id=run_id,
    )


class TestInternalStageFactory:
    """`TasInternalAtomic` + `build_internal_stage_fastapi_app` round-trip + side-effects."""

    @pytest.mark.asyncio
    async def test_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_round_trip()* TAS_{2} dispatches to the first medical_analysis service in the catalogue and returns its reply."""
        patch_async_client(monkeypatch, _build_mas_mesh())
        _stage_app = _build_stage_app()
        _transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "kind": "medical_analysis",
                                                    "operation": "analyseData"})
        assert _resp.status_code == 200
        _body = _resp.json()
        assert _body["downstream_svc_id"] == "MAS_{1}"
        assert _body["downstream_status"] == 200

    @pytest.mark.asyncio
    async def test_status_zero_to_502(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_status_zero_to_502()* when the third-party transport drops, the stage returns 502 to its caller."""
        patch_async_client(monkeypatch, DropTransport())
        _stage_app = _build_stage_app()
        _transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "kind": "medical_analysis",
                                                    "operation": "analyseData"})
        assert _resp.status_code == 502

    @pytest.mark.asyncio
    async def test_inject_5xx(self) -> None:
        """*test_inject_5xx()* `inject_failure="5xx"` returns 502 without invoking the downstream call."""
        _stage_app = _build_stage_app()
        _transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://stage") as _http:
                _resp = await _http.post("/", json={"req_id": "r0",
                                                    "inject_failure": "5xx"})
        assert _resp.status_code == 502

    @pytest.mark.asyncio
    async def test_csv_row(self,
                           tmp_path: Path,
                           monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_csv_row()* one POST writes one row with the internal-stage column set; INTERNAL_CSV_COLUMNS is honoured."""
        internal_stage._INTERNAL_CSV_WRITERS.clear()
        patch_async_client(monkeypatch, _build_mas_mesh())
        _stage_app = _build_stage_app(csv_dir=str(tmp_path), run_id="rid-test")
        _transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_transport,
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
        _header = _content.splitlines()[0].split(",")
        assert _header == INTERNAL_CSV_COLUMNS
        assert "rA" in _content
        assert "TAS_2" in _files[0].name
        assert "rid-test" in _content
        assert "downstream_svc_id" in _header
        assert "downstream_status" in _header
        assert "MAS_{1}" in _content

    @pytest.mark.asyncio
    async def test_mu_zero_no_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """*test_mu_zero_no_sleep()* `mu=0.0` skips the exponential sleep entirely."""
        _slept: list[float] = []

        async def _fake_sleep(_t: float) -> None:
            _slept.append(_t)

        monkeypatch.setattr("src.experimental.prototype.target.factory.internal_stage.asyncio.sleep",
                            _fake_sleep)
        patch_async_client(monkeypatch, _build_mas_mesh())
        _stage_app = _build_stage_app()
        _transport = make_test_transport(_stage_app, "fastapi")
        async with _stage_app.router.lifespan_context(_stage_app):
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://stage") as _http:
                await _http.post("/", json={"req_id": "r0",
                                            "kind": "medical_analysis",
                                            "operation": "analyseData"})
        assert _slept == []
