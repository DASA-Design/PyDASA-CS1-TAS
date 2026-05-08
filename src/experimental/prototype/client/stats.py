"""`Stats`: rolling-window aggregator over `RequestRecord` outcomes and latencies.

`StopGuard` reads the per-window numbers to decide whether the run breached its quality thresholds (failure rate, mean response time); the verdict module reads the same aggregator to compute R1 / R2 verdicts.

IMPLEMENTATION NOTE: the aggregator keeps the raw record list so percentiles and rates over arbitrary windows are computable without re-reading the JSONL. Memory is bounded at `max_records` (default 10_000) with FIFO eviction. Every `window_s` argument is a trailing window length in seconds, measured back from the most recent `submitted_ts`.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from src.experimental.prototype.client.records import Outcome, RequestRecord

# Runtime fallback for data/config/method/prototype/client.json::stats.max_records.
_DFLT_MAX_RECORDS = 10_000


@dataclass
class Stats:
    """In-memory aggregator over `RequestRecord` instances.

    Records are appended in submission order. `summary` returns the standard counters and latency percentiles over a configurable window measured in seconds (or all records if `window_s` is None).

    Attributes:
        max_records (int): retention cap for the in-memory deque. Defaults to 10_000.
        _records (deque[RequestRecord]): bounded FIFO of recent records; oldest evicted when `max_records` is exceeded. Built in `__post_init__`.
    """

    max_records: int = _DFLT_MAX_RECORDS
    _records: deque[RequestRecord] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build the bounded FIFO deque using the configured `max_records` cap."""
        self._records = deque(maxlen=self.max_records)

    def update(self, record: RequestRecord) -> None:
        """Append one record to the aggregator.

        Args:
            record (RequestRecord): completed-request record to log.
        """
        self._records.append(record)

    def count(self) -> int:
        """Return the total number of records currently held.

        Returns:
            int: record count (capped by `max_records`).
        """
        return len(self._records)

    def failure_rate(self, window_s: float | None = None) -> float:
        """Compute the fraction of non-success outcomes over the window.

        Args:
            window_s (float | None, optional): trailing-window length expressed in seconds, measured against the most recent `submitted_ts`. Defaults to None, which selects all retained records.

        Returns:
            float: failed records divided by total records in the window. Returns 0.0 if the window is empty.
        """
        _window = self._slice_window(window_s)
        if not _window:
            return 0.0
        _failed = sum(1 for _r in _window if _r.outcome != "success")
        return _failed / len(_window)

    def mean_latency_s(self, window_s: float | None = None) -> float:
        """Compute mean end-to-end latency over the window, restricted to successful records.

        Args:
            window_s (float | None, optional): trailing-window length in seconds. Defaults to None (all retained records).

        Returns:
            float: arithmetic mean of `total_latency_s` for successful records in the window. Returns 0.0 if the window has no successes.
        """
        _latencies = self._success_latencies(window_s)
        if not _latencies:
            return 0.0
        return statistics.fmean(_latencies)

    def latency_percentile(self, percentile: float, window_s: float | None = None) -> float:
        """Compute the requested percentile of successful-record latencies.

        Args:
            percentile (float): percentile in the half-open interval `(0, 100]`, e.g. `50` for median.
            window_s (float | None, optional): trailing-window length in seconds. Defaults to None.

        Returns:
            float: the percentile latency in seconds. Returns 0.0 on an empty window.

        Raises:
            ValueError: if `percentile` is outside `(0, 100]`.
        """
        if percentile <= 0 or percentile > 100:
            _msg = f"percentile must be in (0, 100], got {percentile}"
            raise ValueError(_msg)
        _latencies = self._success_latencies(window_s)
        if not _latencies:
            return 0.0
        _sorted = sorted(_latencies)
        _idx = max(0, min(len(_sorted) - 1, int(round(percentile / 100.0 * len(_sorted))) - 1))
        return _sorted[_idx]

    def outcome_counts(self, window_s: float | None = None) -> dict[Outcome, int]:
        """Return a count per terminal outcome over the window.

        Args:
            window_s (float | None, optional): trailing-window length in seconds. Defaults to None.

        Returns:
            dict[Outcome, int]: dict keyed by outcome label; missing outcomes have count 0.
        """
        _window = self._slice_window(window_s)
        _counts: dict[Outcome, int] = {
            "success": 0,
            "timeout": 0,
            "drop": 0,
            "5xx": 0,
        }
        for _r in _window:
            _counts[_r.outcome] += 1
        return _counts

    def summary(self, window_s: float | None = None) -> dict[str, Any]:
        """Return a single-call summary over the window.

        Args:
            window_s (float | None, optional): trailing-window length in seconds. Defaults to None (all retained records).

        Returns:
            dict[str, Any]: `count`, `failure_rate`, `mean_latency_s`, `latency_p50`, `latency_p95`, `latency_p99`, `outcomes`.
        """
        _summary: dict[str, Any] = {
            "count": self.count(),
            "failure_rate": self.failure_rate(window_s),
            "mean_latency_s": self.mean_latency_s(window_s),
            "latency_p50": self.latency_percentile(50, window_s),
            "latency_p95": self.latency_percentile(95, window_s),
            "latency_p99": self.latency_percentile(99, window_s),
            "outcomes": self.outcome_counts(window_s),
        }
        return _summary

    def _slice_window(self, window_s: float | None) -> list[RequestRecord]:
        """Return records within `window_s` of the most recent submission, or all if None.

        Args:
            window_s (float | None): window length; None selects every retained record.

        Returns:
            list[RequestRecord]: shallow copy of records inside the window.
        """
        if window_s is None:
            return list(self._records)
        if not self._records:
            return []
        _latest = self._records[-1].submitted_ts
        _cutoff = _latest - window_s
        _filtered: list[RequestRecord] = []
        for _r in self._records:
            if _r.submitted_ts >= _cutoff:
                _filtered.append(_r)
        return _filtered

    def _success_latencies(self, window_s: float | None) -> list[float]:
        """Return latencies for successful records within the window.

        Args:
            window_s (float | None): window length.

        Returns:
            list[float]: success latencies in seconds, in submission order.
        """
        _window = self._slice_window(window_s)
        _latencies: list[float] = []
        for _r in _window:
            if _r.outcome == "success":
                _latencies.append(_r.total_latency_s)
        return _latencies
