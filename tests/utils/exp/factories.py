"""Synthetic-record + synthetic-request factories for `src.experimental` tests.

`make_record(idx, ...)` builds one `RequestRecord` at submission timestamp `idx` (seconds), used by aggregator + guard tests that need to time-place records on a synthetic timeline. Default `outcome="success"` + `latency=0.01` keep call sites short; per-test overrides cover the failure paths.
"""

from __future__ import annotations

from src.experimental.prototype.client.records import Outcome, RequestRecord


def make_record(idx: int,
                outcome: Outcome = "success",
                status_code: int | None = None,
                latency: float = 0.01) -> RequestRecord:
    """Construct one synthetic record at submission timestamp `idx` (seconds).

    Args:
        idx (int): synthetic submission timestamp; one second per index step.
        outcome (Outcome, optional): outcome label. Defaults to `"success"`.
        status_code (int | None, optional): HTTP status code. Defaults to None, which maps to 200 on success and 500 on every failure outcome.
        latency (float, optional): total latency in seconds. Defaults to 0.01.

    Returns:
        RequestRecord: synthetic record with monotonic timestamps derived from `idx`.
    """
    if status_code is None:
        if outcome == "success":
            _status = 200
        else:
            _status = 500
    else:
        _status = status_code
    _record = RequestRecord(req_id=f"r{idx}",
                            kind="medical_analysis",
                            client_id="user-1",
                            submitted_ts=float(idx),
                            completed_ts=float(idx) + latency,
                            total_latency_s=latency,
                            outcome=outcome,
                            status_code=_status)
    return _record
