"""Shared fixtures for the experimental-method test suite.

Provides reusable test data and helpers so individual test files do not hard-wire records:

- `sample_jsonl_record`: one canonical per-request flow record.
- `sample_envelope`: one canonical apparatus-envelope dict.
- `sample_csv_columns`: standard per-service CSV column schema.
- `sample_csv_row`: one canonical per-service invocation row matching the columns above.
- `make_desc`: factory that builds `ServiceDescription` instances with sensible defaults.
- `fastapi_healthz_app`: FastAPI app with a `/healthz` endpoint, for transport / runtime tests.
- `flask_healthz_app`: Flask app with a `/healthz` endpoint, for transport / runtime tests.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi import FastAPI
from flask import Flask, jsonify

from src.experimental.common.registry.description import ServiceDescription

SVC_COLUMNS = [
    "req_id",
    "srv_name",
    "kind",
    "recv_ts",
    "start_ts",
    "local_end_ts",
    "end_ts",
    "c_used_at_start",
    "success",
    "status_code",
    "size_bytes",
]


@pytest.fixture
def sample_jsonl_record() -> dict[str, Any]:
    """Return one canonical per-request flow record.

    Returns:
        dict[str, Any]: dict with the fields a real flow record carries.
    """
    _record: dict[str, Any] = {
        "req_id": "u47-r0312",
        "kind": "medical_analysis",
        "client_id": "user-42",
        "submitted_ts": 1736282400.123456,
        "completed_ts": 1736282400.139201,
        "outcome": "success",
        "total_latency_s": 0.015745,
    }
    return _record


@pytest.fixture
def sample_envelope() -> dict[str, Any]:
    """Return one canonical apparatus-envelope dict.

    Returns:
        dict[str, Any]: minimal envelope with host_profile + timer fields.
    """
    _env: dict[str, Any] = {
        "host_profile": {"os": "Windows"},
        "timer": {"median_ns": 100},
    }
    return _env


@pytest.fixture
def sample_csv_columns() -> list[str]:
    """Return the standard per-service CSV column schema.

    Returns:
        list[str]: column names matching the LOG_COLUMNS schema.
    """
    return list(SVC_COLUMNS)


@pytest.fixture
def sample_csv_row() -> dict[str, Any]:
    """Return one canonical per-service invocation row.

    Returns:
        dict[str, Any]: dict whose keys match `sample_csv_columns`.
    """
    _row: dict[str, Any] = {
        "req_id": "u47-r0312",
        "srv_name": "TAS_{1}",
        "kind": "medical_analysis",
        "recv_ts": 1736282400.124,
        "start_ts": 1736282400.125,
        "local_end_ts": 1736282400.138,
        "end_ts": 1736282400.139,
        "c_used_at_start": 3,
        "success": True,
        "status_code": 200,
        "size_bytes": 1024,
    }
    return _row


@pytest.fixture
def make_desc() -> Callable[..., ServiceDescription]:
    """Return a factory that builds `ServiceDescription` instances with sensible defaults.

    Returns:
        Callable[..., ServiceDescription]: factory accepting `name` (str) and optional `port` (int, default 8001), `operations` (tuple, default `("op_a", "op_b")`), and `custom_props` (dict, default `{"failure_rate": 0.05}` when None is passed).
    """
    def _factory(
        name: str,
        port: int = 8001,
        operations: tuple[str, ...] = ("op_a", "op_b"),
        custom_props: dict[str, Any] | None = None,
    ) -> ServiceDescription:
        """Build one `ServiceDescription` with apparatus-friendly defaults.

        Args:
            name (str): service name (also used to derive `_id` as `id-<name>`).
            port (int, optional): TCP port for the synthesised endpoint URL. Defaults to 8001.
            operations (tuple[str, ...], optional): supported operation names. Defaults to `("op_a", "op_b")`.
            custom_props (dict[str, Any] | None, optional): QoS hints. Defaults to None, which expands to `{"failure_rate": 0.05}`.

        Returns:
            ServiceDescription: a frozen dataclass instance ready to register with `ServiceRegistry`.
        """
        if custom_props is None:
            _props = {"failure_rate": 0.05}
        else:
            _props = custom_props
        _desc = ServiceDescription(
            _id=f"id-{name}",
            name=name,
            endpoint=f"http://127.0.0.1:{port}",
            operations=operations,
            custom_props=_props,
        )
        return _desc
    return _factory


@pytest.fixture
def fastapi_healthz_app() -> FastAPI:
    """Build a FastAPI app exposing a single `/healthz` endpoint.

    Routes are registered via `add_api_route` (not the `@app.get` decorator) so the static analyser sees the handler as referenced.

    Returns:
        FastAPI: configured app whose `/healthz` returns `{"status": "ok"}`.
    """
    _app = FastAPI()

    def _healthz_handler() -> dict[str, str]:
        return {"status": "ok"}

    _app.add_api_route("/healthz",
                       _healthz_handler,
                       methods=["GET"])
    return _app


@pytest.fixture
def flask_healthz_app() -> Flask:
    """Build a Flask app exposing a single `/healthz` endpoint.

    Returns:
        Flask: configured app whose `/healthz` returns `{"status": "ok"}` as JSON.
    """
    _app = Flask(__name__)

    def _healthz_handler() -> Any:  # noqa: ANN401  (Flask response type is Any-ish)
        return jsonify({"status": "ok"})

    _app.add_url_rule("/healthz",
                      view_func=_healthz_handler,
                      methods=["GET"])
    return _app
