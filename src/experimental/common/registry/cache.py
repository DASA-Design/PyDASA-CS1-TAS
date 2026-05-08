"""ServiceCache, a per-client local copy of the registry (Weyns & Calinescu 2015 Fig. 2).

- **SOURCE**: Weyns & Calinescu 2015, Fig. 2; reproduces ServiceCache.
- **FUNCTIONAL OBJECTIVE**: per-client snapshot of `ServiceRegistry` state so clients invoke services without going to the registry on every call. Refreshed on demand (e.g., after an effector removes a failed service) via `refresh()`.
- **DEVIATION FROM SOURCE**: Java `Map<String, ServiceDescription> serviceDescriptions` becomes Python `dict[str, ServiceDescription]` named `svc_descriptions` (per project acronym-substitution); `refresh()` returns `None` and re-snapshots the registry rather than returning the new map. Lives in `common/` for the same reason as `ServiceRegistry`.
"""

from __future__ import annotations

from src.experimental.common.registry.description import ServiceDescription
from src.experimental.common.registry.service import (
    ServiceRegistry,
    UnknownServiceError,
)


class ServiceCache:
    """Per-client snapshot of a `ServiceRegistry`.

    Attributes:
        _registry (ServiceRegistry): source registry the cache mirrors.
        svc_descriptions (dict[str, ServiceDescription]): dict mapping `svc_name` to `ServiceDescription`, populated at construction and refreshed via `refresh()`.
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        """Snapshot the registry into the cache.

        Args:
            registry (ServiceRegistry): source registry to snapshot from.
        """
        self._registry = registry
        self.svc_descriptions: dict[str, ServiceDescription] = {}
        self.refresh()

    def refresh(self) -> None:
        """Re-snapshot the registry into `svc_descriptions`.

        Drops any local entries that no longer exist in the registry; picks up any new entries.
        """
        self.svc_descriptions = self._registry.service_lt

    def lookup(self, svc_name: str) -> ServiceDescription:
        """Return the cached description for `svc_name`.

        Args:
            svc_name (str): name to resolve.

        Returns:
            ServiceDescription: the cached description.

        Raises:
            UnknownServiceError: if the name is not in the cache. Caller may `refresh()` and retry.
        """
        try:
            _desc = self.svc_descriptions[svc_name]
        except KeyError as _err:
            _msg = f"service {svc_name!r} not in cache; call refresh() and retry"
            raise UnknownServiceError(_msg) from _err
        return _desc
