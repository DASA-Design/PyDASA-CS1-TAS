"""Tests for `src.experimental.prototype.target.service.atomic`.

Logic-only checks: K + c admission, `c_used_at_start` stamp, abstract `_handle` enforcement.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.experimental.prototype.target.service.atomic import AtomicService


class _Echo(AtomicService):
    """Trivial atomic service: bounces the payload back as the response body."""

    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"echoed": payload}


class _Blocking(AtomicService):
    """Atomic service whose `_handle` waits on an external event so tests can pin in-flight requests in place."""

    def __init__(self,
                 *,
                 service_name: str,
                 k: int | None,
                 c: int | None,
                 admitted: list[asyncio.Event],
                 hold: asyncio.Event) -> None:
        """Wire in synchronisation primitives the test owns."""
        super().__init__(service_name=service_name, k=k, c=c)
        self._admitted = admitted
        self._hold = hold

    async def _handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Signal admission, wait until the test releases, then bounce the payload."""
        _idx = payload["idx"]
        self._admitted[_idx].set()
        await self._hold.wait()
        return {"echoed": payload}


class TestAtomicService:
    """K + c admission + handler dispatch."""

    def test_no_limit_admits_all(self) -> None:
        """K=None and c=None admit every request and return 200 with the handler's body."""
        async def _exercise() -> tuple[dict[str, Any], int]:
            _svc = _Echo(service_name="echo")
            return await _svc.invoke_operation({"x": 1})
        _body, _status = asyncio.run(_exercise())
        assert _status == 200
        assert _body["echoed"] == {"x": 1}
        assert _body["c_used_at_start"] == 1

    def test_k_full_returns_503(self) -> None:
        """When in-flight reaches K, the next request is rejected with 503 and the documented K_full body."""
        async def _exercise() -> tuple[dict[str, Any], int]:
            _admitted = [asyncio.Event(), asyncio.Event()]
            _hold = asyncio.Event()
            _svc = _Blocking(service_name="block",
                             k=2,
                             c=None,
                             admitted=_admitted,
                             hold=_hold)
            _t1 = asyncio.create_task(_svc.invoke_operation({"idx": 0}))
            _t2 = asyncio.create_task(_svc.invoke_operation({"idx": 1}))
            await _admitted[0].wait()
            await _admitted[1].wait()
            # Two in-flight; a third request must be rejected.
            _body, _status = await _svc.invoke_operation({"idx": 2})
            _hold.set()
            await asyncio.gather(_t1, _t2)
            return _body, _status
        _body, _status = asyncio.run(_exercise())
        assert _status == 503
        assert _body["error"] == "K_full"
        assert _body["service_name"] == "block"
        assert _body["K"] == 2
        assert _body["in_flight"] == 2

    def test_c_used_at_start_stamped(self) -> None:
        """`c_used_at_start` records the in-flight count at admission so downstream queueing analysis can correlate."""
        async def _exercise() -> dict[str, Any]:
            _svc = _Echo(service_name="echo")
            _body, _ = await _svc.invoke_operation({"x": 0})
            return _body
        _body = asyncio.run(_exercise())
        assert _body["c_used_at_start"] == 1

    def test_handle_is_abstract(self) -> None:
        """`AtomicService` cannot be instantiated directly; subclasses must supply `_handle`."""
        with pytest.raises(TypeError):
            AtomicService(service_name="x")  # type: ignore[abstract]
