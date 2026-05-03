# -*- coding: utf-8 -*-
"""
Module test_stability.py
========================

Pin the boundary contract of `aggregate_stability_cell` and `select_c_per_n_con_usr`. The full `run_handler_stability_sweep` (vernier spawn per c value, multi-trial probe per cell) carries minutes of wall time and is exercised behind `@pytest.mark.live_mesh`; the default suite stays inline.

    - **TestStability** `aggregate_stability_cell` empty / single / multi-trial cases plus unknown-metric NaN; `select_c_per_n_con_usr` honours both selection rules including the `min_c_meeting_target` -> `argmin_error` fallback when no c clears the bar.
"""
# native python modules
import math
from typing import Dict, Tuple

# testing framework
import pytest

# module under test
from src.calibration import (aggregate_stability_cell,
                             select_c_per_n_con_usr)


class TestStability:
    """**TestStability** pure helpers from `src.calibration.stability`. `aggregate_stability_cell` collapses per-trial medians into a single relative-error score (NaN for empty / single-sample / unknown-metric cells); `select_c_per_n_con_usr` walks each n-row in `n_grid` and picks the smallest c whose `error_pct <= target` (or argmin-error when none clears the bar)."""

    def test_agg_empty(self) -> None:
        """*test_agg_empty()* empty trials -> all-zero stats with `error_pct=NaN`, `n_trials=0`."""
        _c = aggregate_stability_cell([], "relative_std_of_median")
        assert _c["mean_median_us"] == 0.0
        assert _c["std_median_us"] == 0.0
        assert math.isnan(_c["error_pct"])
        assert _c["n_trials"] == 0

    def test_agg_single(self) -> None:
        """*test_agg_single()* one trial -> `error_pct=NaN` (no std with n=1)."""
        _c = aggregate_stability_cell([100.0], "relative_std_of_median")
        assert _c["mean_median_us"] == 100.0
        assert _c["std_median_us"] == 0.0
        assert math.isnan(_c["error_pct"])
        assert _c["n_trials"] == 1

    def test_agg_multi(self) -> None:
        """*test_agg_multi()* 5 trials with mean 100 and std ~5 -> `0 < error_pct < 10`."""
        _trials = [95.0, 100.0, 105.0, 100.0, 100.0]
        _c = aggregate_stability_cell(_trials, "relative_std_of_median")
        assert _c["mean_median_us"] == pytest.approx(100.0)
        assert _c["error_pct"] > 0.0
        assert _c["error_pct"] < 10.0
        assert _c["n_trials"] == 5

    def test_agg_unknown_metric(self) -> None:
        """*test_agg_unknown_metric()* an unknown metric returns NaN so the selector logs a warning rather than crashing."""
        _c = aggregate_stability_cell([1.0, 2.0, 3.0], "not-a-metric")
        assert math.isnan(_c["error_pct"])

    def test_agg_zero_mean(self) -> None:
        """*test_agg_zero_mean()* a row of zeros -> mean=0 -> `error_pct=NaN` (cannot divide by zero)."""
        _c = aggregate_stability_cell([0.0, 0.0, 0.0], "relative_std_of_median")
        assert math.isnan(_c["error_pct"])

    def test_select_meeting_target(self) -> None:
        """*test_select_meeting_target()* with cells covering c=[1,2,4] at n=10, the smallest c whose `error_pct <= 5.0` wins."""
        _cells: Dict[Tuple[int, int], Dict[str, float]] = {
            (10, 1): {"error_pct": 8.0},
            (10, 2): {"error_pct": 4.0},
            (10, 4): {"error_pct": 2.0},
        }
        _selected = select_c_per_n_con_usr(_cells, [10], [1, 2, 4],
                                           target_error_pct=5.0,
                                           selection_rule="min_c_meeting_target")
        assert _selected == [2]

    def test_select_argmin_fallback(self) -> None:
        """*test_select_argmin_fallback()* when no c clears the bar, `min_c_meeting_target` falls back to argmin-error."""
        _cells: Dict[Tuple[int, int], Dict[str, float]] = {
            (10, 1): {"error_pct": 12.0},
            (10, 2): {"error_pct": 8.0},
            (10, 4): {"error_pct": 6.0},
        }
        _selected = select_c_per_n_con_usr(_cells, [10], [1, 2, 4],
                                           target_error_pct=5.0,
                                           selection_rule="min_c_meeting_target")
        assert _selected == [4]

    def test_select_argmin_rule(self) -> None:
        """*test_select_argmin_rule()* `argmin_error` ignores the target and picks the c with the lowest `error_pct`."""
        _cells: Dict[Tuple[int, int], Dict[str, float]] = {
            (10, 1): {"error_pct": 5.0},
            (10, 2): {"error_pct": 1.0},
            (10, 4): {"error_pct": 3.0},
        }
        _selected = select_c_per_n_con_usr(_cells, [10], [1, 2, 4],
                                           target_error_pct=2.0,
                                           selection_rule="argmin_error")
        assert _selected == [2]

    def test_select_empty_row(self) -> None:
        """*test_select_empty_row()* when no cell exists for an n-level, fall back to the smallest c in the grid."""
        _selected = select_c_per_n_con_usr({}, [10], [4, 8, 16],
                                           target_error_pct=5.0,
                                           selection_rule="min_c_meeting_target")
        assert _selected == [4]

    def test_select_multi_n(self) -> None:
        """*test_select_multi_n()* one selection per n-level in the order of `n_grid`."""
        _cells: Dict[Tuple[int, int], Dict[str, float]] = {
            (10, 1): {"error_pct": 2.0},
            (20, 1): {"error_pct": 8.0},
            (20, 2): {"error_pct": 3.0},
        }
        _selected = select_c_per_n_con_usr(_cells, [10, 20], [1, 2],
                                           target_error_pct=5.0,
                                           selection_rule="min_c_meeting_target")
        assert _selected == [1, 2]

    def test_select_skips_nan(self) -> None:
        """*test_select_skips_nan()* cells with `error_pct=NaN` are not eligible for `meeting_target`; the selector treats them as missing data."""
        _cells: Dict[Tuple[int, int], Dict[str, float]] = {
            (10, 1): {"error_pct": float("nan")},
            (10, 2): {"error_pct": 3.0},
        }
        _selected = select_c_per_n_con_usr(_cells, [10], [1, 2],
                                           target_error_pct=5.0,
                                           selection_rule="min_c_meeting_target")
        assert _selected == [2]
