"""AtomicService: leaf service node with K + c admission (Weyns & Calinescu 2015 Fig. 2).

A leaf that handles its own work. Adds the M/M/c/K admission gate so prototype runs reproduce the queueing model the analytic, stochastic, and dimensional methods reason about. Subclasses override `_handle`; the inherited `invoke_operation` runs the gate around the call so admission is never bypassed.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from typing import Any

from src.experimental.prototype.target.service.abstract import AbstractService


class AdmissionGate:
    """K + c admission gate.

    `K` caps in-flight requests (queue + service); `c` caps parallel workers. Either set to None disables that limit.

    Attributes:
        K (int | None): in-flight cap; None disables.
        c (int | None): parallel-worker cap; None disables.
        c_sem (asyncio.Semaphore | None): worker semaphore; None when c is None.
    """

    def __init__(self, *, K: int | None, c: int | None) -> None:
        """Configure the gate.

        Args:
            K (int | None): in-flight cap.
            c (int | None): parallel-worker cap.
        """
        self.K = K
        self.c = c
        self._lock = asyncio.Lock()
        self._in_flight = 0
        if c is None:
            self.c_sem: asyncio.Semaphore | None = None
        else:
            self.c_sem = asyncio.Semaphore(c)

    async def acquire(self) -> tuple[bool, int]:
        """Try to admit one request.

        Returns:
            tuple[bool, int]: `(admitted, in_flight_count)`. The count is post-admit when accepted, otherwise the count at rejection.
        """
        async with self._lock:
            if self.K is not None and self._in_flight >= self.K:
                _ans = (False, self._in_flight)
            else:
                self._in_flight += 1
                _ans = (True, self._in_flight)
        return _ans

    async def release(self) -> None:
        """Release one admitted request."""
        async with self._lock:
            self._in_flight -= 1


class AtomicService(AbstractService):
    """Leaf service with K + c admission.

    Subclasses implement `_handle(payload)`. The inherited `invoke_operation` runs admission, calls `_handle`, stamps `c_used_at_start` on the response, and releases.

    Attributes:
        service_name (str): catalogue identifier (inherited).
        k (int | None): in-flight cap.
        c (int | None): parallel-worker cap.
    """

    def __init__(self,
                 *,
                 service_name: str,
                 k: int | None = None,
                 c: int | None = None) -> None:
        """Configure the atomic service.

        Args:
            service_name (str): catalogue identifier.
            k (int | None, optional): in-flight cap. Defaults to None (no limit).
            c (int | None, optional): parallel-worker cap. Defaults to None (no limit).
        """
        super().__init__(service_name=service_name)
        self.k = k
        self.c = c
        self._gate = AdmissionGate(K=k, c=c)

    async def invoke_operation(self,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Run admission then `_handle`; return `(body, status_code)`.

        Rejected admission returns `({"error": "K_full", ...}, 503)`. Admitted requests pass through the c-semaphore (when set) into `_handle`, and the response carries `c_used_at_start` so downstream analysis can correlate latency to load.

        Args:
            payload (dict[str, Any]): parsed request body.

        Returns:
            tuple[dict[str, Any], int]: response body + HTTP status code.
        """
        _admitted, _c_used = await self._gate.acquire()
        if not _admitted:
            _rejected: dict[str, Any] = {
                "error": "K_full",
                "service_name": self.service_name,
                "K": self.k,
                "in_flight": _c_used,
            }
            return _rejected, 503
        try:
            if self._gate.c_sem is not None:
                async with self._gate.c_sem:
                    _body = await self._handle(payload)
            else:
                _body = await self._handle(payload)
            _body["c_used_at_start"] = _c_used
            return _body, 200
        finally:
            await self._gate.release()

    @abstractmethod
    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Subclass-supplied request handler. Runs after admission.

        Args:
            payload (dict[str, Any]): parsed request body.

        Returns:
            dict[str, Any]: response body.
        """
        ...
