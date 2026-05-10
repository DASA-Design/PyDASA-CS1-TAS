"""Shared `/healthz` route helper for every factory app.

The runtime spawners poll `/healthz` to decide when a server is ready to receive traffic. Every TAS + third-party app exposes the same endpoint; this helper centralises the route registration so the body shape stays consistent across factories.
"""

from __future__ import annotations

from fastapi import FastAPI

HEALTHZ_BODY: dict[str, str] = {"status": "ok"}


def add_healthz_route(app: FastAPI) -> None:
    """Register `GET /healthz` returning `HEALTHZ_BODY` on the supplied app.

    Args:
        app (FastAPI): app to mount the route on.
    """

    async def _handler() -> dict[str, str]:
        return HEALTHZ_BODY

    app.add_api_route("/healthz", _handler, methods=["GET"])


__all__ = [
    "HEALTHZ_BODY",
    "add_healthz_route",
]
