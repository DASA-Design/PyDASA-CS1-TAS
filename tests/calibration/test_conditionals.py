# -*- coding: utf-8 -*-
"""
Module test_conditionals.py
===========================

Pin the boundary contract of `StopConditions` and the three pure predicates (`should_stop`, `should_stop_detailed`, `loopback_two_trial_ok`). Exhaustive at-boundary coverage so future stop-rule edits can be reviewed against the methodology decisions in `notes/calibration.md` (locked I-1: rejection > 5%; phi >= 1.0; sigma > 2.0; loopback two-trial <= 5%).

    - **TestStopConditions** dataclass shape: defaults, frozen, `from_config` partial / empty / float coercion.
    - **TestPredicates** the three predicates: `should_stop` boundary table + precedence; `should_stop_detailed` dict shape + per-trigger flags + agreement with `should_stop`; `loopback_two_trial_ok` symmetric delta + ok/not-ok boundary + non-positive raise.
"""
# native python modules
import dataclasses

# testing framework
import pytest

# module under test
from src.calibration import (StopConditions,
                             loopback_two_trial_ok,
                             should_stop,
                             should_stop_detailed)


class TestStopConditions:
    """**TestStopConditions** dataclass-shape contract: defaults match the JSON-side `stop_conditions` block in `notes/calibration.md`; the instance is frozen; `from_config` honours partial / empty / float-coerced dicts."""

    def test_defaults(self) -> None:
        """*test_defaults()* default `StopConditions()` carries `rejection=5.0`, `phi=1.0`, `sigma=2.0`, `loopback_delta=5.0`."""
        _c = StopConditions()
        assert _c.rejection_threshold_pct == 5.0
        assert _c.phi_threshold == 1.0
        assert _c.sigma_max_clip == 2.0
        assert _c.loopback_two_trial_delta_pct == 5.0

    def test_frozen(self) -> None:
        """*test_frozen()* attempting to mutate any field raises `dataclasses.FrozenInstanceError`."""
        _c = StopConditions()
        with pytest.raises(dataclasses.FrozenInstanceError):
            _c.rejection_threshold_pct = 99.0  # type: ignore[misc]

    def test_from_config_full(self) -> None:
        """*test_from_config_full()* a config dict with all four keys produces fields equal to the dict values."""
        _c = StopConditions.from_config({
            "rejection_threshold_pct": 10.0,
            "phi_threshold": 0.9,
            "sigma_max_clip": 3.0,
            "loopback_two_trial_delta_pct": 1.5,
        })
        assert _c.rejection_threshold_pct == 10.0
        assert _c.phi_threshold == 0.9
        assert _c.sigma_max_clip == 3.0
        assert _c.loopback_two_trial_delta_pct == 1.5

    def test_from_config_partial(self) -> None:
        """*test_from_config_partial()* missing keys fall back to dataclass defaults; one explicit + three defaulted produces the expected hybrid."""
        _c = StopConditions.from_config({"sigma_max_clip": 7.5})
        assert _c.sigma_max_clip == 7.5
        assert _c.rejection_threshold_pct == 5.0
        assert _c.phi_threshold == 1.0
        assert _c.loopback_two_trial_delta_pct == 5.0

    def test_from_config_empty(self) -> None:
        """*test_from_config_empty()* an empty config dict equals the default `StopConditions()`."""
        assert StopConditions.from_config({}) == StopConditions()

    def test_from_config_float_coercion(self) -> None:
        """*test_from_config_float_coercion()* int values in JSON survive as floats on the dataclass."""
        _c = StopConditions.from_config({"rejection_threshold_pct": 5})
        assert _c.rejection_threshold_pct == 5.0
        assert isinstance(_c.rejection_threshold_pct, float)


class TestPredicates:
    """**TestPredicates** the three module-level predicates: `should_stop` exercises the rejection / phi / sigma boundary table (rejection strict-greater, phi greater-or-equal, sigma strict-greater); `should_stop_detailed` returns the same decision plus per-trigger flags and provenance values; `loopback_two_trial_ok` is symmetric in t1/t2 and raises on non-positive medians."""

    def _conds(self) -> StopConditions:
        """*_conds()* default StopConditions for boundary tests."""
        return StopConditions()

    def test_empty_row(self) -> None:
        """*test_empty_row()* `should_stop({}, conds) is False` (missing keys treated as 0.0)."""
        assert should_stop({}, self._conds()) is False

    def test_under_thresholds(self) -> None:
        """*test_under_thresholds()* `should_stop({"reject_rate_pct": 4.99, "phi": 0.99, "sigma": 1.99}, conds) is False`."""
        _row = {"reject_rate_pct": 4.99, "phi": 0.99, "sigma": 1.99}
        assert should_stop(_row, self._conds()) is False

    def test_rejection_at_threshold(self) -> None:
        """*test_rejection_at_threshold()* `reject_rate_pct == 5.0` (exactly the threshold) returns False; rejection uses strict-greater."""
        _row = {"reject_rate_pct": 5.0, "phi": 0.0, "sigma": 0.0}
        assert should_stop(_row, self._conds()) is False

    def test_rejection_just_over(self) -> None:
        """*test_rejection_just_over()* `reject_rate_pct == 5.0001` returns True."""
        _row = {"reject_rate_pct": 5.0001, "phi": 0.0, "sigma": 0.0}
        assert should_stop(_row, self._conds()) is True

    def test_phi_at_threshold(self) -> None:
        """*test_phi_at_threshold()* `phi == 1.0` returns True; phi uses greater-or-equal because M_act-equals-M_buf is itself the regime change."""
        _row = {"reject_rate_pct": 0.0, "phi": 1.0, "sigma": 0.0}
        assert should_stop(_row, self._conds()) is True

    def test_phi_just_under(self) -> None:
        """*test_phi_just_under()* `phi == 0.9999` returns False."""
        _row = {"reject_rate_pct": 0.0, "phi": 0.9999, "sigma": 0.0}
        assert should_stop(_row, self._conds()) is False

    def test_sigma_at_threshold(self) -> None:
        """*test_sigma_at_threshold()* `sigma == 2.0` (exactly the cap) returns False; sigma uses strict-greater."""
        _row = {"reject_rate_pct": 0.0, "phi": 0.0, "sigma": 2.0}
        assert should_stop(_row, self._conds()) is False

    def test_sigma_just_over(self) -> None:
        """*test_sigma_just_over()* `sigma == 2.0001` returns True."""
        _row = {"reject_rate_pct": 0.0, "phi": 0.0, "sigma": 2.0001}
        assert should_stop(_row, self._conds()) is True

    def test_multi_trip(self) -> None:
        """*test_multi_trip()* a row tripping all three signals returns True; precedence does not change the bool result."""
        _row = {"reject_rate_pct": 99.0, "phi": 5.0, "sigma": 10.0}
        assert should_stop(_row, self._conds()) is True

    def test_extra_keys_ignored(self) -> None:
        """*test_extra_keys_ignored()* unrelated keys are ignored; only `reject_rate_pct` / `phi` / `sigma` are read."""
        _row = {"reject_rate_pct": 0.0, "phi": 0.0, "sigma": 0.0,
                "lambda": 100.0, "throughput": 50.0, "anything": "string"}
        assert should_stop(_row, self._conds()) is False

    def test_custom_thresholds(self) -> None:
        """*test_custom_thresholds()* `StopConditions(rejection_threshold_pct=20.0)` does NOT stop on `reject_rate_pct=10.0`."""
        _conds = StopConditions(rejection_threshold_pct=20.0)
        assert should_stop({"reject_rate_pct": 10.0}, _conds) is False

    def test_detailed_dict_shape(self) -> None:
        """*test_detailed_dict_shape()* `should_stop_detailed({}, conds)` returns the documented six top-level keys; `values` and `thresholds` carry the three signal / threshold keys each."""
        _d = should_stop_detailed({}, StopConditions())
        assert set(_d.keys()) == {"stop", "rejection_triggered",
                                  "phi_triggered", "sigma_triggered",
                                  "values", "thresholds"}
        assert set(_d["values"].keys()) == {"reject_rate_pct", "phi", "sigma"}
        assert set(_d["thresholds"].keys()) == {"rejection_threshold_pct",
                                                "phi_threshold",
                                                "sigma_max_clip"}

    def test_detailed_per_trigger(self) -> None:
        """*test_detailed_per_trigger()* each `*_triggered` flag is True iff its own signal trips, independent of the others."""
        _d = should_stop_detailed({"reject_rate_pct": 10.0,
                                   "phi": 0.5,
                                   "sigma": 0.5},
                                  StopConditions())
        assert _d["rejection_triggered"] is True
        assert _d["phi_triggered"] is False
        assert _d["sigma_triggered"] is False
        assert _d["stop"] is True

    def test_detailed_no_trigger(self) -> None:
        """*test_detailed_no_trigger()* a clean row leaves all three `*_triggered` flags False and `stop=False`."""
        _d = should_stop_detailed({"reject_rate_pct": 1.0,
                                   "phi": 0.5,
                                   "sigma": 0.5},
                                  StopConditions())
        assert _d["stop"] is False
        assert _d["rejection_triggered"] is False
        assert _d["phi_triggered"] is False
        assert _d["sigma_triggered"] is False

    def test_detailed_values_carry_through(self) -> None:
        """*test_detailed_values_carry_through()* the input row's signal values appear verbatim in `values`; missing keys appear as 0.0."""
        _d = should_stop_detailed({"reject_rate_pct": 7.5}, StopConditions())
        assert _d["values"]["reject_rate_pct"] == 7.5
        assert _d["values"]["phi"] == 0.0
        assert _d["values"]["sigma"] == 0.0

    def test_detailed_thresholds_carry_through(self) -> None:
        """*test_detailed_thresholds_carry_through()* the conds' threshold values appear verbatim in `thresholds`."""
        _conds = StopConditions(rejection_threshold_pct=12.5,
                                phi_threshold=0.8,
                                sigma_max_clip=4.0)
        _d = should_stop_detailed({}, _conds)
        assert _d["thresholds"]["rejection_threshold_pct"] == 12.5
        assert _d["thresholds"]["phi_threshold"] == 0.8
        assert _d["thresholds"]["sigma_max_clip"] == 4.0

    def test_detailed_agrees_with_should_stop(self) -> None:
        """*test_detailed_agrees_with_should_stop()* `should_stop_detailed(row, c)["stop"] == should_stop(row, c)` for all sample rows."""
        _conds = StopConditions()
        for _row in [{}, {"reject_rate_pct": 5.0001}, {"phi": 1.0},
                     {"sigma": 2.0001}, {"reject_rate_pct": 99.0,
                                         "phi": 5.0, "sigma": 10.0}]:
            assert should_stop_detailed(_row, _conds)["stop"] == should_stop(_row, _conds)

    def test_loopback_identical(self) -> None:
        """*test_loopback_identical()* two identical medians give `delta_pct=0.0` and `ok=True`."""
        _r = loopback_two_trial_ok(100.0, 100.0, StopConditions())
        assert _r["ok"] is True
        assert _r["delta_pct"] == 0.0

    def test_loopback_under(self) -> None:
        """*test_loopback_under()* a 4% delta against the default 5% threshold returns ok=True."""
        _r = loopback_two_trial_ok(100.0, 104.0, StopConditions())
        assert _r["ok"] is True
        assert _r["delta_pct"] == pytest.approx(4.0 / 104.0 * 100.0)

    def test_loopback_at_threshold(self) -> None:
        """*test_loopback_at_threshold()* a delta exactly at the threshold returns ok=True (non-strict; the gate's 5% is the upper bound)."""
        _conds = StopConditions(loopback_two_trial_delta_pct=5.0)
        _r = loopback_two_trial_ok(100.0, 105.263157894736842, _conds)
        assert _r["delta_pct"] == pytest.approx(5.0)
        assert _r["ok"] is True

    def test_loopback_just_over(self) -> None:
        """*test_loopback_just_over()* a 9.09% delta against the default 5% threshold returns ok=False."""
        _r = loopback_two_trial_ok(100.0, 110.0, StopConditions())
        assert _r["delta_pct"] == pytest.approx(10.0 / 110.0 * 100.0)
        assert _r["ok"] is False

    def test_loopback_symmetric(self) -> None:
        """*test_loopback_symmetric()* swapping t1 and t2 produces the same `delta_pct` and `ok`."""
        _r1 = loopback_two_trial_ok(150.0, 142.0, StopConditions())
        _r2 = loopback_two_trial_ok(142.0, 150.0, StopConditions())
        assert _r1["delta_pct"] == _r2["delta_pct"]
        assert _r1["ok"] == _r2["ok"]

    def test_loopback_dict_shape(self) -> None:
        """*test_loopback_dict_shape()* the returned dict has exactly five keys: `ok`, `delta_pct`, `threshold_pct`, `t1_us`, `t2_us`."""
        _r = loopback_two_trial_ok(100.0, 100.0, StopConditions())
        assert set(_r.keys()) == {"ok", "delta_pct", "threshold_pct",
                                  "t1_us", "t2_us"}

    def test_loopback_threshold_carry_through(self) -> None:
        """*test_loopback_threshold_carry_through()* the conds' delta threshold appears verbatim in `threshold_pct`."""
        _conds = StopConditions(loopback_two_trial_delta_pct=2.5)
        _r = loopback_two_trial_ok(100.0, 100.0, _conds)
        assert _r["threshold_pct"] == 2.5

    def test_loopback_zero_t1_raises(self) -> None:
        """*test_loopback_zero_t1_raises()* `t1=0.0` raises `ValueError` (zero medians are instrument errors)."""
        with pytest.raises(ValueError, match="must be > 0"):
            loopback_two_trial_ok(0.0, 100.0, StopConditions())

    def test_loopback_negative_t2_raises(self) -> None:
        """*test_loopback_negative_t2_raises()* a negative t2 raises `ValueError`."""
        with pytest.raises(ValueError, match="must be > 0"):
            loopback_two_trial_ok(100.0, -1.0, StopConditions())
