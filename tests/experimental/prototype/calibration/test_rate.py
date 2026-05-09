"""Tests for `src.experimental.prototype.calibration.rate`.

Logic-only checks: ramp generator, saturation detector, orchestrator with fake drivers. One smoke test exercises `drive_at_rate` against the vernier through the in-memory ASGI transport.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.calibration.rate import (
    detect_saturation,
    drive_at_rate,
    make_lambda_ramp,
    probe_rate,
)
from src.experimental.prototype.calibration.vernier import build_vernier_fastapi_app


# ---- Module-level helpers ----

def _clean_row(rate: int) -> dict[str, Any]:
    """Per-rate stats row that never breaches either band; used by every fake driver."""
    return {"rate": rate, "loss_pct": 0.0, "p95_us": 1000.0}


def _clean_driver(target_urls: list[str],
                  rate: int,
                  duration_s: float) -> dict[str, Any]:
    """Stateless fake `RateDriver`: every rate clean."""
    del target_urls, duration_s
    return _clean_row(rate)


class _CollectingDriver:
    """Fake `RateDriver` that records every (urls, rate, duration_s) it was called with.

    Attributes:
        calls (list[tuple[list[str], int, float]]): one entry per `__call__`.
    """

    def __init__(self) -> None:
        """Initialise an empty call log."""
        self.calls: list[tuple[list[str], int, float]] = []

    def __call__(self, target_urls: list[str],
                 rate: int,
                 duration_s: float) -> dict[str, Any]:
        """Record the call and return clean per-rate stats."""
        self.calls.append((list(target_urls), rate, duration_s))
        return _clean_row(rate)


class _SaturatingDriver:
    """Fake `RateDriver` that returns saturated stats once `rate >= threshold`.

    Attributes:
        threshold (int): inclusive saturation cut-off.
    """

    def __init__(self, threshold: int) -> None:
        """Configure the saturation cut-off."""
        self.threshold = threshold

    def __call__(self, target_urls: list[str],
                 rate: int,
                 duration_s: float) -> dict[str, Any]:
        """Return saturated stats when `rate >= threshold`, otherwise clean stats."""
        del target_urls, duration_s
        if rate >= self.threshold:
            return {"rate": rate, "loss_pct": 99.0, "p95_us": 1000.0}
        return _clean_row(rate)


class _RaisingTransport(httpx.AsyncBaseTransport):
    """Synthetic transport that always raises `httpx.ConnectError`."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Always raise to simulate a refused connection.

        Args:
            request (httpx.Request): the outgoing request (ignored).
        """
        del request
        _msg = "synthetic connect error"
        raise httpx.ConnectError(_msg)


async def _drive_against_vernier(rate: int, duration_s: float) -> dict[str, Any]:
    """Exercise `drive_at_rate` against the FastAPI vernier via the in-memory ASGI transport."""
    _app = build_vernier_fastapi_app()
    _transport = make_test_transport(_app, "fastapi")
    async with httpx.AsyncClient(transport=_transport,
                                 base_url="http://test") as _client:
        _ans = await drive_at_rate(_client,
                                   ["/"],
                                   rate=rate,
                                   duration_s=duration_s)
    return _ans


async def _drive_against_raising(rate: int, duration_s: float) -> dict[str, Any]:
    """Exercise `drive_at_rate` against a transport that always raises `ConnectError`."""
    async with httpx.AsyncClient(transport=_RaisingTransport(),
                                 base_url="http://test") as _client:
        _ans = await drive_at_rate(_client,
                                   ["/"],
                                   rate=rate,
                                   duration_s=duration_s)
    return _ans


# ---- Tests ----

class TestRate:
    """Ramp generator + saturation detector + orchestrator + driver smoke."""

    def test_ramp_basic(self) -> None:
        """A typical start/stop/step yields a closed-interval linear ramp from start to stop."""
        _ramp = make_lambda_ramp(start=50, stop=200, step=50)
        assert _ramp == [50, 100, 150, 200]

    def test_ramp_single_point(self) -> None:
        """When start equals stop, the ramp degenerates to a single point."""
        _ramp = make_lambda_ramp(start=100, stop=100, step=10)
        assert _ramp == [100]

    def test_ramp_step_zero_raises(self) -> None:
        """A non-positive step is rejected at construction; nothing reasonable can happen with a zero increment."""
        with pytest.raises(ValueError, match="step must be positive"):
            make_lambda_ramp(start=10, stop=20, step=0)

    def test_sat_no_breach(self) -> None:
        """An entirely clean ramp produces a not-saturated verdict with no offending rate."""
        _rows = [{"rate": 10, "loss_pct": 0.0, "p95_us": 1000.0},
                 {"rate": 20, "loss_pct": 1.0, "p95_us": 2000.0}]
        _ans = detect_saturation(_rows,
                                 target_loss_pct=5.0,
                                 max_p95_latency_us=10_000.0)
        assert _ans["saturated"] is False
        assert _ans["saturation_rate"] is None

    def test_sat_loss_breach(self) -> None:
        """A row with `loss_pct` over the band flips the verdict and names the offending rate."""
        _rows = [{"rate": 10, "loss_pct": 0.0, "p95_us": 1000.0},
                 {"rate": 20, "loss_pct": 99.0, "p95_us": 1000.0}]
        _ans = detect_saturation(_rows,
                                 target_loss_pct=5.0,
                                 max_p95_latency_us=10_000.0)
        assert _ans["saturated"] is True
        assert _ans["saturation_rate"] == 20
        assert "loss" in _ans["reason"]

    def test_sat_latency_breach(self) -> None:
        """When a rate's tail latency leaves the band, the verdict flips to saturated and reports the offending rate."""
        _rows = [{"rate": 10, "loss_pct": 0.0, "p95_us": 1000.0},
                 {"rate": 20, "loss_pct": 0.0, "p95_us": 99_999.0}]
        _ans = detect_saturation(_rows,
                                 target_loss_pct=5.0,
                                 max_p95_latency_us=10_000.0)
        assert _ans["saturated"] is True
        assert _ans["saturation_rate"] == 20
        assert "p95" in _ans["reason"]

    def test_sat_first_wins(self) -> None:
        """When the early row breaches, that row is reported even if later rows would also breach."""
        _rows = [{"rate": 10, "loss_pct": 99.0, "p95_us": 1000.0},
                 {"rate": 20, "loss_pct": 99.0, "p95_us": 99_999.0}]
        _ans = detect_saturation(_rows,
                                 target_loss_pct=5.0,
                                 max_p95_latency_us=10_000.0)
        assert _ans["saturation_rate"] == 10

    def test_probe_walks_ramp(self) -> None:
        """The orchestrator invokes the driver once per rate in the ramp, in start-to-stop order."""
        _driver = _CollectingDriver()
        probe_rate(target_urls=["http://x"],
                   start=10,
                   stop=30,
                   step=10,
                   per_rate_s=0.0,
                   target_loss_pct=5.0,
                   max_p95_latency_us=10_000.0,
                   driver=_driver)
        _rates = [_call[1] for _call in _driver.calls]
        assert _rates == [10, 20, 30]

    def test_probe_passes_url_list(self) -> None:
        """The orchestrator forwards the full url list to every driver call so multi-worker deployments are driven aggregate-style."""
        _driver = _CollectingDriver()
        _urls = ["http://x:1", "http://x:2", "http://x:3"]
        probe_rate(target_urls=_urls,
                   start=10,
                   stop=10,
                   step=10,
                   per_rate_s=0.0,
                   target_loss_pct=5.0,
                   max_p95_latency_us=10_000.0,
                   driver=_driver)
        assert _driver.calls[0][0] == _urls

    def test_probe_halts_on_sat(self) -> None:
        """The orchestrator halts at the first saturated rate and reports it; later rates in the ramp are not driven."""
        _driver = _SaturatingDriver(threshold=20)
        _ans = probe_rate(target_urls=["http://x"],
                          start=10,
                          stop=100,
                          step=10,
                          per_rate_s=0.0,
                          target_loss_pct=5.0,
                          max_p95_latency_us=10_000.0,
                          driver=_driver)
        assert _ans["saturated"] is True
        assert _ans["saturation_rate"] == 20
        # halted after rate=20
        assert len(_ans["per_rate"]) == 2

    def test_probe_full_ramp(self) -> None:
        """When no rate saturates, the orchestrator walks every step of the ramp and the verdict stays clean."""
        _ans = probe_rate(target_urls=["http://x"],
                          start=10,
                          stop=30,
                          step=10,
                          per_rate_s=0.0,
                          target_loss_pct=5.0,
                          max_p95_latency_us=10_000.0,
                          driver=_clean_driver)
        assert _ans["saturated"] is False
        assert _ans["saturation_rate"] is None
        assert len(_ans["per_rate"]) == 3
        assert _ans["ramp"] == [10, 20, 30]
        assert _ans["target_urls"] == ["http://x"]

    def test_drive_vernier(self) -> None:
        """Driving the vernier through the in-memory transport produces a populated stats dict; numerical accuracy is left to the notebook."""
        _ans = asyncio.run(_drive_against_vernier(rate=100,
                                                  duration_s=0.05))
        assert _ans["rate"] == 100
        assert _ans["total"] >= 1
        for _key in ("errors", "loss_pct", "median_us", "p95_us", "p99_us"):
            assert _key in _ans

    def test_drive_zero_duration(self) -> None:
        """A zero-duration drive sends no requests and returns the empty-shape sentinel without raising."""
        _ans = asyncio.run(_drive_against_vernier(rate=100,
                                                  duration_s=0.0))
        assert _ans["total"] == 0
        assert _ans["errors"] == 0
        assert _ans["loss_pct"] == 0.0
        assert _ans["median_us"] == 0.0

    def test_drive_transport_error(self) -> None:
        """When the transport always refuses the connection, every request is counted as a failure and the loss fraction reaches 100 percent."""
        _ans = asyncio.run(_drive_against_raising(rate=100,
                                                  duration_s=0.05))
        assert _ans["total"] >= 1
        assert _ans["errors"] == _ans["total"]
        assert _ans["loss_pct"] == 100.0
