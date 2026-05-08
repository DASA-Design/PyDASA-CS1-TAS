"""`StopGuard`: end-of-run controller with three independent stop conditions.

The client halts a run early on any of:

1. **Infra failure**: the apparatus broke. `infra_threshold` consecutive transport failures (timeout / drop / 503) within `infra_window_s` seconds.
2. **Request budget**: `max_requests` reached (default 1000).
3. **Quality violation**: R1 (failure rate) or R2 (mean response time) breached its threshold over a rolling window. Thresholds live in `adaptation-reqs` (plan §Lever 3); the verdict module reads from there.

`update` consumes records via `Stats` and returns the `StopReason` (or `NONE` if the run continues). The reason is sticky after the first trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.experimental.prototype.client.records import RequestRecord
from src.experimental.prototype.client.stats import Stats

# Runtime fallbacks for data/config/method/prototype/client.json::guard.*.
_DFLT_MAX_REQUESTS = 1000
_DFLT_INFRA_THRESHOLD = 5
_DFLT_INFRA_WINDOW_S = 5.0
_DFLT_QUALITY_WINDOW_S = 60.0


class StopReason(str, Enum):
    """Why the guard signalled the run to halt."""

    NONE = "none"
    INFRA_FAILURE = "infra_failure"
    REQUEST_BUDGET = "request_budget"
    QUALITY_R1_FAILURE_RATE = "quality_r1_failure_rate"
    QUALITY_R2_RESPONSE_TIME = "quality_r2_response_time"


@dataclass(frozen=True)
class QualityThresholds:
    """R1 + R2 thresholds the guard applies over the quality window.

    Attributes:
        r1_failure_rate_max (float | None): maximum acceptable failure rate (fraction). `None` disables R1.
        r2_latency_s_max (float | None): maximum acceptable mean response time, in seconds. `None` disables R2.
        window_s (float): trailing-window length both thresholds are computed over.
    """

    r1_failure_rate_max: float | None = None
    r2_latency_s_max: float | None = None
    window_s: float = _DFLT_QUALITY_WINDOW_S


class StopGuard:
    """Three-condition stop controller, evaluated after every completed request.

    Attributes:
        _max_requests (int): cap on total dispatched requests.
        _infra_threshold (int): consecutive infra failures that trigger the infra stop.
        _infra_window_s (float): rolling window for the consecutive-failure check.
        _quality (QualityThresholds): R1 + R2 thresholds plus their window.
        _consecutive_infra_failures (int): live counter; reset on any non-infra outcome.
        _last_infra_ts (float): timestamp of the most recent infra failure (used to expire the window).
        _stop_reason (StopReason): set on the first tripping condition; sticky thereafter.
    """

    def __init__(self,
                 max_requests: int = _DFLT_MAX_REQUESTS,
                 infra_threshold: int = _DFLT_INFRA_THRESHOLD,
                 infra_window_s: float = _DFLT_INFRA_WINDOW_S,
                 quality: QualityThresholds | None = None) -> None:
        """Configure the three conditions.

        Args:
            max_requests (int, optional): request-budget cap. Defaults to 1000.
            infra_threshold (int, optional): consecutive infra-failure cap. Defaults to 5.
            infra_window_s (float, optional): rolling window for the consecutive-failure check, in seconds. Defaults to 5.0.
            quality (QualityThresholds | None, optional): R1 + R2 thresholds + window. Defaults to None, which disables both quality checks.
        """
        self._max_requests = max_requests
        self._infra_threshold = infra_threshold
        self._infra_window_s = infra_window_s
        if quality is None:
            self._quality = QualityThresholds()
        else:
            self._quality = quality
        self._consecutive_infra_failures = 0
        self._last_infra_ts = 0.0
        self._stop_reason: StopReason = StopReason.NONE

    @property
    def stop_reason(self) -> StopReason:
        """Return the current stop reason (sticky after the first trip).

        Returns:
            StopReason: `NONE` while the run can continue; otherwise the tripped condition.
        """
        return self._stop_reason

    @property
    def max_requests(self) -> int:
        """Return the configured request-budget cap.

        Returns:
            int: the `max_requests` cap; callers (notably `User.run_until_stop`) read this so the loop's iteration cap mirrors the budget.
        """
        return self._max_requests

    def update(self, record: RequestRecord, stats: Stats) -> StopReason:
        """Evaluate every stop condition after one record completes.

        Args:
            record (RequestRecord): the record just emitted by the sender.
            stats (Stats): the live aggregator (used by the quality check).

        Returns:
            StopReason: `NONE` while the run continues; otherwise the first tripping condition. Sticky after the first trip.
        """
        # Already tripped: short-circuit and report the sticky reason.
        if self._stop_reason == StopReason.NONE:
            self._update_infra_counter(record)
            # Conditions are checked in priority order: infra > budget > quality.
            if self._infra_failure_tripped():
                self._stop_reason = StopReason.INFRA_FAILURE
            elif stats.count() >= self._max_requests:
                self._stop_reason = StopReason.REQUEST_BUDGET
            else:
                self._stop_reason = self._quality_violation(stats)
        return self._stop_reason

    def _update_infra_counter(self, record: RequestRecord) -> None:
        """Increment / reset the consecutive-infra counter based on the latest outcome.

        Args:
            record (RequestRecord): the record just emitted.
        """
        if self._is_infra_failure(record):
            if (record.submitted_ts - self._last_infra_ts) > self._infra_window_s:
                self._consecutive_infra_failures = 1
            else:
                self._consecutive_infra_failures += 1
            self._last_infra_ts = record.submitted_ts
        else:
            self._consecutive_infra_failures = 0

    @staticmethod
    def _is_infra_failure(record: RequestRecord) -> bool:
        """Return True if the outcome looks like apparatus / transport failure.

        Counts as infra: `timeout`, `drop`, or `5xx` with status 503 (admission overload). Other 5xx codes are treated as business-style failures so planted-failure mechanisms do not falsely trip the infra stop.

        Args:
            record (RequestRecord): the record under test.

        Returns:
            bool: True for transport-level failures; False otherwise.
        """
        _ans = False
        if record.outcome in ("timeout", "drop"):
            _ans = True
        if record.outcome == "5xx" and record.status_code == 503:
            _ans = True
        return _ans

    def _infra_failure_tripped(self) -> bool:
        """Return True if the consecutive-infra counter reached the threshold.

        Returns:
            bool: True if `_consecutive_infra_failures >= _infra_threshold`.
        """
        return self._consecutive_infra_failures >= self._infra_threshold

    def _quality_violation(self, stats: Stats) -> StopReason:
        """Return the matching `StopReason` if a quality threshold is breached.

        Args:
            stats (Stats): the live aggregator.

        Returns:
            StopReason: `QUALITY_R1_FAILURE_RATE`, `QUALITY_R2_RESPONSE_TIME`, or `NONE`. R1 wins ties so a single update never fires both at once.
        """
        _reason = StopReason.NONE
        # R1 first; R2 only checked when R1 is clean so the sticky reason is unambiguous.
        if self._quality.r1_failure_rate_max is not None:
            _rate = stats.failure_rate(self._quality.window_s)
            if _rate > self._quality.r1_failure_rate_max:
                _reason = StopReason.QUALITY_R1_FAILURE_RATE
        if _reason == StopReason.NONE and self._quality.r2_latency_s_max is not None:
            _mean = stats.mean_latency_s(self._quality.window_s)
            if _mean > self._quality.r2_latency_s_max:
                _reason = StopReason.QUALITY_R2_RESPONSE_TIME
        return _reason
