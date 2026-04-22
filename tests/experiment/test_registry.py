# -*- coding: utf-8 -*-
"""
Module test_registry.py
=======================

Unit tests for `src.experiment.registry.ServiceRegistry`:

    - **TestFromConfig** dict-to-registry mapping, port-offset resolution, and `base_port_override`.
    - **TestBuildInvokeUrl** URL shape per service type (third-party `/invoke` vs TAS `/TAS_<i>/invoke`).
    - **TestBuildHealthzUrl** every `/healthz` URL is the same shape regardless of service type.
    - **TestRoleFilters** `list_names()` and `filter_names_role()` return the expected sets.
    - **TestTasComponentsShareAPort** six TAS_{i} entries at `port_offset=0` map to one port but distinct URLs (Option-B topology).
    - **TestUnknownName** names absent from the registry raise `KeyError`.
"""
# native python modules
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.experiment.registry import RegistryEntry, ServiceRegistry


def _cs01_like_cfg() -> Dict[str, Any]:
    """*_cs01_like_cfg()* produce a minimal `experiment.json`-shaped dict covering every service role."""
    return {
        "host": "127.0.0.1",
        "base_port": 8001,
        "service_registry": {
            # six TAS components share port_offset 0 (Option-B: one FastAPI app).
            # Role labels differentiate the CS-01 workflow stage each component
            # plays: client ingress/egress, medical, alarm, drug.
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
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert _r.host == "127.0.0.1"
        assert _r.base_port == 8001

    def test_table_populated_with_registry_entries(self):
        """*test_table_populated_with_registry_entries()* every entry is a `RegistryEntry` with a positive port and a declared role."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
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
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert _r.table["MAS_{1}"].port == 8001 + 6
        assert _r.table["AS_{1}"].port == 8001 + 7
        assert _r.table["DS_{3}"].port == 8001 + 8

    def test_base_port_override(self):
        """*test_base_port_override()* a non-zero `base_port_override` replaces the config value for every entry."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg(), base_port_override=19000)
        assert _r.base_port == 19000
        assert _r.table["MAS_{1}"].port == 19000 + 6
        assert _r.table["TAS_{1}"].port == 19000 + 0

    def test_override_zero_keeps_configured_base(self):
        """*test_override_zero_keeps_configured_base()* `base_port_override=0` is the sentinel for "use the config value"."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg(), base_port_override=0)
        assert _r.base_port == 8001


class TestBuildInvokeUrl:
    """**TestBuildInvokeUrl** TAS names use per-component paths; third-party names get plain `/invoke`."""

    @pytest.fixture
    def _reg(self) -> ServiceRegistry:
        return ServiceRegistry.from_config(_cs01_like_cfg())

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
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert _r.build_healthz_url("TAS_{1}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("TAS_{6}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("MAS_{1}") == "http://127.0.0.1:8007/healthz"


class TestRoleFilters:
    """**TestRoleFilters** `list_names()` returns every entry; `filter_names_role()` subsets correctly."""

    def test_list_names_returns_all(self):
        """*test_list_names_returns_all()* `list_names()` yields every entry in the table (no filtering)."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        _names = list(_r.list_names())
        assert len(_names) == 9
        assert set(_names) == set(_cs01_like_cfg()["service_registry"].keys())

    def test_filter_names_composite_client(self):
        """*test_filter_names_composite_client()* client-facing composites are ingress (TAS_{1}) + egress (TAS_{5}, TAS_{6})."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_client")) == [
            "TAS_{1}", "TAS_{5}", "TAS_{6}"]

    def test_filter_names_per_workflow_stage(self):
        """*test_filter_names_per_workflow_stage()* each internal-routing composite role has exactly one artifact."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_medical")) == ["TAS_{2}"]
        assert list(_r.filter_names_role("composite_alarm")) == ["TAS_{3}"]
        assert list(_r.filter_names_role("composite_drug")) == ["TAS_{4}"]

    def test_filter_names_atomic(self):
        """*test_filter_names_atomic()* every non-TAS third-party service carries the `atomic` role."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("atomic")) == [
            "MAS_{1}", "AS_{1}", "DS_{3}"]

    def test_filter_names_unknown_role_returns_empty(self):
        """*test_filter_names_unknown_role_returns_empty()* a role absent from every entry yields an empty iterator (no exception)."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("made_up")) == []


class TestTasComponentsShareAPort:
    """**TestTasComponentsShareAPort** six TAS_{i} entries at offset 0 collapse to one port but six distinct URLs (Option-B)."""

    def test_ports_identical(self):
        """*test_ports_identical()* six TAS_{i} entries at `port_offset=0` collapse to a single port."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        _ports = {_r.table[f"TAS_{{{_i}}}"].port for _i in range(1, 7)}
        assert _ports == {8001}

    def test_invoke_urls_distinct(self):
        """*test_invoke_urls_distinct()* despite the shared port, each component has its own `/TAS_<i>/invoke` URL."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        _urls = {_r.build_invoke_url(f"TAS_{{{_i}}}") for _i in range(1, 7)}
        assert len(_urls) == 6


class TestUnknownName:
    """**TestUnknownName** unknown service names raise `KeyError` consistently."""

    def test_build_invoke_url_unknown_raises(self):
        """*test_build_invoke_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_invoke_url("NOT_A_SERVICE")

    def test_build_healthz_url_unknown_raises(self):
        """*test_build_healthz_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_healthz_url("NOT_A_SERVICE")

    def test_resolve_base_url_unknown_raises(self):
        """*test_resolve_base_url_unknown_raises()* unknown name propagates `KeyError` from the registry table lookup."""
        _r = ServiceRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.resolve_base_url("NOT_A_SERVICE")
