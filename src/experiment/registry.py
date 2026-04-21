# -*- coding: utf-8 -*-
"""
Module registry.py
==================

Resolves service-name -> HTTP URL using the layout declared in `data/config/method/experiment json::service_registry`. The registry is built once at experiment startup and shared across the composite services, the client simulator, and the launcher's health barrier.

    - `ServiceRegistry(host, base_port, table)` maps names to URLs.
    - `ServiceRegistry.from_config(method_cfg)` builds one from the loaded method config.
    - `ServiceRegistry.url(name)` returns the fully-qualified base URL for a service.
"""
# native python modules
from __future__ import annotations

# data types
from dataclasses import dataclass
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class RegistryEntry:
    """*RegistryEntry* one row of the registry: name, role, resolved port."""

    name: str
    role: str
    port: int


@dataclass(frozen=True)
class ServiceRegistry:
    """*ServiceRegistry* immutable name -> URL resolver.

    Attributes:
        host (str): host address (usually `"127.0.0.1"`).
        base_port (int): first service port; each entry adds its `port_offset`.
        table (Dict[str, RegistryEntry]): name -> RegistryEntry.
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

    def url(self, name: str) -> str:
        """*url()* fully-qualified base URL for a service (`http://host:port`)."""
        _e = self.table[name]
        return f"http://{self.host}:{_e.port}"

    def invoke_url(self, name: str) -> str:
        """*invoke_url()* the per-service invoke endpoint URL.

        The TAS target system (`TAS_{i}`) is one deployable unit hosting
        six internal components on one port; each component is addressed
        by its numeric index in the URL path (`/TAS_<i>/invoke`).
        Third-party services keep a single `/invoke` route per port.
        """
        import re as _re
        _m = _re.match(r"^TAS_\{(\d+)\}$", name)
        if _m is not None:
            return f"{self.url(name)}/TAS_{_m.group(1)}/invoke"
        return f"{self.url(name)}/invoke"

    def healthz_url(self, name: str) -> str:
        """*healthz_url()* the `/healthz` endpoint URL for a service."""
        return f"{self.url(name)}/healthz"

    def names(self) -> Iterable[str]:
        """*names()* all service names in declaration order."""
        return self.table.keys()

    def names_by_role(self, role: str) -> Iterable[str]:
        """*names_by_role()* filter names by role (`"atomic"` or `"composite"`)."""
        return (_n for _n, _e in self.table.items() if _e.role == role)
