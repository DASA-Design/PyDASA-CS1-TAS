"""Tests for `src.experimental.prototype.target.service.client`.

**TestServiceClient**:

- `test_round_trip`: client mounted over an in-memory ASGI echo app POSTs and gets the body + 200 back.
- `test_unknown_svc`: unknown `svc_name` raises `UnknownServiceError` from the cache.
- `test_no_async_with`: calling `invoke_operation` before `__aenter__` raises `RuntimeError`.
- `test_timeout_to_zero`: a transport that raises `httpx.ReadTimeout` returns `(error_body, 0)`.
- `test_drop_to_zero`: a transport that raises `httpx.ConnectError` returns `(error_body, 0)`.
"""

from __future__ import annotations

import pytest

from src.experimental.common.registry.cache import ServiceCache
from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import ServiceRegistry
from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.service.client import ServiceClient
from tests.utils.exp.apps import build_echo_app
from tests.utils.exp.transports import DropTransport, TimeoutTransport


def _build_cache(svc_name: str = "echo",
                 endpoint: str = "http://test") -> ServiceCache:
    """Build a one-entry `ServiceCache` for the test."""
    _reg = ServiceRegistry()
    _reg.register_service(ServiceDescription(_id=svc_name,
                                             name=svc_name,
                                             endpoint=endpoint))
    return ServiceCache(_reg)


class TestServiceClient:
    """`ServiceClient` over an in-memory ASGI transport."""

    @pytest.mark.asyncio
    async def test_round_trip(self) -> None:
        """*test_round_trip()* a one-shot POST through an in-memory echo app returns `({"ok": True, "kind": "X"}, 200)`."""
        _cache = _build_cache()
        _transport = make_test_transport(build_echo_app(), "fastapi")
        async with ServiceClient(client_id="caller",
                                 cache=_cache,
                                 transport=_transport) as _client:
            _body, _status = await _client.invoke_operation(svc_name="echo",
                                                            operation="ping",
                                                            payload={"kind": "X"})
        assert _status == 200
        assert _body["ok"] is True
        assert _body["kind"] == "X"

    @pytest.mark.asyncio
    async def test_unknown_svc(self) -> None:
        """*test_unknown_svc()* `invoke_operation` for a name not in the cache raises `UnknownServiceError`."""
        from src.experimental.common.registry.service import UnknownServiceError
        _cache = _build_cache()
        _transport = make_test_transport(build_echo_app(), "fastapi")
        async with ServiceClient(client_id="caller",
                                 cache=_cache,
                                 transport=_transport) as _client:
            with pytest.raises(UnknownServiceError):
                await _client.invoke_operation(svc_name="missing",
                                               operation="ping",
                                               payload={})

    @pytest.mark.asyncio
    async def test_no_async_with(self) -> None:
        """*test_no_async_with()* calling before `__aenter__` raises `RuntimeError` so the bug surfaces immediately."""
        _cache = _build_cache()
        _client = ServiceClient(client_id="caller", cache=_cache)
        with pytest.raises(RuntimeError):
            await _client.invoke_operation(svc_name="echo",
                                           operation="ping",
                                           payload={})

    @pytest.mark.asyncio
    async def test_timeout_to_zero(self) -> None:
        """*test_timeout_to_zero()* a transport that raises `ReadTimeout` returns status `0` with `error == 'timeout'`."""
        _cache = _build_cache()
        async with ServiceClient(client_id="caller",
                                 cache=_cache,
                                 transport=TimeoutTransport()) as _client:
            _body, _status = await _client.invoke_operation(svc_name="echo",
                                                            operation="ping",
                                                            payload={})
        assert _status == 0
        assert _body["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_drop_to_zero(self) -> None:
        """*test_drop_to_zero()* a transport that raises `ConnectError` returns status `0` with `error == 'drop'`."""
        _cache = _build_cache()
        async with ServiceClient(client_id="caller",
                                 cache=_cache,
                                 transport=DropTransport()) as _client:
            _body, _status = await _client.invoke_operation(svc_name="echo",
                                                            operation="ping",
                                                            payload={})
        assert _status == 0
        assert _body["error"] == "drop"
