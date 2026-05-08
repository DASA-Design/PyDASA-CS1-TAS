"""`RequestRecord` dataclass: one log entry per end-to-end request.

The schema matches the JSONL flow-record format pinned in plan §D6: every field the JSONL writer (`common/io/jsonl.JsonlWriter`) serialises is present, so target + controller wiring can populate `hops` without a schema migration. The `hops` list is empty until the workflow engine and probes are wired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Outcome = Literal["success", "timeout", "drop", "5xx"]


@dataclass
class RequestRecord:
    """One end-to-end request log entry, written one-per-line to the flow JSONL.

    Attributes:
        req_id (str): unique request identifier within a run; a UUID4 hex string minted by `Sender.build_request`.
        kind (str): workflow entry point (e.g. `"alarm"` or `"medical_analysis"`).
        client_id (str): synthetic-user identifier.
        submitted_ts (float): client-side timestamp at send (seconds, `time.time()`).
        completed_ts (float): client-side timestamp when the response landed; equals `submitted_ts + total_latency_s` modulo clock skew.
        total_latency_s (float): end-to-end latency in seconds.
        outcome (Outcome): terminal request state: `"success"`, `"timeout"`, `"drop"`, or `"5xx"`. The `rule_rejection` mechanism (HTTP 200 + `body.success=False`) is excluded per plan §D3 because its semantics fit S4 (functional change), out of scope per case-study `ADR.02`.
        status_code (int): HTTP status code of the final response, or 0 on transport-level failure (timeout / drop).
        hops (list[dict[str, Any]]): per-service hop log; populated by the workflow engine and probes. Each hop carries `service`, `recv_ts`, `start_ts`, `end_ts`, `status`, `c_used_at_start`.
    """

    req_id: str
    kind: str
    client_id: str
    submitted_ts: float
    completed_ts: float
    total_latency_s: float
    outcome: Outcome
    status_code: int
    hops: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Encode the record as a JSON-friendly dict suitable for the JSONL writer.

        Returns:
            dict[str, Any]: dict with every field; `hops` is the nested list, copied so callers cannot mutate the record by reference.
        """
        _payload: dict[str, Any] = {
            "req_id": self.req_id,
            "kind": self.kind,
            "client_id": self.client_id,
            "submitted_ts": self.submitted_ts,
            "completed_ts": self.completed_ts,
            "total_latency_s": self.total_latency_s,
            "outcome": self.outcome,
            "status_code": self.status_code,
            "hops": [dict(_hop) for _hop in self.hops],
        }
        return _payload
