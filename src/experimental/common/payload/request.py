"""Typed request schema for client to service traffic.

Every request carries metadata (`req_id`, `kind`, `client_id`, timestamps), an explicit `inject_failure` flag for repeatable failure injection (see D3 of the plan), and a kB-scale `blob` payload that loads handler memory paths. Bytes are base64-encoded on the wire so the record JSON-serialises cleanly.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Literal

KIND_ALARM = "alarm"
KIND_MED_ANSYS = "medical_analysis"

FailureMechanism = Literal["timeout", "drop", "5xx"]


@dataclass(frozen=True)
class Request:
    """One client-to-service request.

    Attributes:
        req_id (str): unique id within a run (e.g. `u47-r0312`).
        kind (str): workflow entry point: `KIND_ALARM` (panic-button) or `KIND_MED_ANSYS`.
        client_id (str): synthetic-user identifier.
        submitted_ts (float): client-side timestamp at send (seconds, time.time()).
        inject_failure (FailureMechanism | None): failure mechanism to apply at the receiving service, or `None` for a normal success path.
        blob (bytes): kB-scale payload bytes (deterministic from a seed when one is provided to `make_blob`).
    """

    req_id: str
    kind: str
    client_id: str
    submitted_ts: float
    inject_failure: FailureMechanism | None
    blob: bytes

    def to_dict(self) -> dict[str, Any]:
        """Encode for JSON transport (`blob` becomes a base64 string).

        Returns:
            dict[str, Any]: JSON-friendly dict with `blob_b64` in place of raw bytes.
        """
        _payload: dict[str, Any] = {
            "req_id": self.req_id,
            "kind": self.kind,
            "client_id": self.client_id,
            "submitted_ts": self.submitted_ts,
            "inject_failure": self.inject_failure,
            "blob_b64": base64.b64encode(self.blob).decode("ascii"),
        }
        return _payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Request:
        """Decode from a JSON-derived dict.

        Args:
            payload (dict[str, Any]): dict produced by `to_dict()` (or matching shape).

        Returns:
            Request: reconstructed request with `blob` decoded back to bytes.
        """
        _req = cls(
            req_id=payload["req_id"],
            kind=payload["kind"],
            client_id=payload["client_id"],
            submitted_ts=payload["submitted_ts"],
            inject_failure=payload["inject_failure"],
            blob=base64.b64decode(payload["blob_b64"]),
        )
        return _req
