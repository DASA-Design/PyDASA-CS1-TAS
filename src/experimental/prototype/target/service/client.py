"""ServiceClient: httpx-based remote invoker over a `ServiceCache` (Weyns & Calinescu 2015 Fig. 2).

Dispatches one `invoke_operation` call to a registered service. The composite TAS service holds one `ServiceClient` and uses it to reach the `MAS_*`, `AS_*`, `DS_*` atomics across loopback or LAN. The cache resolves names to endpoints; the client bundles request metadata, awaits the HTTP response, and returns `(body, status)`.

The Java synchronous interface becomes async (`httpx.AsyncClient`). The optional `transport` argument is a test seam: production uses real TCP, tests pass an in-memory ASGI transport.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from src.experimental.common.registry.cache import ServiceCache

DFLT_TIMEOUT_S = 5.0


class ServiceClient:
    """Async HTTP client over a `ServiceCache`, modelled on Fig. 2 ServiceClient.

    Attributes:
        client_id (str): caller identifier (for trace fields).
        cache (ServiceCache): per-client snapshot used to resolve `svc_name` to endpoint URLs.
    """

    def __init__(self,
                 *,
                 client_id: str,
                 cache: ServiceCache,
                 timeout_s: float = DFLT_TIMEOUT_S,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Build the client.

        Args:
            client_id (str): identifier (e.g. composite service name).
            cache (ServiceCache): cache to resolve service names against.
            timeout_s (float, optional): HTTP request timeout. Defaults to `DFLT_TIMEOUT_S`.
            transport (httpx.AsyncBaseTransport | None, optional): test seam. Defaults to None (real TCP).
        """
        self.client_id = client_id
        self.cache = cache
        self._timeout_s = timeout_s
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        # Per-svc round-robin counter so multi-worker services share load across workers.
        self._rr_counters: dict[str, int] = {}

    async def __aenter__(self) -> Self:
        """Open the underlying HTTPX client."""
        self._http = httpx.AsyncClient(transport=self._transport,
                                       timeout=self._timeout_s)
        return self

    async def __aexit__(self,
                        _exc_type: type[BaseException] | None,
                        _exc: BaseException | None,
                        _tb: TracebackType | None) -> None:
        """Close the underlying HTTPX client; protocol args are unused."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def invoke_operation(self,
                               svc_name: str,
                               operation: str,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Resolve `svc_name`, POST `payload` to its endpoint, return `(body, status)`.

        The `operation` field is forwarded inside the payload so the receiving service can route to the right atomic operation. Each atomic currently exposes a single endpoint, so `operation` is informational.

        Args:
            svc_name (str): name registered in the cache (e.g. `AS_{1}`).
            operation (str): logical operation name (e.g. `triggerAlarm`).
            payload (dict[str, Any]): request body; `operation` is added under the same key.

        Returns:
            tuple[dict[str, Any], int]: response body + HTTP status code. On transport error returns an error body with status `0` so the caller can record a non-HTTP outcome.

        Raises:
            RuntimeError: if called outside the async-context-manager (no open HTTP client).
        """
        if self._http is None:
            _msg = "ServiceClient must be used inside an async-with block (httpx client not open)"
            raise RuntimeError(_msg)
        _desc = self.cache.lookup(svc_name)
        _url = self._pick_url(svc_name, _desc.iter_urls())
        _body_out: dict[str, Any] = dict(payload)
        _body_out["operation"] = operation
        _body_out["client_id"] = self.client_id
        _ans_body, _ans_status = await self._post(endpoint=_url,
                                                  payload=_body_out)
        return _ans_body, _ans_status

    def _pick_url(self, svc_name: str,
                  urls: tuple[str, ...]) -> str:
        """Round-robin one URL out of `urls` (the workers behind `svc_name`).

        Per-svc counter lives on the client so each `ServiceClient` instance distributes its own outbound load across the service's workers independently. Single-worker services short-circuit to the only URL without incrementing the counter.

        Args:
            svc_name (str): service name; used as the counter key.
            urls (tuple[str, ...]): URLs returned by `ServiceDescription.iter_urls`.

        Returns:
            str: one URL from `urls`.
        """
        if len(urls) == 1:
            return urls[0]
        _idx = self._rr_counters.get(svc_name, 0)
        self._rr_counters[svc_name] = (_idx + 1) % len(urls)
        return urls[_idx % len(urls)]

    async def _post(self,
                    endpoint: str,
                    payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """POST `payload` to `<endpoint>/`; map transport errors to `(error_body, 0)`.

        Args:
            endpoint (str): base URL (e.g. `http://127.0.0.1:8002`).
            payload (dict[str, Any]): outgoing JSON body.

        Returns:
            tuple[dict[str, Any], int]: `(body, status_code)`. Status `0` signals a transport error (the response never arrived).
        """
        if self._http is None:
            _msg = "internal: _post called without an open HTTP client"
            raise RuntimeError(_msg)
        try:
            _resp = await self._http.post(f"{endpoint}/", json=payload)
        except httpx.TimeoutException as _err:
            return {"error": "timeout", "detail": str(_err)}, 0
        except httpx.RequestError as _err:
            return {"error": "drop", "detail": str(_err)}, 0
        try:
            _body = _resp.json()
        except ValueError:
            _body = {"raw": _resp.text}
        if not isinstance(_body, dict):
            _body = {"raw": _body}
        return _body, _resp.status_code


__all__ = [
    "DFLT_TIMEOUT_S",
    "ServiceClient",
]
