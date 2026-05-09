"""Tests for `src.experimental.prototype.calibration.vernier`.

Logic-only checks via the FastAPI / Flask test clients; real spawn lives in `00-calibration.ipynb`.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from src.experimental.prototype.calibration.vernier import (
    Vernier,
    build_vernier_fastapi_app,
    build_vernier_flask_app,
    echo,
)
from src.experimental.prototype.target.service.atomic import AtomicService


class TestVernier:
    """Echo handler + FastAPI / Flask app factories."""

    def test_echo_shape(self) -> None:
        """Given a typical ping payload, `echo` returns a dict with the documented keys and bounces back `req_id`, `submitted_ts`, and `blob_size`."""
        _payload: dict[str, Any] = {"req_id": "r-1",
                                    "submitted_ts": 1.5,
                                    "blob": "abcd"}
        _ans = echo(_payload)
        assert _ans["req_id"] == "r-1"
        assert _ans["submitted_ts"] == 1.5
        assert _ans["blob_size"] == 4
        assert "recv_ts" in _ans
        assert "send_ts" in _ans
        assert _ans["send_ts"] >= _ans["recv_ts"]

    def test_echo_missing_keys(self) -> None:
        """Missing keys default to empty / zero so the vernier tolerates calibration packets that omit fields the full client would set."""
        _ans = echo({})
        assert _ans["req_id"] == ""
        assert _ans["submitted_ts"] == 0.0
        assert _ans["blob_size"] == 0

    def test_echo_blob_size(self) -> None:
        """`blob_size` reports the character length of the (base64-encoded) blob string, not the decoded byte count."""
        _ans = echo({"blob": "x" * 128})
        assert _ans["blob_size"] == 128

    def test_fastapi_echoes(self) -> None:
        """POST `/` to the FastAPI vernier returns 200 with the echo body plus `c_used_at_start` from the inherited admission gate."""
        _client = TestClient(build_vernier_fastapi_app())
        _resp = _client.post("/",
                             json={"req_id": "r-2",
                                   "submitted_ts": 2.0,
                                   "blob": "abc"})
        assert _resp.status_code == 200
        _body = _resp.json()
        assert _body["req_id"] == "r-2"
        assert _body["submitted_ts"] == 2.0
        assert _body["blob_size"] == 3
        # Inherited from AtomicService: every successful response stamps the in-flight count.
        assert _body["c_used_at_start"] >= 1

    def test_fastapi_healthz(self) -> None:
        """GET `/healthz` on the FastAPI vernier returns 200 + `{"status": "ok"}`."""
        _client = TestClient(build_vernier_fastapi_app())
        _resp = _client.get("/healthz")
        assert _resp.status_code == 200
        assert _resp.json() == {"status": "ok"}

    def test_flask_echoes(self) -> None:
        """POST `/` to the Flask vernier returns 200 with the echo body plus `c_used_at_start`."""
        _app = build_vernier_flask_app()
        _client = _app.test_client()
        _resp = _client.post("/",
                             json={"req_id": "r-3",
                                   "submitted_ts": 3.0,
                                   "blob": "ab"})
        assert _resp.status_code == 200
        _body = _resp.get_json()
        assert _body["req_id"] == "r-3"
        assert _body["submitted_ts"] == 3.0
        assert _body["blob_size"] == 2
        assert _body["c_used_at_start"] >= 1

    def test_flask_healthz(self) -> None:
        """GET `/healthz` on the Flask vernier returns 200 + `{"status": "ok"}`."""
        _app = build_vernier_flask_app()
        _client = _app.test_client()
        _resp = _client.get("/healthz")
        assert _resp.status_code == 200
        assert _resp.get_json() == {"status": "ok"}

    def test_vernier_subclasses_atomic(self) -> None:
        """`Vernier` inherits from `AtomicService`, so K + c admission is available out of the box without overriding `invoke_operation`."""
        _svc = Vernier(service_name="vernier", k=10, c=4)
        assert isinstance(_svc, AtomicService)
        assert _svc.k == 10
        assert _svc.c == 4
