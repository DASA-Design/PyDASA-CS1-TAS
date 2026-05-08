"""Tests for `src.experimental.common.registry.cache`.

**TestServiceCache**:

- `test_initial_snapshot`: confirms the cache mirrors registry contents at construction so freshly-built clients see whatever services are registered at the time.
- `test_refresh_picks_up_new_entries`: confirms `refresh()` sees newly registered services so a cache stale after a registration can recover by calling `refresh()`.
- `test_refresh_drops_unregistered`: confirms `refresh()` removes entries that are gone from the registry so an effector's `unregister_service` actually propagates to clients.
- `test_lookup_returns_cached_desc`: confirms a known name returns the cached description so the happy lookup path serves from local state without going to the registry.
- `test_lookup_unknown_raises`: confirms an unknown name raises `UnknownServiceError` with a refresh-and-retry hint so a client can decide whether to refresh and try again.
"""

from __future__ import annotations

from typing import Callable

import pytest

from src.experimental.common.registry.cache import ServiceCache
from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import (
    ServiceRegistry,
    UnknownServiceError,
)


class TestServiceCache:
    """`ServiceCache`: per-client snapshot of `ServiceRegistry`."""

    def test_initial_snapshot(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """Constructing a `ServiceCache` from a populated `ServiceRegistry` immediately mirrors its entries, so a freshly-built client can resolve services without first calling `refresh()`.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest that builds named `ServiceDescription` instances.
        """
        _reg = ServiceRegistry()
        _reg.register_service(make_desc("A"))
        _cache = ServiceCache(_reg)
        assert "A" in _cache.svc_descriptions

    def test_refresh_picks_up_new_entries(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """A service registered after the cache was built is invisible until `refresh()` is called, then becomes visible: this is the contract that lets clients deliberately stay on a stale snapshot until they choose to refresh.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _cache = ServiceCache(_reg)
        _reg.register_service(make_desc("B"))
        assert "B" not in _cache.svc_descriptions
        _cache.refresh()
        assert "B" in _cache.svc_descriptions

    def test_refresh_drops_unregistered(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """An entry the registry no longer holds is gone from the cache after `refresh()`, so an effector that calls `unregister_service` on a failed service ultimately propagates the removal to every client that refreshes.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _reg.register_service(make_desc("C"))
        _cache = ServiceCache(_reg)
        _reg.unregister_service("C")
        _cache.refresh()
        assert "C" not in _cache.svc_descriptions

    def test_lookup_returns_cached_desc(
        self,
        make_desc: Callable[..., ServiceDescription]
    ) -> None:
        """A `lookup` for a name present in the cache returns the cached description, demonstrating the happy path serves from local state and does not consult the registry on every call.

        Args:
            make_desc (Callable[..., ServiceDescription]): factory fixture from conftest.
        """
        _reg = ServiceRegistry()
        _d = make_desc("D")
        _reg.register_service(_d)
        _cache = ServiceCache(_reg)
        assert _cache.lookup("D") == _d

    def test_lookup_unknown_raises(self) -> None:
        """A `lookup` for a name absent from the cache raises `UnknownServiceError` with a `refresh()-and-retry` hint, so the caller can branch on whether to retry after a refresh or surface the failure to its own caller."""
        _reg = ServiceRegistry()
        _cache = ServiceCache(_reg)
        with pytest.raises(UnknownServiceError, match="not in cache"):
            _cache.lookup("nope")
