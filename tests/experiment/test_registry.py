# -*- coding: utf-8 -*-
"""
Module test_registry.py
=======================

Unit tests for `src.experiment.registry.SvcRegistry`. Class roster:

    - **TestFromConfig** dict-to-registry mapping, port-offset resolution, and `base_port_override`.
    - **TestBuildInvokeUrl** URL shape per service type (third-party `/invoke` vs TAS `/TAS_<i>/invoke`).
    - **TestBuildHealthzUrl** every `/healthz` URL is the same shape regardless of service type.
    - **TestRoleFilters** `list_names()` and `filter_names_role()` return the expected sets.
    - **TestTasComponentsShareAPort** six TAS_{i} entries at `port_offset=0` map to one port but distinct URLs (Option-B topology).
    - **TestUnknownName** names absent from the registry raise `KeyError`.
    - **TestDeploymentResolution** per-deployment host resolution; `local` collapses to top-level `host`, the other modes route by bucket with per-service override.
"""
# native python modules
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.experiment.registry import RegistryEntry, SvcRegistry


def _cs01_like_cfg() -> Dict[str, Any]:
    """*_cs01_like_cfg()* return a minimal `experiment.json`-shaped dict with one service per role (composite_client, composite_medical/alarm/drug, atomic)."""
    return {
        "host": "127.0.0.1",
        "base_port": 8001,
        "service_registry": {
            # six TAS components share port_offset 0 (Option-B: one FastAPI app); roles tag the workflow stage (client / medical / alarm / drug)
            "TAS_{1}": {"port_offset": 0, "role": "composite_client"},
            "TAS_{2}": {"port_offset": 0, "role": "composite_medical"},
            "TAS_{3}": {"port_offset": 0, "role": "composite_alarm"},
            "TAS_{4}": {"port_offset": 0, "role": "composite_drug"},
            "TAS_{5}": {"port_offset": 0, "role": "composite_client"},
            "TAS_{6}": {"port_offset": 0, "role": "composite_client"},
            # third-party services each get their own port
            "MAS_{1}": {"port_offset": 6, "role": "atomic"},
            "AS_{1}": {"port_offset": 7, "role": "atomic"},
            "DS_{3}": {"port_offset": 8, "role": "atomic"},
        },
    }


class TestFromConfig:
    """**TestFromConfig** dict-to-registry mapping."""

    def test_host_and_base_port(self):
        """*test_host_and_base_port()* `host` and `base_port` are copied verbatim from the method config."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.host == "127.0.0.1"
        assert _r.base_port == 8001

    def test_table_populated_with_registry_entries(self):
        """*test_table_populated_with_registry_entries()* every entry is a `RegistryEntry` with a positive port and a declared role."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert len(_r.table) == 9
        _valid_roles = {"composite_client", "composite_medical",
                        "composite_alarm", "composite_drug", "atomic"}
        for _name, _entry in _r.table.items():
            assert isinstance(_entry, RegistryEntry)
            assert _entry.name == _name
            assert _entry.port > 0
            assert _entry.role in _valid_roles

    def test_port_is_base_plus_offset(self):
        """*test_port_is_base_plus_offset()* each entry's resolved port equals `base_port + port_offset`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.table["MAS_{1}"].port == 8001 + 6
        assert _r.table["AS_{1}"].port == 8001 + 7
        assert _r.table["DS_{3}"].port == 8001 + 8

    def test_base_port_override(self):
        """*test_base_port_override()* a non-zero `base_port_override` replaces the config value for every entry."""
        _r = SvcRegistry.from_config(_cs01_like_cfg(), base_port_override=19000)
        assert _r.base_port == 19000
        assert _r.table["MAS_{1}"].port == 19000 + 6
        assert _r.table["TAS_{1}"].port == 19000 + 0

    def test_override_zero_keeps_configured_base(self):
        """*test_override_zero_keeps_configured_base()* `base_port_override=0` is the sentinel for "use the config value"."""
        _r = SvcRegistry.from_config(_cs01_like_cfg(), base_port_override=0)
        assert _r.base_port == 8001


class TestBuildInvokeUrl:
    """**TestBuildInvokeUrl** TAS names use per-component paths; third-party names get plain `/invoke`."""

    @pytest.fixture
    def _reg(self) -> SvcRegistry:
        return SvcRegistry.from_config(_cs01_like_cfg())

    @pytest.mark.parametrize("_name, _expected", [
        ("TAS_{1}", "http://127.0.0.1:8001/TAS_1/invoke"),
        ("TAS_{2}", "http://127.0.0.1:8001/TAS_2/invoke"),
        ("TAS_{6}", "http://127.0.0.1:8001/TAS_6/invoke"),
    ])
    def test_tas_component_paths(self, _reg, _name, _expected):
        """*test_tas_component_paths()* TAS names build `/TAS_<i>/invoke` per-component paths on the shared port."""
        assert _reg.build_invoke_url(_name) == _expected

    @pytest.mark.parametrize("_name, _expected", [
        ("MAS_{1}", "http://127.0.0.1:8007/invoke"),
        ("AS_{1}", "http://127.0.0.1:8008/invoke"),
        ("DS_{3}", "http://127.0.0.1:8009/invoke"),
    ])
    def test_third_party_path(self, _reg, _name, _expected):
        """*test_third_party_path()* non-TAS names build a plain `/invoke` route on their own port."""
        assert _reg.build_invoke_url(_name) == _expected


class TestBuildHealthzUrl:
    """**TestBuildHealthzUrl** one `/healthz` path per port; not affected by TAS-component addressing."""

    def test_healthz_shape(self):
        """*test_healthz_shape()* `/healthz` is one path per port, not per TAS component (unlike `/invoke`)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.build_healthz_url("TAS_{1}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("TAS_{6}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("MAS_{1}") == "http://127.0.0.1:8007/healthz"


class TestRoleFilters:
    """**TestRoleFilters** `list_names()` returns every entry; `filter_names_role()` subsets correctly."""

    def test_list_names_returns_all(self):
        """*test_list_names_returns_all()* `list_names()` yields every entry in the table (no filtering)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _names = list(_r.list_names())
        assert len(_names) == 9
        assert set(_names) == set(_cs01_like_cfg()["service_registry"].keys())

    def test_filter_names_composite_client(self):
        """*test_filter_names_composite_client()* client-facing composites are ingress (TAS_{1}) + egress (TAS_{5}, TAS_{6})."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_client")) == [
            "TAS_{1}", "TAS_{5}", "TAS_{6}"]

    def test_filter_names_per_workflow_stage(self):
        """*test_filter_names_per_workflow_stage()* each internal-routing composite role has exactly one artifact."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_medical")) == ["TAS_{2}"]
        assert list(_r.filter_names_role("composite_alarm")) == ["TAS_{3}"]
        assert list(_r.filter_names_role("composite_drug")) == ["TAS_{4}"]

    def test_filter_names_atomic(self):
        """*test_filter_names_atomic()* every non-TAS third-party service carries the `atomic` role."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("atomic")) == [
            "MAS_{1}", "AS_{1}", "DS_{3}"]

    def test_filter_names_unknown_role_returns_empty(self):
        """*test_filter_names_unknown_role_returns_empty()* a role absent from every entry yields an empty iterator (no exception)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("made_up")) == []


class TestTasComponentsShareAPort:
    """**TestTasComponentsShareAPort** six TAS_{i} entries at offset 0 collapse to one port but six distinct URLs (Option-B)."""

    def test_ports_identical(self):
        """*test_ports_identical()* six TAS_{i} entries at `port_offset=0` collapse to a single port."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _ports = {_r.table[f"TAS_{{{_i}}}"].port for _i in range(1, 7)}
        assert _ports == {8001}

    def test_invoke_urls_distinct(self):
        """*test_invoke_urls_distinct()* despite the shared port, each component has its own `/TAS_<i>/invoke` URL."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _urls = {_r.build_invoke_url(f"TAS_{{{_i}}}") for _i in range(1, 7)}
        assert len(_urls) == 6


class TestUnknownName:
    """**TestUnknownName** unknown service names raise `KeyError` consistently."""

    def test_build_invoke_url_unknown_raises(self):
        """*test_build_invoke_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_invoke_url("NOT_A_SERVICE")

    def test_build_healthz_url_unknown_raises(self):
        """*test_build_healthz_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_healthz_url("NOT_A_SERVICE")

    def test_resolve_base_url_unknown_raises(self):
        """*test_resolve_base_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.resolve_base_url("NOT_A_SERVICE")


def _cfg_with_hosts(deployment: str,
                    hosts: Dict[str, str]) -> Dict[str, Any]:
    """*_cfg_with_hosts()* CS-01-shaped cfg with explicit `deployment` + `hosts`."""
    _cfg = _cs01_like_cfg()
    _cfg["deployment"] = deployment
    _cfg["hosts"] = hosts
    return _cfg


class TestDeploymentResolution:
    """**TestDeploymentResolution** per-deployment host resolution covering the 3-mode enum (`local` / `loopback_aliased` / `remote`)."""

    def test_local_ignores_hosts_block(self):
        """*test_local_ignores_hosts_block()* `local` mode forces every service to top-level `host`, even when `hosts` block carries non-null values."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "local",
            {"client": "1.2.3.4",
             "composite": "5.6.7.8",
             "atomic": "9.10.11.12"}))
        for _name in _r.list_names():
            assert _r.host_for(_name) == "127.0.0.1"

    def test_loopback_aliased_routes_by_bucket(self):
        """*test_loopback_aliased_routes_by_bucket()* every service maps to its bucket's loopback alias (`127.0.0.10` for client, `127.0.0.20` for composite, `127.0.0.30` for atomic)."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "loopback_aliased",
            {"client": "127.0.0.10",
             "composite": "127.0.0.20",
             "atomic": "127.0.0.30"}))
        # composite_client members go to client bucket
        for _name in ("TAS_{1}", "TAS_{5}", "TAS_{6}"):
            assert _r.host_for(_name) == "127.0.0.10"
        # composite_medical / _alarm / _drug go to composite bucket
        for _name in ("TAS_{2}", "TAS_{3}", "TAS_{4}"):
            assert _r.host_for(_name) == "127.0.0.20"
        # atomic services go to atomic bucket
        for _name in ("MAS_{1}", "AS_{1}", "DS_{3}"):
            assert _r.host_for(_name) == "127.0.0.30"

    def test_remote_routes_by_bucket(self):
        """*test_remote_routes_by_bucket()* `remote` shares resolution with `loopback_aliased`; only the IPs differ (LAN addresses)."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "remote",
            {"client": "192.168.1.10",
             "composite": "192.168.1.20",
             "atomic": "192.168.1.30"}))
        assert _r.host_for("TAS_{1}") == "192.168.1.10"
        assert _r.host_for("TAS_{2}") == "192.168.1.20"
        assert _r.host_for("MAS_{1}") == "192.168.1.30"

    def test_per_service_override_beats_bucket(self):
        """*test_per_service_override_beats_bucket()* `hosts[<service_name>]` takes precedence over the role-bucket lookup."""
        _hosts = {
            "client": "127.0.0.10",
            "composite": "127.0.0.20",
            "atomic": "127.0.0.30",
            "MAS_{1}": "127.0.0.99"
        }
        _r = SvcRegistry.from_config(_cfg_with_hosts("loopback_aliased",
                                                     _hosts))
        # MAS_{1} pinned via per-service override
        assert _r.host_for("MAS_{1}") == "127.0.0.99"
        # AS_{1} still resolves through atomic bucket
        assert _r.host_for("AS_{1}") == "127.0.0.30"

    def test_missing_bucket_falls_back_to_default_host(self):
        """*test_missing_bucket_falls_back_to_default_host()* when a bucket key is absent, that role's services fall back to top-level `host`."""
        # only `client` declared; composite + atomic must fall back
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "remote", {"client": "192.168.1.10"}))
        assert _r.host_for("TAS_{1}") == "192.168.1.10"
        # composite + atomic missing in hosts -> default 127.0.0.1
        assert _r.host_for("TAS_{2}") == "127.0.0.1"
        assert _r.host_for("MAS_{1}") == "127.0.0.1"

    def test_resolve_base_url_uses_per_service_host(self):
        """*test_resolve_base_url_uses_per_service_host()* `resolve_base_url` reads through `host_for`, not the registry-wide default."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "loopback_aliased",
            {"client": "127.0.0.10",
             "composite": "127.0.0.20",
             "atomic": "127.0.0.30"}))
        assert _r.resolve_base_url("TAS_{1}") == "http://127.0.0.10:8001"
        assert _r.resolve_base_url("TAS_{2}") == "http://127.0.0.20:8001"
        assert _r.resolve_base_url("MAS_{1}") == "http://127.0.0.30:8007"
