"""ServiceRegistry, the global service address book (Weyns & Calinescu 2015 Fig. 2).

- **SOURCE**: Weyns & Calinescu 2015, Fig. 2; reproduces ServiceRegistry.
- **FUNCTIONAL OBJECTIVE**: central lookup table that services register with at startup so the composite (and any other client) can resolve atomic endpoints by name. The registry is the single source of truth for "which services exist"; per-client `ServiceCache` instances mirror it on demand.
- **DEVIATION FROM SOURCE**: Java `Map<String, ServiceDescription>` becomes Python `dict[str, ServiceDescription]`; methods are snake_case per Python convention; class name preserved verbatim. The `serviceList` field is exposed as the `service_lt` property which returns a copied dict, so callers cannot mutate the registry by reference. Method parameters use `svc_name` (project acronym-substitution `service` → `svc`) rather than the paper's `serviceName`.
"""

from __future__ import annotations

from src.experimental.common.registry.description import ServiceDescription


class UnknownServiceError(KeyError):
    """Raised when `lookup_service` is called for an unregistered name."""


class ServiceRegistry:
    """Global address book of `ServiceDescription` records.

    Lifecycle:
        1. Services call `register_service(desc)` at startup.
        2. Clients call `lookup_service(svc_name)` (typically through a `ServiceCache` proxy) to get the endpoint.
        3. Effectors call `unregister_service(svc_name)` to remove a failed entry.

    Attributes:
        _entries (dict[str, ServiceDescription]): private storage keyed by `desc.name`. Exposed read-only via the `service_lt` property (which returns a snapshot copy).
    """

    def __init__(self) -> None:
        """Construct an empty registry."""
        self._entries: dict[str, ServiceDescription] = {}

    @property
    def service_lt(self) -> dict[str, ServiceDescription]:
        """Return a snapshot copy of the registered descriptions.

        Returns:
            dict[str, ServiceDescription]: a new dict; mutating it does not affect the registry.
        """
        _snap = dict(self._entries)
        return _snap

    def register_service(self, desc: ServiceDescription) -> None:
        """Add or replace the entry for `desc.name`.

        Args:
            desc (ServiceDescription): service description to store.
        """
        self._entries[desc.name] = desc

    def unregister_service(self, svc_name: str) -> None:
        """Remove the entry for `svc_name` if present (no-op otherwise).

        Args:
            svc_name (str): name to remove.
        """
        self._entries.pop(svc_name, None)

    def lookup_service(self, svc_name: str) -> ServiceDescription:
        """Return the description for `svc_name`.

        Args:
            svc_name (str): registered name.

        Returns:
            ServiceDescription: the stored description.

        Raises:
            UnknownServiceError: if no entry is registered for that name.
        """
        try:
            _desc = self._entries[svc_name]
        except KeyError as _err:
            _msg = f"no service registered with name {svc_name!r}"
            raise UnknownServiceError(_msg) from _err
        return _desc
