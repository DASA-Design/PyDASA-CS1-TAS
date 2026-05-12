"""ServiceDescription, the service-metadata record (Weyns & Calinescu 2015 Fig. 2).

- **SOURCE**: Weyns & Calinescu 2015, Fig. 2; reproduces ServiceDescription.
- **FUNCTIONAL OBJECTIVE**: carry the metadata a ServiceClient needs to invoke a service: identifier, endpoint URL, supported operations, and arbitrary QoS hints (`custom_props`). Held by `ServiceRegistry`; copied into each client's `ServiceCache` on refresh.
- **DEVIATION FROM SOURCE**: Java getter/setter pairs become Python attributes on a frozen dataclass; field names are shortened since the enclosing class already declares the domain (`ServiceDescription.service_name` is redundant, `ServiceDescription.name` is enough). `id` becomes `_id` to avoid clashing with Python's builtin `id()`. `customProperties: Map<String,Object>` becomes `custom_props: dict[str, Any]`; `operationList` becomes `operations: tuple[str, ...]` (per the project's acronym-substitution rule). Lives in `common/` rather than `target/` so `ServiceRegistry` and `ServiceCache` (also in `common/`) can reference it without forcing a managed-to-managing dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ServiceDescription:
    """Metadata for one service entry in the registry.

    A service may be served by one or more workers behind separate URLs (one worker per uvicorn / waitress process). `endpoint` is the canonical single URL (kept for backwards compatibility); `urls` is the parallel tuple used when `workers > 1`. The `iter_urls` helper returns the effective tuple regardless of which field is populated.

    Attributes:
        _id (str): unique service identifier (e.g. `"AlarmService_1"`); leading underscore avoids the builtin `id()` shadow.
        name (str): human-readable service name (matches the catalogue label). Used as the `ServiceRegistry` key.
        endpoint (str): full base URL of the first worker (e.g. `"http://127.0.0.1:8002"`). When `workers > 1`, this is `urls[0]`.
        urls (tuple[str, ...]): one URL per worker process. Empty tuple defaults to `(endpoint,)` so legacy single-URL callers stay correct.
        operations (tuple[str, ...]): tuple of operation names this service supports (e.g. `("triggerAlarm", "sendAlarm")`).
        custom_props (dict[str, Any]): free-form QoS hints (failure rate, response time, cost from the catalogue).
    """

    _id: str
    name: str
    endpoint: str
    operations: tuple[str, ...] = ()
    custom_props: dict[str, Any] = field(default_factory=dict)
    urls: tuple[str, ...] = ()

    def iter_urls(self) -> tuple[str, ...]:
        """Return the effective worker URLs.

        Returns `urls` when populated; otherwise falls back to `(endpoint,)` so single-URL callers keep round-tripping. Used by `ServiceClient` to pick which worker to dispatch to.
        """
        if self.urls:
            return self.urls
        return (self.endpoint,)
