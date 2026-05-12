"""Tests for `src.experimental.prototype.controller.poller`.

**TestSamplePoller**:

- `test_poll_once_merges_new_records`: one `_poll_once` against a stub TAS_1 ingests the returned samples.
- `test_poll_once_advances_offset`: `_poll_once` records the highest seen offset so subsequent polls only pick up newer samples.
- `test_poll_once_tolerates_transport_error`: a transport failure during polling does not raise; the next poll picks up wherever it left off.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.experimental.prototype.controller.app import build_controller_app
from src.experimental.prototype.controller.poller import SamplePoller


_THRESHOLDS = {"r1_max": 0.0003, "r2_max": 0.026}


class _StubTas:
    """Stub TAS_1 that serves a scripted list of samples on `/samples`.

    Attributes:
        samples (list[dict]): every sample known to the stub. `_poll_once` filters by `since`.
        calls (list[int]): recorded `since` values for each poll.
    """

    def __init__(self, samples: list[dict[str, Any]]) -> None:
        """Configure the stub.

        Args:
            samples (list[dict]): records the stub returns, in offset order.
        """
        self.samples = samples
        self.calls: list[int] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Match an httpx Request against the stub's `/samples` endpoint."""
        if not request.url.path.endswith("/samples"):
            return httpx.Response(404, json={"error": "not_found"})
        _since = int(request.url.params.get("since", 0))
        self.calls.append(_since)
        _records = [_s for _s in self.samples if _s["offset"] > _since]
        _next_offset = max((_s["offset"] for _s in self.samples), default=_since)
        return httpx.Response(200, json={"records": _records, "next_offset": _next_offset})


class _AlwaysErrorTas:
    """Stub TAS_1 that raises on every request."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Raise an httpx transport error regardless of the request."""
        del request
        raise httpx.ConnectError("synthetic")


class _MockTransport(httpx.AsyncBaseTransport):
    """Wrap a stub object that implements `handle_async_request`."""

    def __init__(self, inner: Any) -> None:
        """Bind to an inner stub."""
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Delegate to the inner stub."""
        return await self._inner.handle_async_request(request)


class TestSamplePoller:
    """Single-poll behaviour of `SamplePoller` against a stub TAS_1."""

    @pytest.mark.asyncio
    async def test_poll_once_merges_new_records(self) -> None:
        """*test_poll_once_merges_new_records()* one poll ingests the stub's records into the controller window."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=100)
        _stub = _StubTas([
            {"offset": 1, "req_id": "r1", "status": 200, "total_latency_s": 0.005, "ts": 1.0},
            {"offset": 2, "req_id": "r2", "status": 502, "total_latency_s": 0.001, "ts": 2.0},
        ])
        _poller = SamplePoller(target_url="http://stub-tas",
                               poll_interval_ms=100,
                               app=_app)
        async with httpx.AsyncClient(transport=_MockTransport(_stub)) as _http:
            await _poller._poll_once(_http)
        assert len(_app.state.history) == 2
        assert _app.state.last_offset == 2

    @pytest.mark.asyncio
    async def test_poll_once_advances_offset(self) -> None:
        """*test_poll_once_advances_offset()* a second poll passes `since=last_offset` and skips stale records."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=100)
        _stub = _StubTas([
            {"offset": 1, "req_id": "r1", "status": 200, "total_latency_s": 0.005, "ts": 1.0},
            {"offset": 2, "req_id": "r2", "status": 200, "total_latency_s": 0.005, "ts": 2.0},
        ])
        _poller = SamplePoller(target_url="http://stub-tas",
                               poll_interval_ms=100,
                               app=_app)
        async with httpx.AsyncClient(transport=_MockTransport(_stub)) as _http:
            await _poller._poll_once(_http)
            _stub.samples.append({"offset": 3, "req_id": "r3", "status": 200,
                                  "total_latency_s": 0.005, "ts": 3.0})
            await _poller._poll_once(_http)
        assert _stub.calls == [0, 2]
        assert _app.state.last_offset == 3
        assert len(_app.state.history) == 3

    @pytest.mark.asyncio
    async def test_poll_once_tolerates_transport_error(self) -> None:
        """*test_poll_once_tolerates_transport_error()* a transport failure during polling does not raise."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=100)
        _poller = SamplePoller(target_url="http://broken-tas",
                               poll_interval_ms=100,
                               app=_app)
        async with httpx.AsyncClient(transport=_MockTransport(_AlwaysErrorTas())) as _http:
            await _poller._poll_once(_http)
        assert _app.state.last_offset == 0
        assert len(_app.state.history) == 0
