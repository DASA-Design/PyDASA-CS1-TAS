# -*- coding: utf-8 -*-
"""
Module client/stats.py
======================

Pure aggregation step: turn one probe's `RequestRecord` list into a typed summary dict consumed by `RateDriver.run` / `ClientSimulator.run_ramp`. No state.
"""
# native python modules
from __future__ import annotations

from typing import Any, Dict, Iterable, List

# local modules
from src.experiment.client.records import RequestRecord


def compute_probe_stats(records: List[RequestRecord],
                        counts: Dict[str, int],
                        duration_s: float,
                        rate: float,
                        stop_reason: str,
                        kind_names: Iterable[str]) -> Dict[str, Any]:
    """*compute_probe_stats()* fold one probe's records into a summary dict.

    Per kind: number of successful responses (status 200) plus mean / p50 / p95 latency in milliseconds. Across all records: infra-failure share, business-failure share, and the effective send rate `total / duration_s`.

    Args:
        records (List[RequestRecord]): every invocation record from the probe.
        counts (Dict[str, int]): per-kind successful-completion counts (status 200).
        duration_s (float, seconds): probe wall-clock duration.
        rate (float, req/s): the target rate the probe was driven at.
        stop_reason (str): why the probe loop exited.
        kind_names (Iterable[str]): canonical kind labels in the order to report.

    Returns:
        Dict[str, Any]: keys `rate`, `effective_rate`, `duration_s`, `total`, `samples_per_kind`, `stats_per_kind`, `infra_fail_rate`, `business_fail_rate`, `stopped_reason`, `records`.
    """
    _samples_per_kind: Dict[str, int] = dict(counts)
    _stats_per_kind: Dict[str, Dict[str, float]] = {}
    for _kind in kind_names:
        _kind_recs: List[RequestRecord] = []
        for _r in records:
            _matches_kind = _r.kind == _kind
            _is_ok = _r.status_code == 200
            if _matches_kind and _is_ok:
                _kind_recs.append(_r)
        if not _kind_recs:
            _stats_per_kind[_kind] = {"n": 0}
            continue
        _rts = sorted(_r.response_time_s * 1000 for _r in _kind_recs)
        _n = len(_rts)
        _entry: Dict[str, float] = {}
        _entry["n"] = _n
        _entry["mean_ms"] = sum(_rts) / _n
        _entry["p50_ms"] = _rts[_n // 2]
        _entry["p95_ms"] = _rts[min(int(_n * 0.95), _n - 1)]
        _stats_per_kind[_kind] = _entry

    _total = len(records)
    _infra = sum(1 for _r in records if _r.infra_failure)
    _biz = sum(1 for _r in records if _r.business_failure)
    if _total > 0:
        _infra_rate = _infra / _total
        _biz_rate = _biz / _total
    else:
        _infra_rate = 0.0
        _biz_rate = 0.0

    if duration_s > 0:
        _effective_rate = _total / duration_s
    else:
        _effective_rate = 0.0

    _summary: Dict[str, Any] = {}
    _summary["rate"] = rate
    _summary["effective_rate"] = _effective_rate
    _summary["duration_s"] = duration_s
    _summary["total"] = _total
    _summary["samples_per_kind"] = _samples_per_kind
    _summary["stats_per_kind"] = _stats_per_kind
    _summary["infra_fail_rate"] = _infra_rate
    _summary["business_fail_rate"] = _biz_rate
    _summary["stopped_reason"] = stop_reason
    _summary["records"] = records
    return _summary
