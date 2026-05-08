"""Tests for `src.experimental.common.transport.mock`.

**TestMockTransport**:

- `test_fastapi_returns_asgi_transport`: confirms the FastAPI branch returns an `httpx.ASGITransport` so `httpx.AsyncClient` can pair with it.
- `test_flask_returns_wsgi_transport`: confirms the Flask branch returns an `httpx.WSGITransport` so `httpx.Client` can pair with it.
- `test_unknown_framework_raises`: confirms an unrecognised framework name raises `ValueError` rather than silently returning `None`.
- `test_fastapi_round_trip`: confirms a real FastAPI app responds via the in-memory transport, demonstrating the apparatus actually delivers requests in tests without TCP.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from src.experimental.common.transport.mock import make_test_transport


async def _fetch_healthz(transport: httpx.AsyncBaseTransport) -> tuple[int, dict[str, str]]:
    """Issue one GET to `/healthz` through the given async transport.

    Args:
        transport (httpx.AsyncBaseTransport): in-memory transport bound to a FastAPI app.

    Returns:
        tuple[int, dict[str, str]]: (status_code, response_body).
    """
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as _client:
        _resp = await _client.get("/healthz")
        _body = _resp.json()
        _status = _resp.status_code
    return _status, _body


class TestMockTransport:
    """In-memory httpx transport for FastAPI / Flask test clients."""

    def test_fastapi_returns_asgi_transport(self, fastapi_healthz_app: FastAPI) -> None:
        """Passing a FastAPI app and the `\"fastapi\"` framework literal yields an `httpx.ASGITransport` instance, the type that pairs with `httpx.AsyncClient` for async test calls.

        Args:
            fastapi_healthz_app (FastAPI): shared FastAPI app fixture from conftest.
        """
        _t = make_test_transport(fastapi_healthz_app, "fastapi")
        assert isinstance(_t, httpx.ASGITransport)

    def test_flask_returns_wsgi_transport(self, flask_healthz_app: Flask) -> None:
        """Passing a Flask app and the `\"flask\"` framework literal yields an `httpx.WSGITransport` instance, the type that pairs with the synchronous `httpx.Client` for blocking test calls.

        Args:
            flask_healthz_app (Flask): shared Flask app fixture from conftest.
        """
        _t = make_test_transport(flask_healthz_app, "flask")
        assert isinstance(_t, httpx.WSGITransport)

    def test_unknown_framework_raises(self, fastapi_healthz_app: FastAPI) -> None:
        """A framework string that is neither `\"fastapi\"` nor `\"flask\"` raises `ValueError` with both the bad value and the accepted set in the message, so misuse fails loudly at the call site.

        Args:
            fastapi_healthz_app (FastAPI): shared FastAPI app fixture from conftest (any app object suffices for this branch).
        """
        with pytest.raises(ValueError, match="unknown framework"):
            make_test_transport(fastapi_healthz_app, "django")  # type: ignore[arg-type]

    def test_fastapi_round_trip(self, fastapi_healthz_app: FastAPI) -> None:
        """A real FastAPI app served through the in-memory transport responds to `GET /healthz` with HTTP 200 and the expected JSON body, demonstrating the apparatus delivers requests in tests without involving TCP.

        Args:
            fastapi_healthz_app (FastAPI): shared FastAPI app fixture from conftest.
        """
        _transport = make_test_transport(fastapi_healthz_app, "fastapi")
        _status, _body = asyncio.run(_fetch_healthz(_transport))
        assert _status == 200
        assert _body == {"status": "ok"}
