# -*- coding: utf-8 -*-
"""
Module wire/registry.py
=======================

Address book: maps each service name in `experiment.json::service_registry` to its `(host, port)` and renders the per-endpoint URLs the experiment mesh issues HTTP against. Built once at startup and shared across the architecture, the client simulator, and the launcher health barrier. Per-deployment host policy lives in `_pick_host`.

Public API:
    - `SvcRegistry(host, base_port, table, host_overrides)` immutable address book.
    - `SvcRegistry.from_config(method_cfg)` factory from a parsed `experiment.json`.
    - `SvcRegistry.host_for(name)` resolved host for one service.
    - `SvcRegistry.resolve_base_url(name)` `http://host:port` base URL.
    - `SvcRegistry.build_invoke_url(name)` per-service `/invoke` URL (path-disambiguated for TAS_{i}).
    - `SvcRegistry.build_healthz_url(name)` per-port `/healthz` URL.
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
    """*RegistryEntry* one row of the address book; carries the service name, role label, and resolved port."""

    # service name (e.g. `TAS_{1}`, `MAS_{1}`)
    name: str

    # role label such as `"atomic"`, `"composite_client"`, etc. Used for filtering the registry table by workflow stage.
    role: str

    # resolved 16-bit port number (base_port + port_offset from config)
    port: int


@dataclass(frozen=True)
class SvcRegistry:
    """*SvcRegistry* immutable address book that turns a service name into a fully-qualified URL.

    Per-service host can vary by deployment mode: `local` collapses every service to one address; `loopback_aliased` and `remote` route by role bucket with optional per-service-name override. The four URL builders below all funnel through `host_for(name)` so the deployment policy applies uniformly.
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
                    base_port_ovrd: int = 0) -> "SvcRegistry":
        """*from_config()* hydrate an address book from a parsed `experiment.json`.

        Per-service host resolution is delegated to `_pick_host` once at construction so the caller never re-evaluates the policy at lookup time.

        Args:
            method_cfg (Dict[str, Any]): parsed method config.
            base_port_ovrd (int): when non-zero, replaces `method_cfg["base_port"]`. Used for CI / parallel runs via env var.

        Returns:
            SvcRegistry: populated address book with per-service `host_overrides`.
        """
        _host = method_cfg.get("host", "127.0.0.1")
        _hosts_block = method_cfg.get("hosts") or {}
        _deployment = str(method_cfg.get("deployment", "local"))
        if base_port_ovrd > 0:
            _base = base_port_ovrd
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
        """*_pick_host()* policy decision: which host serves one service under the given deployment.

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
            str: chosen host address for this service.
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
        """*host_for()* host of `name` from the per-service override map; falls back to the registry-wide default."""
        return self.host_overrides.get(name, self.host)

    def resolve_base_url(self, name: str) -> str:
        """*resolve_base_url()* assemble `http://host:port` for `name` (no path).

        Args:
            name (str): service name (e.g. `"TAS_{1}"`, `"MAS_{1}"`).

        Raises:
            KeyError: if `name` is not in the registry table.

        Returns:
            str: `http://<host>:<port>` (no trailing slash, no path).
        """
        _e = self.table[name]
        return f"http://{self.host_for(name)}:{_e.port}"

    def build_invoke_url(self, name: str) -> str:
        """*build_invoke_url()* per-service POST endpoint URL.

        TAS_{i} components share a single uvicorn port (Option B) and disambiguate by URL path (`/TAS_<i>/invoke`); third-party services use a single `/invoke` per port.

        Args:
            name (str): service name.

        Raises:
            KeyError: if `name` is not in the registry table.

        Returns:
            str: full `http://host:port/...invoke` URL clients POST against.
        """
        _m = _TAS_KEY_RE.match(name)
        if _m is not None:
            return f"{self.resolve_base_url(name)}/TAS_{_m.group(1)}/invoke"
        return f"{self.resolve_base_url(name)}/invoke"

    def build_healthz_url(self, name: str) -> str:
        """*build_healthz_url()* `/healthz` URL for `name` (one path per port; not per TAS member)."""
        return f"{self.resolve_base_url(name)}/healthz"

    def list_names(self) -> List[str]:
        """*list_names()* every service name in declaration order."""
        return list(self.table.keys())

    def filter_names_role(self, role: str) -> List[str]:
        """*filter_names_role()* every service name whose entry carries the given role label.

        Args:
            role (str): role label such as `"atomic"`, `"composite_client"`, `"composite_medical"`, `"composite_alarm"`, `"composite_drug"`.

        Returns:
            List[str]: matching service names in declaration order; empty when no entry matches.
        """
        _matching: List[str] = []
        for _name, _entry in self.table.items():
            if _entry.role == role:
                _matching.append(_name)
        return _matching
