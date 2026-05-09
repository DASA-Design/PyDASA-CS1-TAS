"""Reusable HTTP-app factories for `src.experimental` tests.

Five flavours:

- `build_echo_app()`: FastAPI POST `/` returning `{"ok": True, "kind": <kind>}`.
- `build_5xx_app()`: FastAPI POST `/` always returning HTTP 500.
- `build_healthz_fastapi_app()`: FastAPI GET `/healthz` returning `{"status": "ok"}`. Used by `runtime/` process-spawner tests.
- `build_healthz_flask_app()`: Flask GET `/healthz` returning `{"status": "ok"}`. Used by `runtime/` process-spawner tests for the WSGI variant.
- `start_echo_server()`: stdlib `ThreadingHTTPServer` echo on a free localhost port. Returns `(server, thread, base_url)`; caller owns shutdown.

The two `build_healthz_*_app` factories are top-level (not nested closures) so they survive pickling across `multiprocessing.spawn` boundaries on Windows.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi import FastAPI, Response
from flask import Flask, jsonify


def build_echo_app() -> FastAPI:
    """Build a FastAPI app whose POST `/` echoes the body wrapped as `{"ok": True, "kind": <kind>}`.

    Returns:
        FastAPI: app with one POST `/` handler.
    """
    _app = FastAPI()

    async def _handler(payload: dict) -> dict:  # type: ignore[type-arg]
        return {"ok": True, "kind": payload.get("kind", "?")}

    _app.add_api_route("/", _handler, methods=["POST"])
    return _app


def build_5xx_app() -> FastAPI:
    """Build a FastAPI app whose POST `/` always returns HTTP 500 with a planted error body.

    Returns:
        FastAPI: app with one POST `/` handler.
    """
    _app = FastAPI()

    async def _handler(_payload: dict) -> Response:  # type: ignore[type-arg]
        _ans = Response(status_code=500,
                        content=b"{'error':'planted'}",
                        media_type="application/json",)
        return _ans

    _app.add_api_route("/", _handler, methods=["POST"], response_model=None)
    return _app


def build_healthz_fastapi_app() -> FastAPI:
    """Build a FastAPI app exposing a single `/healthz` endpoint returning `{"status": "ok"}`.

    Top-level so it is picklable by name across `multiprocessing.spawn` (Windows requires it).

    Returns:
        FastAPI: app with one GET `/healthz` handler.
    """
    _app = FastAPI()

    def _healthz_handler() -> dict[str, str]:
        return {"status": "ok"}

    _app.add_api_route("/healthz", _healthz_handler, methods=["GET"])
    return _app


def build_healthz_flask_app() -> Flask:
    """Build a Flask app exposing a single `/healthz` endpoint returning `{"status": "ok"}`.

    Top-level so it is picklable by name across `multiprocessing.spawn` (Windows requires it).

    Returns:
        Flask: app with one GET `/healthz` handler.
    """
    _app = Flask(__name__)

    def _healthz_handler() -> Any:  # noqa: ANN401
        return jsonify({"status": "ok"})

    _app.add_url_rule("/healthz", view_func=_healthz_handler, methods=["GET"])
    return _app


class _SilentEchoHandler(BaseHTTPRequestHandler):
    """Stdlib HTTP handler returning 200 + JSON `{"ok": True}` on POST.

    The `log_message` override silences the default request-line logging so test output stays focused.
    """

    def do_POST(self) -> None:
        """Read the body, ignore it, return the canonical 200 echo response."""
        _length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(_length) if _length > 0 else b""
        _bytes = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(_bytes)))
        self.end_headers()
        self.wfile.write(_bytes)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Silence the default request logging.

        Args:
            format (str): format string (unused). Named to match the parent signature.
            *args (Any): format arguments (unused).
        """
        return


def start_echo_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Bind a `ThreadingHTTPServer` to `127.0.0.1:0` and start serving in a daemon thread.

    Returns:
        tuple[ThreadingHTTPServer, threading.Thread, str]: server, serving thread, base URL. The caller is responsible for `server.shutdown()` + `server.server_close()` + `thread.join(timeout=...)`.
    """
    _server = ThreadingHTTPServer(("127.0.0.1", 0), _SilentEchoHandler)
    _port = _server.server_address[1]
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    return _server, _thread, f"http://127.0.0.1:{_port}"
