# -*- coding: utf-8 -*-
"""
Module test_registry.py
=======================

Pin the `SvcRegistry` address-book contracts: dict-to-registry mapping, port-offset arithmetic, URL builders (per-component TAS path vs flat third-party path), role filters, shared-port Option-B layout, missing-name behaviour, per-deployment host policy.

    - **TestSvcRegistry** every public-API contract; one class per the project's single-class preference.
"""
# native python modules
from typing import Any, Dict

# testing framework
import pytest

# module under test
from src.experiment.wire import RegistryEntry, SvcRegistry


def _cs01_like_cfg() -> Dict[str, Any]:
    """*_cs01_like_cfg()* minimal `experiment.json`-shaped dict with one service per role (composite_client, composite_medical/alarm/drug, atomic).

    Returns:
        Dict[str, Any]: nine entries: six TAS_{i} at port_offset=0 sharing port 8001, three third-party services at offsets 6/7/8.
    """
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


def _cfg_with_hosts(deployment: str,
                    hosts: Dict[str, str]) -> Dict[str, Any]:
    """*_cfg_with_hosts()* CS-01 cfg variant with explicit `deployment` + `hosts` blocks for the per-deployment policy tests.

    Args:
        deployment (str): one of `"localhost"` / `"multiprocess"` / `"remote"`.
        hosts (Dict[str, str]): the `hosts` block (bucket map plus optional per-service-name overrides).

    Returns:
        Dict[str, Any]: copy of `_cs01_like_cfg()` with the two extra keys merged in.
    """
    _cfg = _cs01_like_cfg()
    _cfg["deployment"] = deployment
    _cfg["hosts"] = hosts
    return _cfg


class TestSvcRegistry:
    """**TestSvcRegistry** every public-API contract of the address book."""

    # ----- from_config: scalar copies + table population ----- #

    def test_host_and_base_port(self) -> None:
        """*test_host_and_base_port()* `r.host == "127.0.0.1"` and `r.base_port == 8001` (verbatim from config)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.host == "127.0.0.1"
        assert _r.base_port == 8001

    def test_table_populated(self) -> None:
        """*test_table_populated()* `len(table) == 9`; every value is a `RegistryEntry` with `port > 0` and a role drawn from the declared set."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert len(_r.table) == 9
        _valid_roles = {"composite_client", "composite_medical",
                        "composite_alarm", "composite_drug", "atomic"}
        for _name, _entry in _r.table.items():
            assert isinstance(_entry, RegistryEntry)
            assert _entry.name == _name
            assert _entry.port > 0
            assert _entry.role in _valid_roles

    def test_port_is_base_plus_offset(self) -> None:
        """*test_port_is_base_plus_offset()* `MAS_{1}.port == 8001 + 6`, `AS_{1}.port == 8001 + 7`, `DS_{3}.port == 8001 + 8`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.table["MAS_{1}"].port == 8001 + 6
        assert _r.table["AS_{1}"].port == 8001 + 7
        assert _r.table["DS_{3}"].port == 8001 + 8

    def test_base_port_ovrd(self) -> None:
        """*test_base_port_ovrd()* `base_port_ovrd=19000` -> `r.base_port == 19000`; every entry's port becomes `19000 + offset`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg(), base_port_ovrd=19000)
        assert _r.base_port == 19000
        assert _r.table["MAS_{1}"].port == 19000 + 6
        assert _r.table["TAS_{1}"].port == 19000 + 0

    def test_override_zero_keeps_configured_base(self) -> None:
        """*test_override_zero_keeps_configured_base()* `base_port_ovrd=0` is the sentinel for "use the config value"; `r.base_port == 8001`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg(), base_port_ovrd=0)
        assert _r.base_port == 8001

    # ----- build_invoke_url: TAS path vs third-party path ----- #

    @pytest.mark.parametrize("_name, _expected", [
        ("TAS_{1}", "http://127.0.0.1:8001/TAS_1/invoke"),
        ("TAS_{2}", "http://127.0.0.1:8001/TAS_2/invoke"),
        ("TAS_{6}", "http://127.0.0.1:8001/TAS_6/invoke"),
    ])
    def test_invoke_tas_component_paths(self,
                                        _name: str,
                                        _expected: str) -> None:
        """*test_invoke_tas_component_paths()* TAS_{i} produces `http://host:port/TAS_<i>/invoke` on the shared port."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.build_invoke_url(_name) == _expected

    @pytest.mark.parametrize("_name, _expected", [
        ("MAS_{1}", "http://127.0.0.1:8007/invoke"),
        ("AS_{1}", "http://127.0.0.1:8008/invoke"),
        ("DS_{3}", "http://127.0.0.1:8009/invoke"),
    ])
    def test_invoke_third_party_path(self,
                                     _name: str,
                                     _expected: str) -> None:
        """*test_invoke_third_party_path()* non-TAS names produce `http://host:port/invoke` on each service's own port."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.build_invoke_url(_name) == _expected

    # ----- build_healthz_url: one path per port ----- #

    def test_healthz_shape(self) -> None:
        """*test_healthz_shape()* `/healthz` is one path per port; both TAS_{1} and TAS_{6} return `http://127.0.0.1:8001/healthz`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert _r.build_healthz_url("TAS_{1}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("TAS_{6}") == "http://127.0.0.1:8001/healthz"
        assert _r.build_healthz_url("MAS_{1}") == "http://127.0.0.1:8007/healthz"

    # ----- list_names + filter_names_role ----- #

    def test_list_names_all(self) -> None:
        """*test_list_names_all()* `set(list_names()) == set(service_registry.keys())`; nine entries, no filtering."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _names = list(_r.list_names())
        assert len(_names) == 9
        assert set(_names) == set(_cs01_like_cfg()["service_registry"].keys())

    def test_filter_names_composite_client(self) -> None:
        """*test_filter_names_composite_client()* `filter_names_role("composite_client") == ["TAS_{1}", "TAS_{5}", "TAS_{6}"]` (declaration order)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_client")) == [
            "TAS_{1}", "TAS_{5}", "TAS_{6}"]

    def test_filter_names_per_workflow_stage(self) -> None:
        """*test_filter_names_per_workflow_stage()* each internal-routing composite role returns exactly one artifact."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("composite_medical")) == ["TAS_{2}"]
        assert list(_r.filter_names_role("composite_alarm")) == ["TAS_{3}"]
        assert list(_r.filter_names_role("composite_drug")) == ["TAS_{4}"]

    def test_filter_names_atomic(self) -> None:
        """*test_filter_names_atomic()* `filter_names_role("atomic") == ["MAS_{1}", "AS_{1}", "DS_{3}"]`."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("atomic")) == [
            "MAS_{1}", "AS_{1}", "DS_{3}"]

    def test_filter_unknown_role_empty(self) -> None:
        """*test_filter_unknown_role_empty()* `filter_names_role("made_up") == []` (no exception)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        assert list(_r.filter_names_role("made_up")) == []

    # ----- TAS components share a port ----- #

    def test_tas_ports_identical(self) -> None:
        """*test_tas_ports_identical()* `{r.table["TAS_{i}"].port for i in 1..6} == {8001}` (Option-B single-port collapse)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _ports = {_r.table[f"TAS_{{{_i}}}"].port for _i in range(1, 7)}
        assert _ports == {8001}

    def test_tas_invoke_urls_distinct(self) -> None:
        """*test_tas_invoke_urls_distinct()* despite the shared port, each TAS_{i} has its own `/TAS_<i>/invoke` URL (six unique URLs)."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        _urls = {_r.build_invoke_url(f"TAS_{{{_i}}}") for _i in range(1, 7)}
        assert len(_urls) == 6

    # ----- unknown-name behaviour ----- #

    def test_invoke_url_unknown_raises(self) -> None:
        """*test_invoke_url_unknown_raises()* `build_invoke_url("NOT_A_SERVICE")` raises `KeyError` from the table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_invoke_url("NOT_A_SERVICE")

    def test_healthz_url_unknown_raises(self) -> None:
        """*test_healthz_url_unknown_raises()* `build_healthz_url("NOT_A_SERVICE")` raises `KeyError` from the table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.build_healthz_url("NOT_A_SERVICE")

    def test_resolve_base_url_unknown_raises(self) -> None:
        """*test_resolve_base_url_unknown_raises()* `resolve_base_url("NOT_A_SERVICE")` raises `KeyError` from the table lookup."""
        _r = SvcRegistry.from_config(_cs01_like_cfg())
        with pytest.raises(KeyError):
            _r.resolve_base_url("NOT_A_SERVICE")

    # ----- deployment-mode host resolution ----- #

    def test_localhost_ignores_hosts_block(self) -> None:
        """*test_localhost_ignores_hosts_block()* `deployment="localhost"` -> every `host_for(name) == "127.0.0.1"` (top-level `host`), even when the `hosts` block carries non-null values."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "localhost",
            {"client": "1.2.3.4",
             "composite": "5.6.7.8",
             "atomic": "9.10.11.12"}))
        for _name in _r.list_names():
            assert _r.host_for(_name) == "127.0.0.1"

    def test_multiprocess_buckets(self) -> None:
        """*test_multiprocess_buckets()* `deployment="multiprocess"` -> client members hit `127.0.0.10`, composite members hit `127.0.0.20`, atomic members hit `127.0.0.30`."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "multiprocess",
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

    def test_remote_buckets(self) -> None:
        """*test_remote_buckets()* `deployment="remote"` shares the bucket-routing logic with `multiprocess` (only the IPs differ)."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "remote",
            {"client": "192.168.1.10",
             "composite": "192.168.1.20",
             "atomic": "192.168.1.30"}))
        assert _r.host_for("TAS_{1}") == "192.168.1.10"
        assert _r.host_for("TAS_{2}") == "192.168.1.20"
        assert _r.host_for("MAS_{1}") == "192.168.1.30"

    def test_per_service_override_beats_bucket(self) -> None:
        """*test_per_service_override_beats_bucket()* `hosts["MAS_{1}"]="127.0.0.99"` wins over the bucket entry; sibling `AS_{1}` still routes through the bucket."""
        _hosts = {
            "client": "127.0.0.10",
            "composite": "127.0.0.20",
            "atomic": "127.0.0.30",
            "MAS_{1}": "127.0.0.99"
        }
        _r = SvcRegistry.from_config(_cfg_with_hosts("multiprocess",
                                                     _hosts))
        # MAS_{1} pinned via per-service override
        assert _r.host_for("MAS_{1}") == "127.0.0.99"
        # AS_{1} still resolves through atomic bucket
        assert _r.host_for("AS_{1}") == "127.0.0.30"

    def test_missing_bucket_default(self) -> None:
        """*test_missing_bucket_default()* when the `composite` and `atomic` buckets are absent, those roles fall back to top-level `host="127.0.0.1"`; only the declared `client` bucket routes."""
        # only `client` declared; composite + atomic must fall back
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "remote", {"client": "192.168.1.10"}))
        assert _r.host_for("TAS_{1}") == "192.168.1.10"
        # composite + atomic missing in hosts -> default 127.0.0.1
        assert _r.host_for("TAS_{2}") == "127.0.0.1"
        assert _r.host_for("MAS_{1}") == "127.0.0.1"

    def test_resolve_base_url_uses_override(self) -> None:
        """*test_resolve_base_url_uses_override()* `resolve_base_url` reads through `host_for`, so per-service host overrides reach the URL."""
        _r = SvcRegistry.from_config(_cfg_with_hosts(
            "multiprocess",
            {"client": "127.0.0.10",
             "composite": "127.0.0.20",
             "atomic": "127.0.0.30"}))
        assert _r.resolve_base_url("TAS_{1}") == "http://127.0.0.10:8001"
        assert _r.resolve_base_url("TAS_{2}") == "http://127.0.0.20:8001"
        assert _r.resolve_base_url("MAS_{1}") == "http://127.0.0.30:8007"
