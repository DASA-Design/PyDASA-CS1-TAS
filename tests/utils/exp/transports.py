"""Synthetic `httpx.AsyncBaseTransport` implementations + monkeypatch helper for `src.experimental` tests.

- `TimeoutTransport`: raises `httpx.ReadTimeout` -> sender records `outcome="timeout"`.
- `DropTransport`: raises `httpx.ConnectError` -> sender records `outcome="drop"`.
- `MeshTransport`: routes per-host requests to one of several mounted ASGI apps; used by composite + internal-stage round-trip tests that mount the mesh in-process.
- `patch_async_client(monkeypatch, transport)`: monkeypatch `httpx.AsyncClient` in `service.client` so the composite / stage's `ServiceClient` picks up the supplied transport when none is explicitly passed.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest


class TimeoutTransport(httpx.AsyncBaseTransport):
    """Drop-in async transport that always raises `httpx.ReadTimeout`."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Always raise to simulate a wall-clock timeout.

        Args:
            request (httpx.Request): the outgoing request (ignored).
        """
        del request
        _msg = "synthetic timeout"
        raise httpx.ReadTimeout(_msg)


class DropTransport(httpx.AsyncBaseTransport):
    """Drop-in async transport that always raises `httpx.ConnectError`."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Always raise to simulate a dropped connection.

        Args:
            request (httpx.Request): the outgoing request (ignored).
        """
        del request
        _msg = "synthetic connection drop"
        raise httpx.ConnectError(_msg)


class MeshTransport(httpx.AsyncBaseTransport):
    """Route requests by `host:port` to one of several mounted ASGI apps.

    The composite (or an internal stage) holds endpoints like `http://127.0.0.1:8002`; tests mount one ASGI transport per endpoint and let this router dispatch by host:port without booting uvicorn.
    """

    def __init__(self, host_to_transport: dict[str, httpx.ASGITransport]) -> None:
        """Configure the per-host routing table.

        Args:
            host_to_transport (dict[str, httpx.ASGITransport]): maps `"127.0.0.1:<port>"` to the ASGI transport that should answer for it.
        """
        self._lt = host_to_transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Forward `request` to the matching ASGI transport.

        Args:
            request (httpx.Request): outgoing request; only `url.host` and `url.port` are read.

        Returns:
            httpx.Response: response produced by the mounted ASGI app.

        Raises:
            httpx.ConnectError: when no transport is registered for the request's `host:port`.
        """
        _key = f"{request.url.host}:{request.url.port}"
        _t = self._lt.get(_key)
        if _t is None:
            _msg = f"no transport for {_key!r}"
            raise httpx.ConnectError(_msg)
        return await _t.handle_async_request(request)


def patch_async_client(monkeypatch: pytest.MonkeyPatch,
                       transport: httpx.AsyncBaseTransport) -> None:
    """Patch `service.client.httpx.AsyncClient` to inject `transport` when no explicit one is passed.

    Used by round-trip tests that mount a mesh of ASGI apps and need the composite's (or internal stage's) `ServiceClient` to dispatch through them instead of real TCP. Idempotent across tests; pytest's `monkeypatch` fixture reverts at teardown.

    Args:
        monkeypatch (pytest.MonkeyPatch): per-test fixture.
        transport (httpx.AsyncBaseTransport): transport to inject (typically a `MeshTransport` or a fixed-failure transport).
    """
    _orig = httpx.AsyncClient

    class _Patched(_orig):
        def __init__(_self, *args: Any, **kwargs: Any) -> None:  # noqa: N805
            if kwargs.get("transport") is None:
                kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.experimental.prototype.target.service.client.httpx.AsyncClient",
                        _Patched)
