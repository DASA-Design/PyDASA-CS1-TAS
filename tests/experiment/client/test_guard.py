# -*- coding: utf-8 -*-
"""
Module test_guard.py
====================

Pin the `StopGuard` halt rules: rolling threshold, fail-fast, idempotency, `reset()`.

    - **TestStopGuard** rolling + fail-fast + idempotency + reset.
"""
# modules under test
from src.experiment.client.config import CascadeCfg
from src.experiment.client.guard import StopGuard
from src.experiment.client.records import RequestRecord

# shared helpers
from tests.utils.helpers import _make_records


class TestStopGuard:
    """**TestStopGuard** rolling threshold, fail-fast, idempotency, reset."""

    def test_fail_fast_on_infra(self) -> None:
        """*test_fail_fast_on_infra()* 5 OK -> not tripped; 1 503 -> `tripped is True`, `"503" in reason`."""
        _g = StopGuard(CascadeCfg(mode="fail_fast"))
        for _r in _make_records(n=5):
            _g.observe(_r)
        assert _g.tripped is False
        _g.observe(_make_records(n=1,
                                 status_code=503,
                                 success=False,
                                 id_prefix="e")[0])
        assert _g.tripped is True
        assert _g.reason is not None
        assert "503" in _g.reason

    def test_fail_fast_skips_biz(self) -> None:
        """*test_fail_fast_skips_biz()* 50 `(200, success=False)` records -> `tripped is False`."""
        _g = StopGuard(CascadeCfg(mode="fail_fast"))
        _biz = RequestRecord(req_id="b",
                             kind="k",
                             status_code=200,
                             success=False)
        for _ in range(50):
            _g.observe(_biz)
        assert _g.tripped is False

    def test_rolling_holds_at_threshold(self) -> None:
        """*test_rolling_holds_at_threshold()* `5/50 == 0.10` (not strictly > 0.10) -> `tripped is False`."""
        _g = StopGuard(CascadeCfg(mode="rolling", threshold=0.10, window=50))
        _stream = _make_records(n=45) + _make_records(n=5,
                                                      status_code=503,
                                                      success=False,
                                                      id_prefix="e")
        for _r in _stream:
            _g.observe(_r)
        assert _g.tripped is False

    def test_rolling_trips_above(self) -> None:
        """*test_rolling_trips_above()* `10/50 == 0.20 > 0.10` -> `tripped is True`, `"rolling" in reason`."""
        _g = StopGuard(CascadeCfg(mode="rolling", threshold=0.10, window=50))
        _stream = _make_records(n=40) + _make_records(n=10,
                                                      status_code=503,
                                                      success=False,
                                                      id_prefix="e")
        for _r in _stream:
            _g.observe(_r)
        assert _g.tripped is True
        assert _g.reason is not None
        assert "rolling" in _g.reason

    def test_rolling_partial_window(self) -> None:
        """*test_rolling_partial_window()* 49 infra in a 50-window -> `tripped is False` (window not yet full)."""
        _g = StopGuard(CascadeCfg(mode="rolling", threshold=0.10, window=50))
        for _r in _make_records(n=49,
                                status_code=503,
                                success=False,
                                id_prefix="e"):
            _g.observe(_r)
        assert _g.tripped is False

    def test_idempotent_after_trip(self) -> None:
        """*test_idempotent_after_trip()* further `observe()` calls after a trip leave `reason` unchanged."""
        _g = StopGuard(CascadeCfg(mode="fail_fast"))
        _g.observe(_make_records(n=1,
                                 status_code=500,
                                 success=False,
                                 id_prefix="e")[0])
        _first_reason = _g.reason
        _g.observe(_make_records(n=1,
                                 status_code=503,
                                 success=False,
                                 id_prefix="e")[0])
        _g.observe(_make_records(n=1,
                                 status_code=200,
                                 success=True,
                                 id_prefix="e")[0])
        assert _g.reason == _first_reason

    def test_reset_clears_state(self) -> None:
        """*test_reset_clears_state()* after `reset()`: `tripped is False`, `reason is None`, and 50 fresh OK records do not re-trip."""
        _g = StopGuard(CascadeCfg(mode="fail_fast"))
        _g.observe(_make_records(n=1,
                                 status_code=503,
                                 success=False,
                                 id_prefix="e")[0])
        assert _g.tripped is True
        _g.reset()
        assert _g.tripped is False
        assert _g.reason is None
        for _r in _make_records(n=50):
            _g.observe(_r)
        assert _g.tripped is False
