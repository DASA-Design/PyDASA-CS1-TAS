# -*- coding: utf-8 -*-
"""
Module registry.py
==================

Resolve service-name to HTTP URL using the layout declared in
`data/config/method/experiment.json::service_registry`. The registry
is built once at experiment startup and shared across the composite
services, the client simulator, and the launcher's health barrier.

Public API:
    - `ServiceRegistry(host, base_port, table)` maps names to URLs.
    - `ServiceRegistry.from_config(method_cfg)` builds one from the loaded method config.
    - `ServiceRegistry.resolve_base_url(name)` returns the fully-qualified base URL.
    - `ServiceRegistry.build_invoke_url(name)` returns the per-service invoke endpoint.
    - `ServiceRegistry.build_healthz_url(name)` returns the `/healthz` endpoint.
    - `ServiceRegistry.list_names()` / `filter_names_by_role(role)` enumerate the table.
"""
# native python modules
from __future__ import annotations

import re

# data types
from dataclasses import dataclass
from typing import Any, Dict, Iterable


# matches `TAS_{i}` keys; used to route into the six-in-one Option-B FastAPI app
_TAS_KEY_RE = re.compile(r"^TAS_\{(\d+)\}$")


@dataclass(frozen=True)
class RegistryEntry:
    """*RegistryEntry* one row of the registry: name, role, resolved port."""

    name: str

    role: str

    port: int


@dataclass(frozen=True)
class ServiceRegistry:
    """*ServiceRegistry* immutable service-name to URL resolver.

    Attributes:
        host (str): host address (usually `"127.0.0.1"`).
        base_port (int): first service port; each entry adds its `port_offset`.
        table (Dict[str, RegistryEntry]): keyed by service name (e.g. `TAS_{1}`, `MAS_{1}`); values are frozen `RegistryEntry` records.
    """

    host: str

    base_port: int

    table: Dict[str, RegistryEntry]

    @classmethod
    def from_config(cls,
                    method_cfg: Dict[str, Any],
                    *,
                    base_port_override: int = 0) -> "ServiceRegistry":
        """*from_config()* build a registry from a loaded `experiment.json`.

        Args:
            method_cfg (Dict[str, Any]): parsed method config.
            base_port_override (int): when non-zero, replaces `method_cfg["base_port"]`. Used for CI / parallel runs via env var.

        Returns:
            ServiceRegistry: populated registry.
        """
        _host = method_cfg.get("host", "127.0.0.1")
        _base = base_port_override if base_port_override > 0 else int(method_cfg["base_port"])
        _table: Dict[str, RegistryEntry] = {}
        for _name, _spec in method_cfg["service_registry"].items():
            _port = _base + int(_spec["port_offset"])
            _table[_name] = RegistryEntry(name=_name,
                                          role=_spec["role"],
                                          port=_port)
        return cls(host=_host, base_port=_base, table=_table)

    def resolve_base_url(self, name: str) -> str:
        """*resolve_base_url()* return the `http://host:port` base URL for `name`.

        Args:
            name (str): service name (e.g. `"TAS_{1}"`, `"MAS_{1}"`).

        Raises:
            KeyError: if `name` is not in the registry table.

        Returns:
            str: fully-qualified base URL, without a trailing path.
        """
        _e = self.table[name]
        return f"http://{self.host}:{_e.port}"

    def build_invoke_url(self, name: str) -> str:
        """*build_invoke_url()* return the per-service invoke endpoint URL.

        The TAS target system (`TAS_{i}`) is one deployable unit hosting
        six internal components on one port; each component is addressed
        by its numeric index in the URL path (`/TAS_<i>/invoke`).
        Third-party services keep a single `/invoke` route per port.

        Args:
            name (str): service name.

        Raises:
            KeyError: if `name` is not in the registry table.

        Returns:
            str: the `POST /invoke` URL for this service.
        """
        _m = _TAS_KEY_RE.match(name)
        if _m is not None:
            return f"{self.resolve_base_url(name)}/TAS_{_m.group(1)}/invoke"
        return f"{self.resolve_base_url(name)}/invoke"

    def build_healthz_url(self, name: str) -> str:
        """*build_healthz_url()* return the `/healthz` endpoint URL for `name`."""
        return f"{self.resolve_base_url(name)}/healthz"

    def list_names(self) -> Iterable[str]:
        """*list_names()* yield every service name in declaration order."""
        return self.table.keys()

    def filter_names_by_role(self, role: str) -> Iterable[str]:
        """*filter_names_by_role()* yield names whose entry role matches `role`.

        Args:
            role (str): role label such as `"atomic"`, `"composite_client"`, `"composite_medical"`, `"composite_alarm"`, `"composite_drug"`.

        Returns:
            Iterable[str]: lazy generator of matching service names.
        """
        return (_n for _n, _e in self.table.items() if _e.role == role)
