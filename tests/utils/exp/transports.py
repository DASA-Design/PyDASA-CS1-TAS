"""Synthetic `httpx.AsyncBaseTransport` implementations for failure-path tests.

Each transport ignores the request and raises a fixed exception, simulating one failure mode the sender's outcome-mapping logic must classify:

- `TimeoutTransport`: raises `httpx.ReadTimeout` -> sender records `outcome="timeout"`.
- `DropTransport`: raises `httpx.ConnectError` -> sender records `outcome="drop"`.
"""

from __future__ import annotations

import httpx


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
