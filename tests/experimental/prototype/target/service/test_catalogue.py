"""Tests for `src.experimental.prototype.target.service.catalogue`.

**TestCatalogue**:

- `test_default_layer`: loading `external_services.json` with no version returns the `_setpoint` layer (`weyns_2015` -> 7 entries).
- `test_named_layer`: explicit `version='camara_2023'` returns the 9-entry Cámara layer.
- `test_unknown_version`: an unknown version raises `ValueError`.
- `test_lookup`: `catalogue.lookup(svc_id)` returns the typed entry; unknown ids raise `KeyError`.
- `test_by_kind_filters`: `catalogue.by_kind('alarm')` returns only alarm entries.
- `test_reported_kept`: a Cámara 2023 entry's `reported` block surfaces both `failure_rate` and `response_time_s`.
- `test_no_versions_list`: a JSON without `_versions` raises `ValueError`.
- `test_no_kind`: an entry without `kind` raises `ValueError`.

**TestFailureModes**:

- `test_load_default_only`: a sidecar with only `_default` returns it for every service via `mix_for(...)`.
- `test_per_service_override`: a sidecar with a `services` entry overrides the default for that service.
- `test_unknown_mech`: a mix keyed by `weird` raises `ValueError`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experimental.prototype.target.service.catalogue import (
    ServiceCatalogueEntry,
    load_catalogue,
    load_failure_modes,
)


def _write(tmp_path: Path, name: str, doc: dict) -> Path:
    """Helper: write `doc` as JSON under `tmp_path/name`."""
    _path = tmp_path / name
    _path.write_text(json.dumps(doc), encoding="utf-8")
    return _path


class TestCatalogue:
    """`ServiceCatalogue` loader + lookup."""

    def test_default_layer(self) -> None:
        """*test_default_layer()* default-path load with `version=None` returns the `weyns_2015` layer (7 entries; kinds = {alarm, medical_analysis, drug})."""
        _cat = load_catalogue()
        assert _cat.name == "weyns_2015"
        assert len(_cat.entries) == 7
        _kinds = {_e.kind for _e in _cat.entries.values()}
        assert _kinds == {"alarm", "medical_analysis", "drug"}

    def test_named_layer(self) -> None:
        """*test_named_layer()* `version='camara_2023'` returns the 9-entry Cámara layer."""
        _cat = load_catalogue("camara_2023")
        assert _cat.name == "camara_2023"
        assert len(_cat.entries) == 9

    def test_unknown_version(self) -> None:
        """*test_unknown_version()* an unknown version raises `ValueError`."""
        with pytest.raises(ValueError, match="unknown catalogue version"):
            load_catalogue("nope")

    def test_lookup(self) -> None:
        """*test_lookup()* `catalogue.lookup('AS_{1}')` returns the matching entry; unknown ids raise `KeyError`."""
        _cat = load_catalogue("weyns_2015")
        _entry = _cat.lookup("AS_{1}")
        assert isinstance(_entry, ServiceCatalogueEntry)
        assert _entry.kind == "alarm"
        with pytest.raises(KeyError):
            _cat.lookup("nope")

    def test_by_kind_filters(self) -> None:
        """*test_by_kind_filters()* `catalogue.by_kind('alarm')` returns only the three alarm entries."""
        _cat = load_catalogue("weyns_2015")
        _alarms = _cat.by_kind("alarm")
        assert {_e.svc_id for _e in _alarms} == {"AS_{1}", "AS_{2}", "AS_{3}"}

    def test_reported_kept(self) -> None:
        """*test_reported_kept()* a Cámara 2023 entry surfaces `failure_rate` and `response_time_s` under `reported`."""
        _cat = load_catalogue("camara_2023")
        _entry = _cat.lookup("AS_{1}")
        assert _entry.reported["failure_rate"] == 0.003
        assert _entry.reported["response_time_s"] == 0.011

    def test_no_versions_list(self, tmp_path: Path) -> None:
        """*test_no_versions_list()* a JSON without `_versions` raises `ValueError`."""
        _path = _write(tmp_path, "bad.json", {"_setpoint": "v1", "v1": {"services": {}}})
        with pytest.raises(ValueError, match="_versions"):
            load_catalogue(path=_path)

    def test_no_kind(self, tmp_path: Path) -> None:
        """*test_no_kind()* an entry without `kind` raises `ValueError`."""
        _doc = {
            "_setpoint": "v1",
            "_versions": ["v1"],
            "v1": {"services": {"AS_{1}": {"reported": {"failure_rate": 0.1}}}},
        }
        _path = _write(tmp_path, "bad.json", _doc)
        with pytest.raises(ValueError, match="kind"):
            load_catalogue(path=_path)


class TestFailureModes:
    """`load_failure_modes` + `FailureModesCfg.mix_for` over the version-layered sidecar."""

    def test_default_layer(self) -> None:
        """*test_default_layer()* default-path load with `version=None` reads the on-disk `_setpoint` layer (`weyns_2015`) and returns its 7 per-service entries."""
        _cfg = load_failure_modes()
        # Every weyns_2015 service should be listed; AS_{1} should match the alarm pattern.
        assert _cfg.mix_for("AS_{1}")["drop"] == 0.5
        # A service NOT in the weyns_2015 layer (e.g. MAS_{4}) falls back to `_default`.
        assert _cfg.mix_for("MAS_{4}") == {"timeout": 0.5, "drop": 0.2, "5xx": 0.3}

    def test_named_layer(self) -> None:
        """*test_named_layer()* `version='weyns_iftikhar_2016'` returns the 15-entry mix layer; MAS_{4} is now listed and matches the medical_analysis pattern."""
        _cfg = load_failure_modes("weyns_iftikhar_2016")
        assert _cfg.mix_for("MAS_{4}")["timeout"] == 0.6

    def test_unknown_version(self) -> None:
        """*test_unknown_version()* an unknown version raises `ValueError`."""
        with pytest.raises(ValueError, match="unknown failure-modes version"):
            load_failure_modes("nope")

    def test_default_only_layer(self, tmp_path: Path) -> None:
        """*test_default_only_layer()* a sidecar with an empty `services` block in the chosen version returns `_default` for every lookup."""
        _doc = {
            "_setpoint": "v1",
            "_versions": ["v1"],
            "_default": {"timeout": 0.5, "drop": 0.2, "5xx": 0.3},
            "v1": {"services": {}},
        }
        _path = _write(tmp_path, "fm.json", _doc)
        _cfg = load_failure_modes(path=_path)
        assert _cfg.mix_for("AS_{1}") == {"timeout": 0.5, "drop": 0.2, "5xx": 0.3}

    def test_per_service_override(self, tmp_path: Path) -> None:
        """*test_per_service_override()* a per-service entry inside the chosen version overrides the default for that service; unlisted services still fall back to `_default`."""
        _doc = {
            "_setpoint": "v1",
            "_versions": ["v1"],
            "_default": {"timeout": 0.5, "drop": 0.2, "5xx": 0.3},
            "v1": {"services": {"MAS_{1}": {"timeout": 1.0, "drop": 0.0, "5xx": 0.0}}},
        }
        _path = _write(tmp_path, "fm.json", _doc)
        _cfg = load_failure_modes(path=_path)
        assert _cfg.mix_for("MAS_{1}")["timeout"] == 1.0
        assert _cfg.mix_for("AS_{1}")["timeout"] == 0.5

    def test_unknown_mech(self, tmp_path: Path) -> None:
        """*test_unknown_mech()* an unknown mechanism in the default mix raises `ValueError`."""
        _doc = {"_default": {"weird": 1.0}, "_setpoint": "v1", "_versions": ["v1"], "v1": {"services": {}}}
        _path = _write(tmp_path, "fm.json", _doc)
        with pytest.raises(ValueError):
            load_failure_modes(path=_path)

    def test_no_versions(self, tmp_path: Path) -> None:
        """*test_no_versions()* a sidecar without `_versions` raises `ValueError`."""
        _doc = {"_default": {"timeout": 0.5, "drop": 0.2, "5xx": 0.3}}
        _path = _write(tmp_path, "fm.json", _doc)
        with pytest.raises(ValueError, match="_versions"):
            load_failure_modes(path=_path)
