"""Vernier: ping/echo atomic handler + FastAPI / Flask app factories.

The single-service load target for calibration. The handler stamps `recv_ts` and `send_ts` on every request and echoes `req_id`, `submitted_ts`, and the blob size back; the client uses those four values to compute round-trip latency and server-side handling time.

`build_vernier_fastapi_app()` and `build_vernier_flask_app()` mount the echo at POST `/` plus a `/healthz` for readiness probes. Both factories are top-level so they pickle across `multiprocessing.spawn`.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI
from flask import Flask, jsonify, request as flask_request


def echo(payload: dict[str, Any]) -> dict[str, Any]:
    """Stamp `recv_ts` + `send_ts` and bounce the request id, submitted timestamp, and blob size back.

    Pure function: no I/O, no framework dependency. Both app factories wrap this with their stack's request-decoding glue.

    Args:
        payload (dict[str, Any]): parsed request body. Expected keys: `req_id` (str), `submitted_ts` (float), `blob` (str, optional). Missing keys are tolerated (defaults are empty / zero) so the vernier accepts both calibration ping packets and full client `Request` payloads.

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


def build_vernier_fastapi_app() -> FastAPI:
    """Build a FastAPI app exposing POST `/` (vernier echo) and GET `/healthz`.

    Top-level so it is picklable by name across `multiprocessing.spawn`.

    Returns:
        FastAPI: app with one POST `/` and one GET `/healthz` handler.
    """
    _app = FastAPI()

    async def _post_root(payload: dict[str, Any]) -> dict[str, Any]:
        return echo(payload)

    async def _get_healthz() -> dict[str, str]:
        return {"status": "ok"}

    _app.add_api_route("/",
                       _post_root,
                       methods=["POST"])
    _app.add_api_route("/healthz",
                       _get_healthz,
                       methods=["GET"])
    return _app


def build_vernier_flask_app() -> Flask:
    """Build a Flask app exposing POST `/` (vernier echo) and GET `/healthz`.

    Top-level so it is picklable by name across `multiprocessing.spawn`.

    Returns:
        Flask: app with one POST `/` and one GET `/healthz` handler.
    """
    _app = Flask(__name__)

    def _post_root() -> Any:
        _payload = flask_request.get_json(silent=True) or {}
        return jsonify(echo(_payload))

    def _get_healthz() -> Any:
        return jsonify({"status": "ok"})

    _app.add_url_rule("/",
                      view_func=_post_root,
                      methods=["POST"])
    _app.add_url_rule("/healthz",
                      view_func=_get_healthz,
                      methods=["GET"])
    return _app
