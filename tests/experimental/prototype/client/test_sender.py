"""Tests for `src.experimental.prototype.client.sender`.

**TestSender**:

- `test_build_metadata`: confirms `build_request` stamps every metadata field (`req_id`, `kind`, `client_id`, `submitted_ts`, `inject_failure`, blob) so the wire payload is well-formed before send.
- `test_blob_seeded`: confirms two builds with the same seed produce identical bytes so the apparatus stays bit-reproducible.
- `test_auto_uuid_req_id`: confirms `build_request` mints a UUID4 hex string for `req_id` when the caller does not supply one, so two consecutive calls produce distinct ids without the caller managing a counter.
- `test_send_success`: confirms a 200 response yields `outcome="success"` plus a status code so happy-path requests log cleanly.
- `test_send_5xx`: confirms a 500 response yields `outcome="5xx"` so planted failure mechanisms surface as expected.
- `test_send_timeout`: confirms a `TimeoutException` from the transport yields `outcome="timeout"` with status 0 so the wall-clock cap is observable.
- `test_send_drop`: confirms a transport-level connection error yields `outcome="drop"` with status 0 so dropped connections are surfaced as a distinct outcome from timeouts.
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from src.experimental.common.payload.request import KIND_MED_ANSYS, Request
from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.client.records import RequestRecord
from src.experimental.prototype.client.sender import Sender
from tests.utils.exp.apps import build_5xx_app, build_echo_app
from tests.utils.exp.transports import DropTransport, TimeoutTransport


async def _send_one(transport: httpx.AsyncBaseTransport) -> RequestRecord:
    """Open a one-shot AsyncClient bound to the given transport, send one request, return the record.

    Args:
        transport (httpx.AsyncBaseTransport): test transport to dispatch through.

    Returns:
        RequestRecord: the completed record.
    """
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as _client:
        _sender = Sender(client=_client,
                         client_id="user-1",
                         endpoint="/",
                         payload_size_bytes=64,
                         blob_seed=42,
                         timeout_s=1.0)
        _request = _sender.build_request(kind=KIND_MED_ANSYS, req_id="r1")
        _record = await _sender.send(_request)
        return _record


class TestSender:
    """`Sender` builds requests and dispatches them via `httpx.AsyncClient`."""

    def test_build_metadata(self, fastapi_healthz_app: FastAPI) -> None:
        """The `Request` returned by `build_request` carries every field downstream consumers need: id, kind, client_id, timestamp, failure flag (None until the catalogue is wired), and the blob bytes."""
        async def _exercise() -> Request:
            _transport = make_test_transport(fastapi_healthz_app, "fastapi")
            async with httpx.AsyncClient(transport=_transport,
                                         base_url="http://testserver") as _c:
                _s = Sender(client=_c,
                            client_id="user-1",
                            endpoint="/healthz",
                            payload_size_bytes=32,
                            blob_seed=7)
                return _s.build_request(kind=KIND_MED_ANSYS, req_id="r1")
        _request = asyncio.run(_exercise())
        assert _request.req_id == "r1"
        assert _request.kind == KIND_MED_ANSYS
        assert _request.client_id == "user-1"
        assert _request.inject_failure is None
        assert len(_request.blob) == 32
        assert _request.submitted_ts > 0

    def test_auto_uuid_req_id(self, fastapi_healthz_app: FastAPI) -> None:
        """Calling `build_request` without a `req_id` mints a UUID4 hex string per call: two back-to-back builds carry distinct 32-char hex ids, so callers can drop their own counter and trust the sender to mint unique identifiers."""
        async def _exercise() -> tuple[str, str]:
            _transport = make_test_transport(fastapi_healthz_app, "fastapi")
            async with httpx.AsyncClient(transport=_transport, base_url="http://testserver") as _c:
                _s = Sender(client=_c,
                            client_id="u",
                            endpoint="/healthz",
                            payload_size_bytes=32,
                            blob_seed=42)
                _a = _s.build_request(kind=KIND_MED_ANSYS)
                _b = _s.build_request(kind=KIND_MED_ANSYS)
                return _a.req_id, _b.req_id
        _id_a, _id_b = asyncio.run(_exercise())
        assert _id_a != _id_b
        assert len(_id_a) == 32
        assert len(_id_b) == 32
        # UUID4 hex is lowercase 0-9a-f only
        assert all(_c in "0123456789abcdef" for _c in _id_a)

    def test_blob_seeded(self, fastapi_healthz_app: FastAPI) -> None:
        """Two requests built by the same sender (which holds a fixed `blob_seed`) carry identical blob bytes, demonstrating the apparatus is bit-reproducible across calls."""
        async def _exercise() -> tuple[bytes, bytes]:
            _transport = make_test_transport(fastapi_healthz_app, "fastapi")
            async with httpx.AsyncClient(transport=_transport, base_url="http://testserver") as _c:
                _s = Sender(client=_c,
                            client_id="u",
                            endpoint="/healthz",
                            payload_size_bytes=64,
                            blob_seed=99)
                _a = _s.build_request(kind=KIND_MED_ANSYS, req_id="r1")
                _b = _s.build_request(kind=KIND_MED_ANSYS, req_id="r2")
                return _a.blob, _b.blob
        _blob_a, _blob_b = asyncio.run(_exercise())
        assert _blob_a == _blob_b

    def test_send_success(self) -> None:
        """A 200 response from the in-memory echo app yields `outcome="success"` with a 200 status code, so the happy-path log line carries the expected outcome."""
        _transport = make_test_transport(build_echo_app(), "fastapi")
        _record = asyncio.run(_send_one(_transport))
        assert _record.outcome == "success"
        assert _record.status_code == 200

    def test_send_5xx(self) -> None:
        """A 500 response yields `outcome="5xx"` with status 500, so a planted server-error failure mechanism is visible to the verdict layer."""
        _transport = make_test_transport(build_5xx_app(), "fastapi")
        _record = asyncio.run(_send_one(_transport))
        assert _record.outcome == "5xx"
        assert _record.status_code == 500

    def test_send_timeout(self) -> None:
        """A `httpx.ReadTimeout` from the transport yields `outcome="timeout"` with status 0, demonstrating the sender maps wall-clock failures to the structured outcome the guard's infra-failure logic relies on."""
        _record = asyncio.run(_send_one(TimeoutTransport()))
        assert _record.outcome == "timeout"
        assert _record.status_code == 0

    def test_send_drop(self) -> None:
        """A `httpx.ConnectError` from the transport yields `outcome="drop"` with status 0, distinguishing connection-level failures from wall-clock timeouts so the guard's infra-cascade math sees both signals."""
        _record = asyncio.run(_send_one(DropTransport()))
        assert _record.outcome == "drop"
        assert _record.status_code == 0
