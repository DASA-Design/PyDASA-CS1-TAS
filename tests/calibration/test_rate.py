# -*- coding: utf-8 -*-
"""
Module test_rate.py
===================

Pin the boundary contract of `batch_size_for` and `find_highest_sustainable_rate`. The full `run_rate_sweep` end-to-end (vernier spawn + multi-rate probe) is exercised behind `@pytest.mark.live_mesh` because each trial carries a `max_probe_window_s` cost; the default suite stays under a second.

    - **TestRate** `batch_size_for` boundary table; `find_highest_sustainable_rate` walks aggregates and returns the highest passing rate (or None); the absolute-value loss check covers over-delivery as well as under-delivery.
"""
# native python modules
from typing import Dict

# module under test
from src.calibration import batch_size_for, find_highest_sustainable_rate


def _agg(target: float, mean_loss_pct: float) -> Dict[str, float]:
    """*_agg()* one-key shorthand: aggregate dict carrying just the field `find_highest_sustainable_rate` reads.

    Args:
        target (float): target rate label (kept for fidelity; unused by the predicate).
        mean_loss_pct (float): the loss value the predicate inspects.

    Returns:
        Dict[str, float]: minimal aggregate with `target` + `mean_loss_pct`.
    """
    return {"target": target, "mean_loss_pct": mean_loss_pct}


class TestRate:
    """**TestRate** pure helpers from `src.calibration.rate`. `batch_size_for` derives a per-tick send batch from `_TARGET_TICK_S=0.020` and the target rate, clamped to >= 1; `find_highest_sustainable_rate` returns the largest rate whose `|mean_loss_pct| <= threshold` after walking the aggregates in ascending order."""

    def test_batch_zero(self) -> None:
        """*test_batch_zero()* `batch_size_for(0.0) == 1` (clamped)."""
        assert batch_size_for(0.0) == 1

    def test_batch_negative(self) -> None:
        """*test_batch_negative()* `batch_size_for(-1.0) == 1` (clamped; defensive)."""
        assert batch_size_for(-1.0) == 1

    def test_batch_low(self) -> None:
        """*test_batch_low()* a rate below `1/_TARGET_TICK_S = 50 req/s` produces batch == 1."""
        assert batch_size_for(10.0) == 1
        assert batch_size_for(40.0) == 1

    def test_batch_at_tick(self) -> None:
        """*test_batch_at_tick()* `batch_size_for(50.0) == round(0.020 / (1/50)) == 1`."""
        assert batch_size_for(50.0) == 1

    def test_batch_high(self) -> None:
        """*test_batch_high()* `batch_size_for(500.0) == round(0.020 / (1/500)) == 10`."""
        assert batch_size_for(500.0) == 10

    def test_find_empty(self) -> None:
        """*test_find_empty()* an empty aggregates dict returns None."""
        assert find_highest_sustainable_rate({}, 5.0) is None

    def test_find_all_above(self) -> None:
        """*test_find_all_above()* every rate fails the bar -> None."""
        _agg_dict = {
            10.0: _agg(10.0, 8.0),
            20.0: _agg(20.0, 12.0),
        }
        assert find_highest_sustainable_rate(_agg_dict, 5.0) is None

    def test_find_highest_passing(self) -> None:
        """*test_find_highest_passing()* mixed pass/fail rates -> highest passing rate."""
        _agg_dict = {
            10.0: _agg(10.0, 1.0),
            50.0: _agg(50.0, 2.0),
            100.0: _agg(100.0, 4.5),
            200.0: _agg(200.0, 7.0),
        }
        assert find_highest_sustainable_rate(_agg_dict, 5.0) == 100.0

    def test_find_at_threshold(self) -> None:
        """*test_find_at_threshold()* `mean_loss_pct == threshold` is non-strict (passes)."""
        _agg_dict = {
            10.0: _agg(10.0, 5.0),
            20.0: _agg(20.0, 5.001),
        }
        assert find_highest_sustainable_rate(_agg_dict, 5.0) == 10.0

    def test_find_over_delivery(self) -> None:
        """*test_find_over_delivery()* negative `mean_loss_pct` (over-delivery) is symmetric: `|loss| <= threshold` is the gate."""
        _agg_dict = {
            10.0: _agg(10.0, -3.0),
            20.0: _agg(20.0, -10.0),
        }
        assert find_highest_sustainable_rate(_agg_dict, 5.0) == 10.0
