"""Tests for `src.experimental.prototype.target.service.composite`.

**TestCompositeService**:

- `test_delegates`: `invoke_operation(payload)` calls the engine's `execute` and returns its `(body, status)`.
- `test_alias`: the published-Fig-2 alias yields the same answer as `invoke_operation`.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.prototype.target.service.composite import CompositeService


class _StubEngine:
    """Stand-in `WorkflowEngine` that returns a scripted `(body, status)` from `execute`."""

    def __init__(self, body: dict[str, Any], status: int) -> None:
        self._body = body
        self._status = status
        self.calls: list[dict[str, Any]] = []

    async def execute(self,
                      payload: dict[str, Any],
                      client: Any) -> tuple[dict[str, Any], int]:
        del client
        self.calls.append(dict(payload))
        return dict(self._body), self._status


class TestCompositeService:
    """`CompositeService` glue between Fig.2 surface and the workflow engine."""

    @pytest.mark.asyncio
    async def test_delegates(self) -> None:
        """*test_delegates()* `invoke_operation` returns whatever `engine.execute` returns and forwards the payload unchanged."""
        _engine = _StubEngine(body={"ok": True}, status=200)
        _composite = CompositeService(service_name="TAS",
                                      workflow=_engine,  # type: ignore[arg-type]
                                      client=None)  # type: ignore[arg-type]
        _body, _status = await _composite.invoke_operation({"kind": "alarm"})
        assert _status == 200
        assert _body == {"ok": True}
        assert _engine.calls == [{"kind": "alarm"}]

    @pytest.mark.asyncio
    async def test_alias(self) -> None:
        """*test_alias()* `invoke_composite_service` is a verbatim alias of `invoke_operation`."""
        _engine = _StubEngine(body={"ok": True}, status=200)
        _composite = CompositeService(service_name="TAS",
                                      workflow=_engine,  # type: ignore[arg-type]
                                      client=None)  # type: ignore[arg-type]
        _ans = await _composite.invoke_composite_service({"kind": "alarm"})
        assert _ans == ({"ok": True}, 200)
