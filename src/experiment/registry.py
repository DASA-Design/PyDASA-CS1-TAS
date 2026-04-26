# -*- coding: utf-8 -*-
"""
Module registry.py
==================

Resolve service-name to HTTP URL using the layout declared in `data/config/method/experiment.json::service_registry`. The registry is built once at experiment startup and shared across the composite services, the client simulator, and the launcher's health barrier. Per-deployment host resolution (`local` / `loopback_aliased` / `remote`) lives in `_pick_host`; see `notes/distribute.md` §3 for the rule.

Public API:
    - `SvcRegistry(host, base_port, table, host_overrides)` maps names to URLs.
    - `SvcRegistry.from_config(method_cfg)` builds one from the loaded method config.
    - `SvcRegistry.host_for(name)` returns the resolved host address.
    - `SvcRegistry.resolve_base_url(name)` returns the fully-qualified base URL.
    - `SvcRegistry.build_invoke_url(name)` returns the per-service invoke endpoint.
    - `SvcRegistry.build_healthz_url(name)` returns the `/healthz` endpoint.
    - `SvcRegistry.list_names()` / `filter_names_role(role)` enumerate the table.
"""
# native python modules
from __future__ import annotations

import re

# data types
from dataclasses import dataclass, field
from typing import Any, Dict, List


# matches `TAS_{i}` keys; used to route into the six-in-one Option-B FastAPI app
_TAS_KEY_RE = re.compile(r"^TAS_\{(\d+)\}$")

# role labels keyed in the `hosts.<bucket>` map of method_cfg
_CLIENT_ROLE = "composite_client"
_COMPOSITE_PREFIX = "composite_"
_ATOMIC_ROLE = "atomic"


@dataclass(frozen=True)
class RegistryEntry:
    """*RegistryEntry* one row of the registry; carries the service name, role label, and resolved port."""

    # service name (e.g. `TAS_{1}`, `MAS_{1}`)
    name: str
    # role label such as `"atomic"`, `"composite_client"`, etc. Used for filtering the registry table by workflow stage.
    role: str
    # resolved 16-bit port number (base_port + port_offset from config)
    port: int


@dataclass(frozen=True)
class SvcRegistry:
    """*SvcRegistry* immutable service-name to URL resolver.

    Attributes:
        host (str): default host address (`"127.0.0.1"` in `local` mode).
        base_port (int): first service port; each entry adds its `port_offset`.
        table (Dict[str, RegistryEntry]): keyed by service name (e.g. `TAS_{1}`, `MAS_{1}`); values are frozen `RegistryEntry` records.
        host_overrides (Dict[str, str]): per-service-name host override populated by `from_config`. In `local` mode, every entry maps to `host`; in `loopback_aliased` and `remote` modes, entries map to per-bucket hosts from `method_cfg.hosts`.
    """

    # default host address used when host_overrides has no entry for a service
    host: str

    # base port; each entry's resolved port is `base_port + port_offset`
    base_port: int

    # mapping of service name to `RegistryEntry` record
    table: Dict[str, RegistryEntry]

    # per-service host override; populated by `from_config` per deployment mode
    host_overrides: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_config(cls,
                    method_cfg: Dict[str, Any],
                    *,
                    base_port_override: int = 0) -> "SvcRegistry":
        """*from_config()* build a registry from a loaded `experiment.json`.

        Delegates to `_pick_host` once per registry entry to populate `host_overrides`; see that method for the per-deployment resolution rule.

        Args:
            method_cfg (Dict[str, Any]): parsed method config.
            base_port_override (int): when non-zero, replaces `method_cfg["base_port"]`. Used for CI / parallel runs via env var.

        Returns:
            SvcRegistry: populated registry with per-service `host_overrides`.
        """
        _host = method_cfg.get("host", "127.0.0.1")
        _hosts_block = method_cfg.get("hosts") or {}
        _deployment = str(method_cfg.get("deployment", "local"))
        if base_port_override > 0:
            _base = base_port_override
        else:
            _base = int(method_cfg["base_port"])
        _table: Dict[str, RegistryEntry] = {}
        _overrides: Dict[str, str] = {}
        for _name, _spec in method_cfg["service_registry"].items():
            _role = _spec["role"]
            _port = _base + int(_spec["port_offset"])
            _table[_name] = RegistryEntry(name=_name,
                                          role=_role,
                                          port=_port)
            _overrides[_name] = cls._pick_host(
                deployment=_deployment,
                name=_name,
                role=_role,
                hosts_block=_hosts_block,
                default_host=_host,
            )
        return cls(host=_host,
                   base_port=_base,
                   table=_table,
                   host_overrides=_overrides)

    @staticmethod
    def _pick_host(*,
                   deployment: str,
                   name: str,
                   role: str,
                   hosts_block: Dict[str, Any],
                   default_host: str) -> str:
        """*_pick_host()* resolve the host for one service per deployment mode.

        Resolution rule per `deployment`:

            - `local` (default): every service maps to top-level `host` (`127.0.0.1`); the `hosts` block is ignored.
            - `loopback_aliased` and `remote`: per-service-name `hosts[N]` if set, else per-bucket `hosts[R]` (`client` for composite_client, `composite` for composite_*, `atomic` for atomic), else top-level `host`.

        Pure function so the policy is unit-testable in isolation.

        Args:
            deployment (str): `"local"` / `"loopback_aliased"` / `"remote"`.
            name (str): service name.
            role (str): service role from the registry table.
            hosts_block (Dict[str, Any]): the `hosts` block from method_cfg.
            default_host (str): top-level `host` fallback.

        Returns:
            str: resolved host address for this service.
        """
        if deployment == "local":
            return default_host
        _per_svc = hosts_block.get(name)
        if _per_svc:
            return str(_per_svc)
        if role == _CLIENT_ROLE:
            _bucket = hosts_block.get("client")
        elif role.startswith(_COMPOSITE_PREFIX):
            _bucket = hosts_block.get("composite")
        elif role == _ATOMIC_ROLE:
            _bucket = hosts_block.get("atomic")
        else:
            _bucket = None
        if _bucket:
            return str(_bucket)
        return default_host

    def host_for(self, name: str) -> str:
        """*host_for()* return the resolved host for `name`; falls back to the registry-wide default."""
        return self.host_overrides.get(name, self.host)

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
        return f"http://{self.host_for(name)}:{_e.port}"

    def build_invoke_url(self, name: str) -> str:
        """*build_invoke_url()* return the per-service invoke endpoint URL.

        TAS_{i} routes share one port and disambiguate by URL path (`/TAS_<i>/invoke`); third-party services use a single `/invoke` per port.

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

    def list_names(self) -> List[str]:
        """*list_names()* return every service name in declaration order."""
        return list(self.table.keys())

    def filter_names_role(self, role: str) -> List[str]:
        """*filter_names_role()* return every service name whose entry carries the given role label.

        Args:
            role (str): role label such as `"atomic"`, `"composite_client"`, `"composite_medical"`, `"composite_alarm"`, `"composite_drug"`.

        Returns:
            List[str]: matching service names in declaration order.
        """
        _matching: List[str] = []
        for _name, _entry in self.table.items():
            if _entry.role == role:
                _matching.append(_name)
        return _matching
