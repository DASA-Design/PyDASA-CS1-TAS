"""Tests for `src.experimental.prototype.client.stats`.

**TestStats**:

- `test_count_grows`: confirms `count()` reflects every appended record so callers can read total dispatched volume.
- `test_failure_rate_all`: confirms the failure rate over the full record set equals failed / total so the verdict layer reads the right number.
- `test_failure_rate_windowed`: confirms a trailing window restricts the rate calculation to recent records so quality verdicts respect the configured window.
- `test_mean_latency_successes`: confirms only successful records contribute to mean latency so timeout / drop / 5xx records do not skew R2.
- `test_percentile_basic`: confirms the percentile path returns a sensible value over a known distribution.
- `test_percentile_invalid`: confirms an out-of-range percentile raises `ValueError` rather than silently producing a wrong number.
- `test_outcome_counts`: confirms the outcome dictionary always carries a key per outcome label so consumers do not need defensive `.get()`.
- `test_summary_shape`: confirms the `summary()` payload exposes every field downstream verdict / plot code expects.
- `test_empty_zeros`: confirms an aggregator with no records returns sensible zeros for `count`, `failure_rate`, mean and percentile latencies, so callers do not need defensive checks.
- `test_window_excludes_old`: confirms a trailing window selects only records within the window, leaving older ones out of every metric so the verdict layer never reads stale data.
"""

from __future__ import annotations

import pytest

from src.experimental.prototype.client.stats import Stats
from tests.utils.exp.factories import make_record


class TestStats:
    """In-memory rolling-window aggregator over `RequestRecord` instances."""

    def test_count_grows(self) -> None:
        """Appending N records advances `count()` from 0 to N, demonstrating every record reaches the deque."""
        _stats = Stats()
        for _i in range(5):
            _stats.update(make_record(_i))
        assert _stats.count() == 5

    def test_failure_rate_all(self) -> None:
        """Two failures out of four records is a 0.5 failure rate; the aggregator returns exactly that fraction so the verdict layer sees a stable number."""
        _stats = Stats()
        _stats.update(make_record(0, "success"))
        _stats.update(make_record(1, "timeout"))
        _stats.update(make_record(2, "5xx"))
        _stats.update(make_record(3, "success"))
        assert _stats.failure_rate() == 0.5

    def test_failure_rate_windowed(self) -> None:
        """A 1-second trailing window restricts the calculation to the latest two records; in this case both succeeded, so the windowed rate is 0 even though the full-history rate is non-zero."""
        _stats = Stats()
        _stats.update(make_record(0, "timeout"))
        _stats.update(make_record(1, "5xx"))
        _stats.update(make_record(2, "success"))
        _stats.update(make_record(3, "success"))
        # window covers ts in [3 - 1, 3] = {2, 3}; both successes
        assert _stats.failure_rate(window_s=1.0) == 0.0

    def test_mean_latency_successes(self) -> None:
        """Failed records are excluded from the mean-latency calculation, so a slow timeout does not inflate the success-path R2 number."""
        _stats = Stats()
        _stats.update(make_record(0, "success", latency=0.01))
        _stats.update(make_record(1, "timeout", latency=5.0))
        _stats.update(make_record(2, "success", latency=0.03))
        _mean = _stats.mean_latency_s()
        assert abs(_mean - 0.02) < 1e-9

    def test_percentile_basic(self) -> None:
        """Over latencies {1, 2, 3, 4, 5} ms, the median is around the middle of the distribution; the aggregator returns a value within that range."""
        _stats = Stats()
        for _i, _lat in enumerate([0.001, 0.002, 0.003, 0.004, 0.005]):
            _stats.update(make_record(_i, "success", latency=_lat))
        _p50 = _stats.latency_percentile(50)
        assert 0.001 <= _p50 <= 0.005

    def test_percentile_invalid(self) -> None:
        """A percentile outside the half-open `(0, 100]` interval raises `ValueError`, surfacing misuse loudly at the call site."""
        _stats = Stats()
        with pytest.raises(ValueError, match="percentile must be in"):
            _stats.latency_percentile(0)
        with pytest.raises(ValueError, match="percentile must be in"):
            _stats.latency_percentile(101)

    def test_outcome_counts(self) -> None:
        """The outcome dictionary always carries a key per terminal outcome (`success`, `timeout`, `drop`, `5xx`), so downstream code can read counts without defensive `.get()` fallbacks."""
        _stats = Stats()
        _stats.update(make_record(0, "success"))
        _stats.update(make_record(1, "timeout"))
        _counts = _stats.outcome_counts()
        assert set(_counts.keys()) == {"success", "timeout", "drop", "5xx"}
        assert _counts["success"] == 1
        assert _counts["timeout"] == 1
        assert _counts["drop"] == 0

    def test_summary_shape(self) -> None:
        """The `summary()` payload exposes every field the verdict layer and plotting helpers consume; a single test pins the shape contract."""
        _stats = Stats()
        _stats.update(make_record(0, "success", latency=0.01))
        _summary = _stats.summary()
        assert set(_summary.keys()) == {
            "count",
            "failure_rate",
            "mean_latency_s",
            "latency_p50",
            "latency_p95",
            "latency_p99",
            "outcomes",
        }

    def test_empty_zeros(self) -> None:
        """An aggregator with no records returns 0 for `count`, 0.0 for every rate / mean / percentile metric (over both the full history and a windowed view), so callers can rely on zeros rather than wrap each call in a defensive guard."""
        _stats = Stats()
        assert _stats.count() == 0
        assert _stats.failure_rate() == 0.0
        assert _stats.failure_rate(window_s=10.0) == 0.0
        assert _stats.mean_latency_s() == 0.0
        assert _stats.latency_percentile(50) == 0.0

    def test_window_excludes_old(self) -> None:
        """A trailing window selects only records whose `submitted_ts` is within `window_s` of the latest record; older records are excluded from every per-window metric so the verdict layer reads only fresh data."""
        _stats = Stats()
        _stats.update(make_record(0, "timeout", latency=0.5))
        _stats.update(make_record(100, "success", latency=0.02))
        # 1-second window covers only the second record
        assert _stats.count() == 2
        assert _stats.failure_rate(window_s=1.0) == 0.0
        assert _stats.mean_latency_s(window_s=1.0) == 0.02
