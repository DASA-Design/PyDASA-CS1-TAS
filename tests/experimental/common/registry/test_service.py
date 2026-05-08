"""Tests for `src.experimental.common.registry.service`.

**TestServiceRegistry**:

- `test_register_then_lookup`: confirms a registered description is retrievable by name so the registry actually stores what it claims to.
- `test_lookup_unknown_raises`: confirms an unregistered name raises `UnknownServiceError` with a clear message so callers see a structured failure rather than a bare `KeyError`.
- `test_unregister`: confirms removed entries are no longer retrievable and a second remove of an absent name is a safe no-op so effectors can call `unregister_service` defensively.
- `test_service_lt_is_snapshot`: confirms the `service_lt` property returns a copied dict so callers cannot mutate the registry by reference.
- `test_register_overwrites`: confirms registering the same name replaces the prior description so service-endpoint moves take effect on next lookup.
"""

from __future__ import annotations

from typing import Callable

import pytest

from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import (
    ServiceRegistry,
    UnknownServiceError,
)


class TestServiceRegistry:
    """`ServiceRegistry` per Weyns 2015 Fig. 2."""

    def test_register_then_lookup(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """Registering a description and looking it up by name returns the same object, demonstrating the registry stores entries keyed by `desc.name` as Fig. 2 specifies.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _d = make_desc("AlarmService_1")
        _reg.register_service(_d)
        assert _reg.lookup_service("AlarmService_1") == _d

    def test_lookup_unknown_raises(self) -> None:
        """Looking up a name that was never registered raises `UnknownServiceError` (the project-specific subclass of `KeyError`) with the missing name in the message, so callers can branch on a structured exception."""
        _reg = ServiceRegistry()
        with pytest.raises(UnknownServiceError, match="no service registered"):
            _reg.lookup_service("nope")

    def test_unregister(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """After `unregister_service`, lookup raises; a second remove of an already-absent name is a no-op (no exception), so effectors can call `unregister_service` defensively without first checking for membership.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _reg.register_service(make_desc("MAS_1"))
        _reg.unregister_service("MAS_1")
        with pytest.raises(UnknownServiceError):
            _reg.lookup_service("MAS_1")
        _reg.unregister_service("MAS_1")

    def test_service_lt_is_snapshot(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """The dict returned by the `service_lt` property is a copy: clearing it leaves the registry's underlying entries intact, so callers cannot mutate registry state by reference.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _reg.register_service(make_desc("A"))
        _snap = _reg.service_lt
        _snap.clear()
        assert _reg.lookup_service("A").name == "A"

    def test_register_overwrites(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """Registering twice under the same name replaces the prior description rather than coexisting, so a service that moves endpoints (e.g., port re-bind) becomes immediately resolvable at the new endpoint on the next lookup.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _reg.register_service(make_desc("X", port=8001))
        _reg.register_service(make_desc("X", port=8002))
        assert _reg.lookup_service("X").endpoint.endswith(":8002")
