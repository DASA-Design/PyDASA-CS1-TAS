"""Tests for `src.experimental.prototype.client.guard`.

**TestStopGuard**:

- `test_initial_state`: confirms a fresh guard reports `StopReason.NONE` so a run starts in a non-stopped state.
- `test_request_budget`: confirms exceeding `max_requests` trips `REQUEST_BUDGET` so the run halts at the configured cap.
- `test_infra_consecutive`: confirms `infra_threshold` consecutive transport failures within the window trip `INFRA_FAILURE`.
- `test_infra_resets_on_success`: confirms one good record between failures resets the consecutive counter so spurious cascades do not falsely trip the infra stop.
- `test_quality_r1`: confirms exceeding `r1_failure_rate_max` over the quality window trips `QUALITY_R1_FAILURE_RATE`.
- `test_quality_r2`: confirms exceeding `r2_latency_s_max` over the quality window trips `QUALITY_R2_RESPONSE_TIME`.
- `test_sticky`: confirms once a condition trips, subsequent updates keep returning the same reason so the run halts deterministically.
- `test_5xx_non_503`: confirms a planted `5xx` failure mechanism with status != 503 does NOT count towards the infra cascade so failure-injection scenarios do not falsely trip the apparatus stop.
- `test_5xx_503_counts`: confirms a 5xx response with status 503 (admission overload) DOES count towards the infra cascade because it indicates the apparatus is broken.
- `test_infra_window_quiet`: confirms a previous infra failure outside the window resets the consecutive counter when a new failure arrives, so an old quiet incident does not contribute to a new cascade.
- `test_max_requests_property`: confirms the public `max_requests` property returns the configured cap so callers (notably `User.run_until_stop`) can mirror the budget without reaching into private state.
"""

from __future__ import annotations

from src.experimental.prototype.client.guard import (
    QualityThresholds,
    StopGuard,
    StopReason,
)
from src.experimental.prototype.client.stats import Stats
from tests.utils.exp.factories import make_record


class TestStopGuard:
    """Three-condition stop controller: infra failure, request budget, quality threshold."""

    def test_initial_state(self) -> None:
        """A fresh `StopGuard` reports `StopReason.NONE` before any record arrives, so a run begins in the non-stopped state."""
        _guard = StopGuard()
        assert _guard.stop_reason == StopReason.NONE

    def test_request_budget(self) -> None:
        """Reaching `max_requests` records trips `REQUEST_BUDGET`; the guard halts the run at the configured cap so resources are not exhausted."""
        _guard = StopGuard(max_requests=3)
        _stats = Stats()
        _reason = StopReason.NONE
        for _i in range(3):
            _r = make_record(_i, "success")
            _stats.update(_r)
            _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.REQUEST_BUDGET

    def test_infra_consecutive(self) -> None:
        """`infra_threshold` consecutive transport failures within the window trip `INFRA_FAILURE`; this is the early-halt signal that the apparatus is broken (not the architecture)."""
        _guard = StopGuard(max_requests=1000,
                           infra_threshold=3,
                           infra_window_s=10.0)
        _stats = Stats()
        _reason = StopReason.NONE
        for _i in range(3):
            _r = make_record(_i, "timeout")
            _stats.update(_r)
            _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.INFRA_FAILURE

    def test_infra_resets_on_success(self) -> None:
        """A success record between transport failures resets the consecutive counter so two old failures + one success + one new failure do not falsely trip the cascade."""
        _guard = StopGuard(infra_threshold=3, infra_window_s=100.0)
        _stats = Stats()
        for _i in range(2):
            _r = make_record(_i, "timeout")
            _stats.update(_r)
            _guard.update(_r, _stats)
        _good = make_record(2, "success")
        _stats.update(_good)
        _guard.update(_good, _stats)
        _bad = make_record(3, "timeout")
        _stats.update(_bad)
        _reason = _guard.update(_bad, _stats)
        assert _reason == StopReason.NONE

    def test_quality_r1(self) -> None:
        """A failure rate above `r1_failure_rate_max` over the quality window trips `QUALITY_R1_FAILURE_RATE`; the run halts because the strategy already missed the bar."""
        _quality = QualityThresholds(r1_failure_rate_max=0.2, window_s=100.0)
        _guard = StopGuard(quality=_quality)
        _stats = Stats()
        # 3 successes, then 2 5xx-business-style failures = 2/5 = 40% > 20%
        for _i in range(3):
            _r = make_record(_i, "success")
            _stats.update(_r)
            _guard.update(_r, _stats)
        _r = make_record(3, "5xx", status_code=500)
        _stats.update(_r)
        _guard.update(_r, _stats)
        _r = make_record(4, "5xx", status_code=500)
        _stats.update(_r)
        _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.QUALITY_R1_FAILURE_RATE

    def test_quality_r2(self) -> None:
        """A mean success-latency above `r2_latency_s_max` over the window trips `QUALITY_R2_RESPONSE_TIME`."""
        _quality = QualityThresholds(r2_latency_s_max=0.05, window_s=100.0)
        _guard = StopGuard(quality=_quality)
        _stats = Stats()
        _r = make_record(0, "success", latency=0.10)
        _stats.update(_r)
        _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.QUALITY_R2_RESPONSE_TIME

    def test_sticky(self) -> None:
        """Once a condition trips, subsequent `update()` calls return the same reason so the run halts deterministically without flapping."""
        _guard = StopGuard(max_requests=1)
        _stats = Stats()
        _r = make_record(0, "success")
        _stats.update(_r)
        _first = _guard.update(_r, _stats)
        _r2 = make_record(1, "success")
        _stats.update(_r2)
        _second = _guard.update(_r2, _stats)
        assert _first == StopReason.REQUEST_BUDGET
        assert _second == StopReason.REQUEST_BUDGET

    def test_5xx_non_503(self) -> None:
        """A planted `5xx` failure with status 500 (not 503) is treated as a business-style failure for infra purposes, so the planted-failure mechanism does not falsely trip the apparatus stop."""
        _guard = StopGuard(infra_threshold=2, infra_window_s=100.0)
        _stats = Stats()
        _reason = StopReason.NONE
        for _i in range(5):
            _r = make_record(_i, "5xx", status_code=500)
            _stats.update(_r)
            _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.NONE

    def test_5xx_503_counts(self) -> None:
        """A 5xx response with status 503 indicates admission overload (apparatus broken), so two consecutive 503s within the window trip `INFRA_FAILURE` even though the outcome label is `5xx` rather than `timeout`/`drop`."""
        _guard = StopGuard(infra_threshold=2, infra_window_s=100.0)
        _stats = Stats()
        _reason = StopReason.NONE
        for _i in range(2):
            _r = make_record(_i, "5xx", status_code=503)
            _stats.update(_r)
            _reason = _guard.update(_r, _stats)
        assert _reason == StopReason.INFRA_FAILURE

    def test_max_requests_property(self) -> None:
        """The public `max_requests` property returns the configured budget so `User.run_until_stop` can derive its iteration cap from the guard without poking at private attributes."""
        _guard = StopGuard(max_requests=42)
        assert _guard.max_requests == 42

    def test_infra_window_quiet(self) -> None:
        """One transport failure long ago (outside the window) does not contribute to a new cascade: the second failure restarts the counter at 1, so reaching the threshold requires `infra_threshold` failures within one window only."""
        _guard = StopGuard(infra_threshold=2, infra_window_s=1.0)
        _stats = Stats()
        # First failure at t=0
        _r0 = make_record(0, "timeout")
        _stats.update(_r0)
        _guard.update(_r0, _stats)
        # Second failure at t=10 (outside the 1-second window): counter resets to 1
        _r1 = make_record(10, "timeout")
        _stats.update(_r1)
        _reason = _guard.update(_r1, _stats)
        assert _reason == StopReason.NONE
