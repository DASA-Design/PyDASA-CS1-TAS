# -*- coding: utf-8 -*-
"""
Module test_sender.py
=====================

Pin the `RequestSender.send_one` contract: payload + headers reach the wire intact, business outcome flows from the response body, transport errors map to `status_code=-1`.

    - **TestRequestSender** payload+headers round-trip; HTTP 500 captured as infra failure; transport exception captured as `status_code=-1`.
"""
# native python modules
import random
from typing import Dict

# test stack
import pytest

# web stack
import httpx

# modules under test
from src.experiment.client.config import ClientCfg
from src.experiment.client.sender import RequestSender

# shared helpers
from tests.utils.helpers import (_RequestCapture,
                                 _make_mock_async_client,
                                 _one_svc_registry)


def _make_sender(client: httpx.AsyncClient,
                 *,
                 sizes_by_kind: Dict[str, int] | None = None) -> RequestSender:
    """*_make_sender()* build a `RequestSender` with one-kind probability and the given size map."""
    _cfg = ClientCfg(seed=1,
                     req_size_b=128,
                     req_sizes_by_kind=sizes_by_kind or {},
                     kind_prob={"TAS_{2}": 1.0})
    return RequestSender(client, _one_svc_registry(), _cfg, random.Random(1))


class TestRequestSender:
    """**TestRequestSender** payload+headers round-trip, transport-error capture, status passthrough."""

    @pytest.mark.asyncio
    async def test_payload_and_headers(self) -> None:
        """*test_payload_and_headers()* the outbound request body has `payload.blob` of `size_bytes` length and the `X-Request-*` headers mirror the same fields."""
        _capture = _RequestCapture()
        async with _make_mock_async_client(_capture) as _c:
            _sender = _make_sender(_c, sizes_by_kind={"TAS_{2}": 256})
            _rec = await _sender.send_one("TAS_{2}")

        assert _rec.status_code == 200
        assert _rec.success is True
        assert _rec.size_bytes == 256
        assert _capture.body["kind"] == "TAS_{2}"
        assert _capture.body["size_bytes"] == 256
        assert len(_capture.body["payload"]["blob"]) == 256
        assert _capture.headers["x-request-size-bytes"] == "256"
        assert _capture.headers["x-request-kind"] == "TAS_{2}"

    @pytest.mark.asyncio
    async def test_500_recorded(self) -> None:
        """*test_500_recorded()* HTTP 500 is captured as `status_code=500, success=False`."""
        async def _h(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        async with _make_mock_async_client(_h) as _c:
            _sender = _make_sender(_c)
            _rec = await _sender.send_one("TAS_{2}")

        assert _rec.status_code == 500
        assert _rec.success is False
        assert _rec.infra_failure is True

    @pytest.mark.asyncio
    async def test_transport_err(self) -> None:
        """*test_transport_err()* a transport-level `httpx.HTTPError` raised inside the handler maps to `status_code=-1, success=False`."""
        async def _raising(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("network down")

        async with _make_mock_async_client(_raising) as _c:
            _sender = _make_sender(_c)
            _rec = await _sender.send_one("TAS_{2}")

        assert _rec.status_code == -1
        assert _rec.success is False
        assert _rec.infra_failure is True
