"""Vernier: ping/echo atomic service + FastAPI / Flask app factories.

The single-service load target for calibration. The handler stamps `recv_ts` and `send_ts` on every request and echoes `req_id`, `submitted_ts`, and the blob size back; the client uses those values to compute round-trip latency and server-side handling time.

`Vernier` inherits from `AtomicService`. Calibration leaves K + c at `None` (unbounded) so the host floor is measured without admission noise. The two factories instantiate one `Vernier`, wrap it in a per-framework adapter, and bind POST `/` + GET `/healthz`. Both are top-level so they pickle across `multiprocessing.spawn`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from flask import Flask, jsonify, request as flask_request

from src.experimental.prototype.target.service.atomic import AtomicService


_HEALTHZ_BODY: dict[str, str] = {"status": "ok"}


def echo(payload: dict[str, Any]) -> dict[str, Any]:
    """Stamp `recv_ts` + `send_ts` and bounce the request id, submitted timestamp, and blob size back.

    Pure function: no I/O, no framework dependency. The `Vernier` handler wraps this with admission stamping.

    Args:
        payload (dict[str, Any]): parsed request body. Expected keys: `req_id` (str), `submitted_ts` (float), `blob` (str, optional). Missing keys default to empty / zero so the vernier accepts both calibration ping packets and full client `Request` payloads.

    Returns:
        dict[str, Any]: response body. Keys: `req_id`, `submitted_ts` (echoed), `recv_ts`, `blob_size`, `send_ts`.
    """
    _recv = time.time()
    _ans: dict[str, Any] = {
        "req_id": payload.get("req_id", ""),
        "submitted_ts": payload.get("submitted_ts", 0.0),
        "recv_ts": _recv,
        "blob_size": len(payload.get("blob", "")),
        "send_ts": time.time(),
    }
    return _ans


class Vernier(AtomicService):
    """Ping/echo atomic service. The calibration test bench.

    Inherits K + c admission from `AtomicService`; `_handle` is the pure echo. Calibration runs leave K + c unset so the host floor is measured without admission noise.
    """

    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run the pure echo; admission and `c_used_at_start` are handled by the inherited `invoke_operation`."""
        return echo(payload)


class _FastapiRoutes:
    """FastAPI route adapter: bound-method handlers over a shared `Vernier`.

    Promotes the per-route handlers out of the factory closure and into module scope so they're inspectable by FastAPI's signature machinery and not re-defined on every factory call.
    """

    def __init__(self, svc: Vernier) -> None:
        self._svc = svc

    async def post_root(self, payload: dict[str, Any]) -> JSONResponse:
        """POST `/`: forward the parsed body to the vernier and return its body + status."""
        _body, _status = await self._svc.invoke_operation(payload)
        return JSONResponse(content=_body, status_code=_status)

    async def healthz(self) -> dict[str, str]:
        """GET `/healthz`: readiness probe."""
        return _HEALTHZ_BODY


class _FlaskRoutes:
    """Flask view adapter: bound-method handlers over a shared `Vernier`.

    Mirrors `_FastapiRoutes`. Flask is sync; the async `invoke_operation` is run via `asyncio.run` per request (low load only; the calibration uses FastAPI for high-rate runs).
    """

    def __init__(self, svc: Vernier) -> None:
        self._svc = svc

    def post_root(self) -> Any:
        """POST `/`: parse JSON, invoke the vernier, return Flask response."""
        _payload = flask_request.get_json(silent=True) or {}
        _body, _status = asyncio.run(self._svc.invoke_operation(_payload))
        return jsonify(_body), _status

    def healthz(self) -> Any:
        """GET `/healthz`: readiness probe."""
        return jsonify(_HEALTHZ_BODY)


def build_vernier_fastapi_app(*,
                              k: int | None = None,
                              c: int | None = None) -> FastAPI:
    """Build a FastAPI app exposing POST `/` (vernier echo) and GET `/healthz`.

    Top-level so it pickles across `multiprocessing.spawn`.

    Args:
        k (int | None, optional): in-flight cap forwarded to the `Vernier` instance. Defaults to None (no limit).
        c (int | None, optional): parallel-worker cap. Defaults to None (no limit).

    Returns:
        FastAPI: configured app.
    """
    _routes = _FastapiRoutes(Vernier(service_name="vernier", k=k, c=c))
    _app = FastAPI()
    _app.add_api_route("/",
                       _routes.post_root,
                       methods=["POST"])
    _app.add_api_route("/healthz",
                       _routes.healthz,
                       methods=["GET"])
    return _app


def build_vernier_flask_app(*,
                            k: int | None = None,
                            c: int | None = None) -> Flask:
    """Build a Flask app exposing POST `/` (vernier echo) and GET `/healthz`.

    Top-level so it pickles across `multiprocessing.spawn`.

    Args:
        k (int | None, optional): in-flight cap. Defaults to None.
        c (int | None, optional): parallel-worker cap. Defaults to None.

    Returns:
        Flask: configured app.
    """
    _routes = _FlaskRoutes(Vernier(service_name="vernier", k=k, c=c))
    _app = Flask(__name__)
    _app.add_url_rule("/",
                      view_func=_routes.post_root,
                      methods=["POST"])
    _app.add_url_rule("/healthz",
                      view_func=_routes.healthz,
                      methods=["GET"])
    return _app
