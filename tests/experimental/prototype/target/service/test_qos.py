"""Tests for `src.experimental.prototype.target.service.qos`.

**TestQoS**:

- `test_perf_value`: `PerformanceQoS(0.026)` exposes the response-time bound.
- `test_avail_value`: `AvailabilityQoS(3e-4)` exposes the failure-rate bound.
- `test_subclasses`: both concretes are instances of the ABC for downstream type checks.
- `test_frozen`: dataclasses reject attribute assignment so cached entries stay immutable.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.experimental.prototype.target.service.qos import (
    AvailabilityQoS,
    PerformanceQoS,
    QoSRequirement,
)


class TestQoS:
    """`QoSRequirement` ABC + `PerformanceQoS` + `AvailabilityQoS`."""

    def test_perf_value(self) -> None:
        """*test_perf_value()* `PerformanceQoS(0.026)` stores the response-time bound on the named field."""
        _q = PerformanceQoS(response_time_s_max=0.026)
        assert _q.response_time_s_max == 0.026

    def test_avail_value(self) -> None:
        """*test_avail_value()* `AvailabilityQoS(3e-4)` stores the failure-rate bound on the named field."""
        _q = AvailabilityQoS(failure_rate_max=3e-4)
        assert _q.failure_rate_max == 3e-4

    def test_subclasses(self) -> None:
        """*test_subclasses()* both concretes are instances of `QoSRequirement` so downstream code can branch on the ABC."""
        assert isinstance(PerformanceQoS(0.026), QoSRequirement)
        assert isinstance(AvailabilityQoS(3e-4), QoSRequirement)

    def test_frozen(self) -> None:
        """*test_frozen()* both dataclasses raise `FrozenInstanceError` on attribute assignment so cached entries are safe to share."""
        _q = PerformanceQoS(0.026)
        with pytest.raises(FrozenInstanceError):
            setattr(_q, "response_time_s_max", 0.05)
        _a = AvailabilityQoS(3e-4)
        with pytest.raises(FrozenInstanceError):
            setattr(_a, "failure_rate_max", 0.5)
