"""Tests for `src.experimental.prototype.controller.strategies`.

**TestExtractOpWeights**:

- `test_three_ops`: a 3-node `_routs` matrix yields one normalised row per operation.
- `test_drops_diagonal`: the diagonal column is dropped as per-service epsilon.
- `test_unknown_scenario`: unknown scenario raises `KeyError`.

**TestPickers**:

- `test_baseline_weighted`: weighted-random picks favour the heavier weight.
- `test_baseline_fallback`: missing weights fall back to catalogue first-of-kind.
- `test_s1_chain`: `RetryOnFailurePicker` returns up to `max_attempts` distinct candidates.
- `test_s2_picks_reliable`: `PreferReliablePicker` picks the lowest observed failure rate.
- `test_s2_unseen`: unseen svc has failure_rate=0 and ties for best.
- `test_aggregate_ranked`: `RetryAndPreferReliablePicker` ranks then truncates.
- `test_make_picker`: `make_picker(adp, ...)` returns the right class per adp.
- `test_unknown_adp`: unknown adp raises `KeyError`.
- `test_unknown_wire`: unknown wire name raises `ValueError`.
"""

from __future__ import annotations

import random

import pytest

from src.experimental.prototype.controller.strategies import (
    FirstOfKindPicker,
    PreferReliablePicker,
    RetryAndPreferReliablePicker,
    RetryOnFailurePicker,
    extract_op_weights,
    make_picker,
    picker_from_wire,
    picker_name_for,
)
from src.experimental.prototype.target.service.catalogue import (
    ServiceCatalogue,
    ServiceCatalogueEntry,
)


def _catalogue(*entries: tuple[str, str]) -> ServiceCatalogue:
    """Build a tiny catalogue from `(svc_id, kind)` pairs.

    Args:
        *entries (tuple[str, str]): one or more `(svc_id, kind)` pairs.

    Returns:
        ServiceCatalogue: catalogue with the entries in insertion order.
    """
    _entries = {
        _id: ServiceCatalogueEntry(svc_id=_id, kind=_kind)
        for _id, _kind in entries
    }
    return ServiceCatalogue(name="test", source="", entries=_entries)


class TestExtractOpWeights:
    """`extract_op_weights` over a `_routs`-shaped matrix."""

    def test_three_ops(self) -> None:
        """*test_three_ops()* one normalised row per operation in `stage_routes`."""
        _nodes = ["TAS_{2}", "MAS_{1}", "MAS_{2}"]
        _routs = {
            "baseline": [
                [0.0, 0.4, 0.6],
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
            ],
        }
        _stage_routes = {
            "TAS_{2}": {
                "calls_kind": "medical_analysis",
                "operation": "analyseData",
            },
        }
        _ans = extract_op_weights(_routs, _nodes, _stage_routes)
        assert _ans == {"analyseData": {"MAS_{1}": 0.4, "MAS_{2}": 0.6}}

    def test_drops_diagonal(self) -> None:
        """*test_drops_diagonal()* the diagonal column is dropped as per-service epsilon."""
        _nodes = ["TAS_{2}", "MAS_{1}"]
        _routs = {
            "baseline": [
                [0.5, 1.0],
                [0.0, 0.0],
            ],
        }
        _stage_routes = {"TAS_{2}": {"operation": "analyseData"}}
        _ans = extract_op_weights(_routs, _nodes, _stage_routes)
        assert _ans == {"analyseData": {"MAS_{1}": 1.0}}

    def test_unknown_scenario(self) -> None:
        """*test_unknown_scenario()* raises `KeyError`."""
        with pytest.raises(KeyError):
            extract_op_weights({"baseline": []}, [], {}, scenario="nope")


class TestPickers:
    """The four strategy pickers + their factory."""

    def test_baseline_weighted(self) -> None:
        """*test_baseline_weighted()* over many draws, the heavier-weighted svc wins more often."""
        _cat = _catalogue(("AS_{1}", "alarm"), ("AS_{2}", "alarm"))
        _weights = {"triggerAlarm": {"AS_{1}": 0.9, "AS_{2}": 0.1}}
        _picker = FirstOfKindPicker(op_weights=_weights, rng=random.Random(42))
        _counts = {"AS_{1}": 0, "AS_{2}": 0}
        for _ in range(1000):
            _picked = _picker("alarm", "triggerAlarm", _cat)
            _counts[_picked[0].svc_id] += 1
        assert _counts["AS_{1}"] > 700
        assert _counts["AS_{2}"] < 300

    def test_baseline_fallback(self) -> None:
        """*test_baseline_fallback()* missing weights fall back to catalogue first-of-kind."""
        _cat = _catalogue(("AS_{1}", "alarm"), ("AS_{2}", "alarm"))
        _picker = FirstOfKindPicker(op_weights={})
        _ans = _picker("alarm", "missing_op", _cat)
        assert len(_ans) == 1
        assert _ans[0].svc_id == "AS_{1}"

    def test_s1_chain(self) -> None:
        """*test_s1_chain()* up to `max_attempts` distinct candidates without replacement."""
        _cat = _catalogue(
            ("AS_{1}", "alarm"),
            ("AS_{2}", "alarm"),
            ("AS_{3}", "alarm"),
        )
        _weights = {
            "triggerAlarm": {
                "AS_{1}": 0.33,
                "AS_{2}": 0.33,
                "AS_{3}": 0.34,
            },
        }
        _picker = RetryOnFailurePicker(
            op_weights=_weights,
            max_attempts=3,
            rng=random.Random(0),
        )
        _chain = _picker("alarm", "triggerAlarm", _cat)
        assert len(_chain) == 3
        _ids = [_e.svc_id for _e in _chain]
        assert len(set(_ids)) == 3

    def test_s2_picks_reliable(self) -> None:
        """*test_s2_picks_reliable()* picks the svc with the lowest observed failure rate."""
        _cat = _catalogue(("AS_{1}", "alarm"), ("AS_{2}", "alarm"))
        _picker = PreferReliablePicker(window_size=10)
        for _ in range(5):
            _picker.observe("AS_{1}", False)
            _picker.observe("AS_{2}", True)
        _ans = _picker("alarm", "triggerAlarm", _cat)
        assert len(_ans) == 1
        assert _ans[0].svc_id == "AS_{2}"

    def test_s2_unseen(self) -> None:
        """*test_s2_unseen()* a never-observed svc has failure_rate=0 and ties for best."""
        _cat = _catalogue(("AS_{1}", "alarm"), ("AS_{2}", "alarm"))
        _picker = PreferReliablePicker(window_size=10)
        _picker.observe("AS_{1}", False)
        assert _picker.failure_rate("AS_{2}") == 0.0
        _ans = _picker("alarm", "triggerAlarm", _cat)
        assert _ans[0].svc_id == "AS_{2}"

    def test_aggregate_ranked(self) -> None:
        """*test_aggregate_ranked()* returns reliability-ranked chain truncated to `max_attempts`."""
        _cat = _catalogue(
            ("AS_{1}", "alarm"),
            ("AS_{2}", "alarm"),
            ("AS_{3}", "alarm"),
        )
        _picker = RetryAndPreferReliablePicker(max_attempts=2, window_size=10)
        for _ in range(4):
            _picker.observe("AS_{1}", False)
            _picker.observe("AS_{2}", True)
            _picker.observe("AS_{3}", False)
        _chain = _picker("alarm", "triggerAlarm", _cat)
        assert len(_chain) == 2
        assert _chain[0].svc_id == "AS_{2}"

    def test_make_picker(self) -> None:
        """*test_make_picker()* returns the right concrete class per adp."""
        _weights = {"op": {"AS_{1}": 1.0}}
        _kwargs = {"op_weights": _weights, "max_attempts": 3, "window_size": 10}
        assert isinstance(make_picker("baseline", **_kwargs), FirstOfKindPicker)
        assert isinstance(make_picker("s1", **_kwargs), RetryOnFailurePicker)
        assert isinstance(make_picker("s2", **_kwargs), PreferReliablePicker)
        assert isinstance(make_picker("aggregate", **_kwargs), RetryAndPreferReliablePicker)

    def test_unknown_adp(self) -> None:
        """*test_unknown_adp()* unknown adp raises `KeyError`."""
        with pytest.raises(KeyError):
            picker_name_for("nope")

    def test_unknown_wire(self) -> None:
        """*test_unknown_wire()* unknown wire name raises `ValueError`."""
        with pytest.raises(ValueError):
            picker_from_wire("nope", op_weights={}, max_attempts=3, window_size=10)
