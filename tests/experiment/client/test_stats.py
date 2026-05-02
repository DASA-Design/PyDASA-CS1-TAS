# -*- coding: utf-8 -*-
"""
Module test_stats.py
====================

Pin the `compute_probe_stats` aggregation: per-kind percentiles over successful records, infra/business fail rates over all records, effective send rate from `total / duration_s`.

    - **TestComputeProbeStats** percentiles, fail rates, effective rate, empty-input edge cases.
"""
# native python modules
from typing import List

# test stack
import pytest

# modules under test
from src.experiment.client.records import RequestRecord
from src.experiment.client.stats import compute_probe_stats

# shared helpers
from tests.utils.helpers import _make_records


class TestComputeProbeStats:
    """**TestComputeProbeStats** percentile + fail-rate + effective-rate aggregation."""

    def test_per_kind_percentiles(self) -> None:
        """*test_per_kind_percentiles()* `stats_per_kind["k"]["mean_ms"] == mean(rts_ms)`, `p50_ms == sorted[n//2]`, `p95_ms == sorted[min(int(n*0.95), n-1)]`."""
        _records = _make_records(kind="k",
                                 rts_ms=[10.0, 20.0, 30.0, 40.0, 50.0])
        _out = compute_probe_stats(_records,
                                   counts={"k": 5},
                                   duration_s=1.0,
                                   rate=5.0,
                                   stop_reason="samples_reached",
                                   kind_names=["k"])
        _stats = _out["stats_per_kind"]["k"]
        assert _stats["n"] == 5
        assert _stats["mean_ms"] == pytest.approx(30.0)
        assert _stats["p50_ms"] == pytest.approx(30.0)
        assert _stats["p95_ms"] == pytest.approx(50.0)

    def test_empty_kind_n_zero(self) -> None:
        """*test_empty_kind_n_zero()* a kind with zero status-200 records yields `{"n": 0}` (no `mean_ms` keys)."""
        _records: List[RequestRecord] = []
        _records.extend(_make_records(n=1,
                                      status_code=503,
                                      success=False,
                                      id_prefix="e"))
        _out = compute_probe_stats(_records,
                                   counts={"k": 0},
                                   duration_s=1.0,
                                   rate=1.0,
                                   stop_reason="samples_reached",
                                   kind_names=["k"])
        assert _out["stats_per_kind"]["k"] == {"n": 0}

    def test_infra_biz_rates(self) -> None:
        """*test_infra_biz_rates()* `infra_fail_rate = infra_count / total`, `business_fail_rate = biz_count / total`."""
        _records: List[RequestRecord] = []
        _records.extend(_make_records(kind="k",
                                      rts_ms=[5.0, 5.0]))
        _records.append(RequestRecord(req_id="x",
                                      kind="k",
                                      status_code=200,
                                      success=False))
        _records.append(RequestRecord(req_id="x",
                                      kind="k",
                                      status_code=503,
                                      success=False))
        _out = compute_probe_stats(_records,
                                   counts={"k": 2},
                                   duration_s=1.0,
                                   rate=4.0,
                                   stop_reason="samples_reached",
                                   kind_names=["k"])
        assert _out["total"] == 4
        assert _out["infra_fail_rate"] == pytest.approx(0.25)
        assert _out["business_fail_rate"] == pytest.approx(0.25)

    def test_effective_rate(self) -> None:
        """*test_effective_rate()* `effective_rate == total / duration_s`; `0.0` when `duration_s <= 0`."""
        _recs = _make_records(kind="k", rts_ms=[1.0] * 10)
        _out = compute_probe_stats(_recs,
                                   counts={"k": 10},
                                   duration_s=2.0,
                                   rate=5.0,
                                   stop_reason="samples_reached",
                                   kind_names=["k"])
        assert _out["effective_rate"] == pytest.approx(5.0)
        _out_zero = compute_probe_stats(_recs, counts={"k": 10},
                                        duration_s=0.0,
                                        rate=5.0,
                                        stop_reason="probe_timeout",
                                        kind_names=["k"])
        assert _out_zero["effective_rate"] == 0.0

    def test_empty_records(self) -> None:
        """*test_empty_records()* zero records -> `total=0`, `infra_fail_rate=0.0`, `business_fail_rate=0.0`, every kind reports `{"n": 0}`."""
        _out = compute_probe_stats([],
                                   counts={},
                                   duration_s=1.0,
                                   rate=1.0,
                                   stop_reason="probe_timeout",
                                   kind_names=["k1", "k2"])
        assert _out["total"] == 0
        assert _out["infra_fail_rate"] == 0.0
        assert _out["business_fail_rate"] == 0.0
        assert _out["stats_per_kind"]["k1"] == {"n": 0}
        assert _out["stats_per_kind"]["k2"] == {"n": 0}
