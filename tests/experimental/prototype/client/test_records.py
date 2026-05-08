"""Tests for `src.experimental.prototype.client.records`.

**TestRequestRecord**:

- `test_to_dict_keys`: confirms `to_dict()` emits every schema field so the JSONL writer sees a stable shape.
- `test_hops_copy_isolated`: confirms mutating the returned `hops` list does not bleed back into the record, so callers cannot corrupt the in-memory state by accident.
- `test_default_hops`: confirms a freshly built record has an empty `hops` list, since hops are populated later by the workflow engine and probes.
"""

from __future__ import annotations

from tests.utils.exp.factories import make_record


class TestRequestRecord:
    """One log entry per end-to-end request, matching the JSONL flow-record schema."""

    def test_to_dict_keys(self) -> None:
        """The dict produced by `to_dict()` has exactly the field set the JSONL writer expects, so a record is serialisable without further transformation."""
        _record = make_record(0)
        _payload = _record.to_dict()
        assert set(_payload.keys()) == {
            "req_id",
            "kind",
            "client_id",
            "submitted_ts",
            "completed_ts",
            "total_latency_s",
            "outcome",
            "status_code",
            "hops",
        }

    def test_hops_copy_isolated(self) -> None:
        """Mutating the `hops` list returned from `to_dict()` leaves the record untouched, so external callers cannot corrupt the in-memory state."""
        _record = make_record(0)
        _record.hops.append({"service": "S1"})
        _payload = _record.to_dict()
        _payload["hops"].append({"service": "MUTATED"})
        assert len(_record.hops) == 1
        assert _record.hops[0]["service"] == "S1"

    def test_default_hops(self) -> None:
        """A freshly built record has an empty `hops` list because the workflow engine and probes populate hops as the request traverses the target + controller layers; until they are wired, hops remain empty."""
        _record = make_record(0)
        assert _record.hops == []
