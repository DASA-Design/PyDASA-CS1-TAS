"""Tests for `src.experimental.prototype.target.service.abstract`.

Logic-only checks: identity, lifecycle defaults, abstract enforcement.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.prototype.target.service.abstract import AbstractService


class _NoOpService(AbstractService):
    """Smallest concrete subclass; returns a fixed body."""

    async def invoke_operation(self,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        del payload
        return {"ok": True}, 200


class TestAbstractService:
    """Root of the published service-class hierarchy."""

    def test_service_name_set(self) -> None:
        """The constructor records `service_name` as a public attribute matching the catalogue identifier."""
        _svc = _NoOpService(service_name="test")
        assert _svc.service_name == "test"

    def test_lifecycle_defaults_noop(self) -> None:
        """`start_service` and `stop_service` are no-ops by default; subclasses override only when warm-up / tear-down is needed."""
        _svc = _NoOpService(service_name="test")
        # Should not raise.
        _svc.start_service()
        _svc.stop_service()

    def test_invoke_operation_is_abstract(self) -> None:
        """`AbstractService` cannot be instantiated directly; subclasses must supply `invoke_operation`."""
        with pytest.raises(TypeError):
            AbstractService(service_name="x")  # type: ignore[abstract]
