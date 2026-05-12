"""Tests for `src.experimental.prototype.controller.app`.

**TestControllerApp**:

- `test_aggregates_empty`: a fresh app reports `n_seen=0`, both breach flags `False`.
- `test_aggregates_after_ingest`: ingesting one failure + two successes yields R1=1/3, R2=mean(successful latencies), no breach (warm-up).
- `test_warmup_gate`: a high failure rate before warm-up keeps `r1_breach=False`; after warm-up it flips True.
- `test_history_records`: every ingested sample lands in `/history` with running aggregates at its arrival.
- `test_healthz`: `GET /healthz` returns 200.

**TestIngestSamples**:

- `test_drops_stale_offsets`: records with offset <= `last_offset` are skipped silently.
- `test_advances_offset`: the highest seen offset becomes the new `last_offset`.
"""

from __future__ import annotations

import pytest
import httpx

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.controller.app import (
    build_controller_app,
    ingest_samples,
)


_THRESHOLDS = {"r1_max": 0.0003, "r2_max": 0.026}


def _sample(offset: int, status: int, latency_s: float = 0.005) -> dict:
    """Build one TAS_1 sample record."""
    return {
        "offset": offset,
        "req_id": f"r{offset}",
        "status": status,
        "total_latency_s": latency_s,
        "ts": float(offset),
    }


class TestControllerApp:
    """`build_controller_app` + the `/aggregates`, `/history`, `/healthz` routes."""

    @pytest.mark.asyncio
    async def test_aggregates_empty(self) -> None:
        """*test_aggregates_empty()* a fresh app reports `n_seen=0` and both breach flags False."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=5)
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _resp = await _http.get("/aggregates")
        assert _resp.status_code == 200
        _body = _resp.json()
        assert _body["n_seen"] == 0
        assert _body["r1_value"] == 0.0
        assert _body["r2_value"] == 0.0
        assert _body["r1_breach"] is False
        assert _body["r2_breach"] is False

    @pytest.mark.asyncio
    async def test_aggregates_after_ingest(self) -> None:
        """*test_aggregates_after_ingest()* 1 failure + 2 successes yields R1=1/3; R2=mean over successes."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=100)
        ingest_samples(_app, [
            _sample(1, status=502, latency_s=0.005),
            _sample(2, status=200, latency_s=0.010),
            _sample(3, status=200, latency_s=0.020),
        ])
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _resp = await _http.get("/aggregates")
        _body = _resp.json()
        assert _body["n_seen"] == 3
        assert _body["n_in_window"] == 3
        assert _body["r1_value"] == pytest.approx(1 / 3)
        assert _body["r2_value"] == pytest.approx(0.015)
        # Warmup is 100 so breach flags stay False even with R1 above threshold.
        assert _body["r1_breach"] is False

    @pytest.mark.asyncio
    async def test_warmup_gate(self) -> None:
        """*test_warmup_gate()* R1 above threshold is suppressed until the warm-up is reached."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=5)
        ingest_samples(_app, [_sample(_i, status=502) for _i in range(1, 4)])
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _before = (await _http.get("/aggregates")).json()
        assert _before["r1_value"] == 1.0
        assert _before["r1_breach"] is False
        ingest_samples(_app, [_sample(_i, status=502) for _i in range(4, 7)])
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _after = (await _http.get("/aggregates")).json()
        assert _after["n_seen"] == 6
        assert _after["r1_breach"] is True

    @pytest.mark.asyncio
    async def test_history_records(self) -> None:
        """*test_history_records()* every ingested sample lands in `/history`."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=100)
        ingest_samples(_app, [
            _sample(1, status=200, latency_s=0.005),
            _sample(2, status=502, latency_s=0.001),
        ])
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _resp = await _http.get("/history")
        _records = _resp.json()["records"]
        assert len(_records) == 2
        assert _records[0]["req_id"] == "r1"
        assert _records[1]["status"] == 502
        assert _records[1]["r1_running"] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_healthz(self) -> None:
        """*test_healthz()* `GET /healthz` returns 200 with `{"status": "ok"}`."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=5)
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://ctrl") as _http:
            _resp = await _http.get("/healthz")
        assert _resp.status_code == 200
        assert _resp.json() == {"status": "ok"}


class TestIngestSamples:
    """`ingest_samples` offset tracking and history merge."""

    def test_drops_stale_offsets(self) -> None:
        """*test_drops_stale_offsets()* records with offset <= `last_offset` are skipped."""
        _app = build_controller_app(thresholds=_THRESHOLDS, window_size=10, warmup_n=5)
        ingest_samples(_app, [_sample(1, status=200), _sample(2, status=200)])
        assert _app.state.last_offset == 2
        ingest_samples(_app, [_sample(1, status=502), _sample(2, status=502)])
        assert _app.state.last_offset == 2
        assert len(_app.state.history) == 2  # no new records merged

    def test_advances_offset(self) -> None:
        """*test_advances_offset()* the highest new offset becomes the new `last_offset`."""
        _app = build_controller_app(thresholds=_THRESHOLDS,
                                    window_size=10,
                                    warmup_n=5)
        ingest_samples(_app,
                       [_sample(5, status=200)])
        assert _app.state.last_offset == 5
        ingest_samples(_app,
                       [_sample(7, status=200), _sample(9, status=200)])
        assert _app.state.last_offset == 9
        assert len(_app.state.history) == 3
