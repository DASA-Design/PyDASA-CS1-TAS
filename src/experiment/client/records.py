# -*- coding: utf-8 -*-
"""
Module client/records.py
========================

One client-side measurement per request: timing, status, success, plus three
derived failure-mode flags. Architecturally observable only; domain concepts
(cost) live elsewhere.
"""
# native python modules
from __future__ import annotations

# data types
from dataclasses import dataclass


@dataclass
class RequestRecord:
    """*RequestRecord* end-to-end measurement captured by the client for one outbound request.

    Attributes:
        req_id (str): UUID4 identifying this invocation.
        kind (str): request kind label (e.g. `"TAS_{2}"`).
        send_ts (float): perf-counter seconds when the client dispatched the request.
        recv_ts (float): perf-counter seconds when the response (or transport exception) was captured.
        status_code (int): HTTP status; `-1` means transport exception (timeout, connection reset, DNS failure, etc.).
        success (bool): body-level `success` flag; business-level outcome.
        size_bytes (int): declared payload size in bytes.
    """
    req_id: str
    kind: str
    send_ts: float = 0.0
    recv_ts: float = 0.0
    status_code: int = 0
    success: bool = False
    size_bytes: int = 0

    @property
    def response_time_s(self) -> float:
        """*response_time_s* end-to-end latency clamped at zero against clock skew.

        Returns:
            float: `recv_ts - send_ts` in seconds when ordered, else `0.0` (out-of-order timestamps mean an exception fired before the wire response landed).
        """
        _delta = self.recv_ts - self.send_ts
        _rt = max(0.0, _delta)
        return _rt

    @property
    def infra_failure(self) -> bool:
        """*infra_failure* infrastructure-level outcome flag fed to the stop guard.

        Returns:
            bool: True for transport errors (`status_code < 0`) and 5xx responses; False for 2xx, 3xx, 4xx, and `200 + success=False` (the latter is a business-level fault, not infra).
        """
        _is_transport_err = self.status_code < 0
        _is_5xx = self.status_code >= 500
        _flag = _is_transport_err or _is_5xx
        return _flag

    @property
    def business_failure(self) -> bool:
        """*business_failure* business-level outcome flag (the adaptation target; does NOT halt the ramp).

        Returns:
            bool: True iff the wire said `200 OK` but the response body declared `success=False`; False otherwise.
        """
        _is_ok_status = self.status_code == 200
        _is_biz_fail = not self.success
        _flag = _is_ok_status and _is_biz_fail
        return _flag
