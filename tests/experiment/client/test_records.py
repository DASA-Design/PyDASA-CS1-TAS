# -*- coding: utf-8 -*-
"""
Module test_records.py
======================

Pin the three derived properties on `RequestRecord`: latency clamping, infra-failure flag, business-failure flag.

    - **TestRequestRecord** `response_time_s` / `infra_failure` / `business_failure`.
"""
# test stack
import pytest

# modules under test
from src.experiment.client.records import RequestRecord


class TestRequestRecord:
    """**TestRequestRecord** derived-property contract for one client measurement."""

    def test_rt_clamps_zero(self) -> None:
        """*test_rt_clamps_zero()* `recv_ts < send_ts` -> `response_time_s == 0.0`; positive delta returns the delta verbatim."""
        _r1 = RequestRecord(req_id="x", kind="k", send_ts=1.0, recv_ts=0.5)
        _r2 = RequestRecord(req_id="x", kind="k", send_ts=1.0, recv_ts=1.25)
        assert _r1.response_time_s == 0.0
        assert _r2.response_time_s == pytest.approx(0.25)

    @pytest.mark.parametrize(
        "_status,_expected",
        [(-1, True), (500, True), (503, True), (504, True),
         (200, False), (400, False), (404, False), (429, False)],
    )
    def test_infra_flag(self, _status: int, _expected: bool) -> None:
        """*test_infra_flag()* `infra_failure` is True iff `status_code < 0` or `>= 500`."""
        _rec = RequestRecord(req_id="x",
                             kind="k",
                             status_code=_status)
        assert _rec.infra_failure is _expected

    @pytest.mark.parametrize(
        "_status,_success,_expected",
        [(200, True, False), (200, False, True),
         (500, False, False), (-1, False, False), (400, True, False)],
    )
    def test_biz_flag(self, _status: int, _success: bool, _expected: bool) -> None:
        """*test_biz_flag()* `business_failure` is True iff `status_code == 200 and success is False`."""
        _rec = RequestRecord(req_id="x",
                             kind="k",
                             status_code=_status,
                             success=_success)
        assert _rec.business_failure is _expected
