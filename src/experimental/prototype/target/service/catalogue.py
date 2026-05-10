"""Loaders for the service catalogue and its failure-modes sidecar.

The catalogue file (`data/config/method/prototype/catalogue/external_services.json`) holds the per-version service menu used by Weyns & Calinescu 2015, Weyns & Iftikhar 2016, and Cámara 2023, stacked as named layers in one document. Each entry carries a `kind` (the workflow engine groups dispatchable services by kind) and an optional `reported` block carrying the source paper's archival numbers (for documentation; the apparatus does not read it).

Apparatus-controlled values (mu, epsilon, c, K) live in `data/config/profile/{dflt,opti}.json::specs`, not here. The failure-mechanism mix lives in the `failure_modes.json` sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.experimental.common.payload.request import FailureMechanism

DFLT_CATALOGUE_DIR = Path("data/config/method/prototype/catalogue")
DFLT_CATALOGUE_FILE = "external_services.json"
DFLT_FAILURE_MODES_FILE = "failure_modes.json"


@dataclass(frozen=True)
class ServiceCatalogueEntry:
    """One row in a service catalogue.

    Attributes:
        svc_id (str): identifier matching the artifact key in `data/config/profile/*.json` (e.g. `AS_{1}`).
        kind (str): catalogue group (`alarm` / `medical_analysis` / `drug`); the workflow engine resolves a step's `svc_kind` to a concrete `svc_id` via this field.
        reported (dict[str, float]): archival numbers from the source paper (e.g. `{"failure_rate": 0.11, "response_time_s": 0.011}`). Not read by the apparatus; kept for documentation + future verdict comparison.
    """

    svc_id: str
    kind: str
    reported: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceCatalogue:
    """A full catalogue of services from one reported source layer.

    Attributes:
        name (str): version stem (e.g. `weyns_2015`).
        source (str): bibliographic citation copied from the layer's `_source`.
        entries (dict[str, ServiceCatalogueEntry]): keyed by `svc_id`.
    """

    name: str
    source: str
    entries: dict[str, ServiceCatalogueEntry]

    def by_kind(self, kind: str) -> list[ServiceCatalogueEntry]:
        """Return every entry in catalogue group `kind`, in catalogue order.

        Args:
            kind (str): catalogue group (e.g. `alarm`).

        Returns:
            list[ServiceCatalogueEntry]: matching entries; empty list if none.
        """
        _ans: list[ServiceCatalogueEntry] = []
        for _entry in self.entries.values():
            if _entry.kind == kind:
                _ans.append(_entry)
        return _ans

    def lookup(self, svc_id: str) -> ServiceCatalogueEntry:
        """Return the entry for `svc_id`.

        Args:
            svc_id (str): catalogue key.

        Returns:
            ServiceCatalogueEntry: stored entry.

        Raises:
            KeyError: if `svc_id` is not in the catalogue.
        """
        try:
            _ans = self.entries[svc_id]
        except KeyError as _err:
            _msg = f"service id {svc_id!r} not in catalogue {self.name!r}"
            raise KeyError(_msg) from _err
        return _ans


def load_catalogue(version: str | None = None,
                   *,
                   path: Path | None = None) -> ServiceCatalogue:
    """Load one version layer from `external_services.json` into a `ServiceCatalogue`.

    Args:
        version (str | None, optional): version stem to read (e.g. `weyns_2015`). Defaults to None, which reads the file's `_setpoint`.
        path (Path | None, optional): override the catalogue file path (tests). Defaults to `DFLT_CATALOGUE_DIR / DFLT_CATALOGUE_FILE`.

    Returns:
        ServiceCatalogue: parsed catalogue for the chosen version.

    Raises:
        FileNotFoundError: if the catalogue file does not exist.
        ValueError: if the JSON is malformed, the version is unknown, or any entry omits a required field.
    """
    if path is None:
        _path = DFLT_CATALOGUE_DIR / DFLT_CATALOGUE_FILE
    else:
        _path = path
    if not _path.exists():
        _msg = f"catalogue file not found: {_path}"
        raise FileNotFoundError(_msg)
    with _path.open(encoding="utf-8") as _fh:
        _doc = json.load(_fh)
    _ans = _parse_catalogue(_doc, version)
    return _ans


def _parse_catalogue(doc: dict[str, object],
                     version: str | None) -> ServiceCatalogue:
    """Validate the document shape, pick the version layer, build the typed catalogue.

    Args:
        doc (dict): parsed JSON content of `external_services.json`.
        version (str | None): which version layer to read; `None` falls back to `_setpoint`.

    Returns:
        ServiceCatalogue: typed catalogue.

    Raises:
        ValueError: when `_versions` / `_setpoint` are missing, when the requested version is not declared, or when an entry omits `kind`.
    """
    _versions = doc.get("_versions")
    if not isinstance(_versions, list) or not _versions:
        _msg = "catalogue document is missing a non-empty `_versions` list"
        raise ValueError(_msg)
    if version is None:
        _setpoint = doc.get("_setpoint")
        if not isinstance(_setpoint, str):
            _msg = "catalogue document is missing `_setpoint`"
            raise ValueError(_msg)
        _version = _setpoint
    else:
        _version = version
    if _version not in _versions:
        _msg = f"unknown catalogue version {_version!r}; known: {_versions}"
        raise ValueError(_msg)
    _layer = doc.get(_version)
    if not isinstance(_layer, dict):
        _msg = f"catalogue version {_version!r} is missing or not an object"
        raise ValueError(_msg)
    _services_raw = _layer.get("services")
    if not isinstance(_services_raw, dict):
        _msg = f"catalogue version {_version!r}: `services` object is required"
        raise ValueError(_msg)
    _source = str(_layer.get("_source", ""))
    _entries: dict[str, ServiceCatalogueEntry] = {}
    for _svc_id, _row in _services_raw.items():
        if not isinstance(_row, dict):
            _msg = (f"catalogue version {_version!r}, entry {_svc_id!r}: "
                    f"must be an object, got {type(_row).__name__}")
            raise ValueError(_msg)
        _entries[_svc_id] = _build_entry(_version, _svc_id, _row)
    _ans = ServiceCatalogue(name=_version, source=_source, entries=_entries)
    return _ans


def _build_entry(version: str,
                 svc_id: str,
                 row: dict[str, object]) -> ServiceCatalogueEntry:
    """Build one `ServiceCatalogueEntry` from a JSON row dict.

    Args:
        version (str): owning version (for error messages).
        svc_id (str): catalogue key.
        row (dict): entry contents.

    Returns:
        ServiceCatalogueEntry: typed entry.

    Raises:
        ValueError: if `kind` is missing or `reported` is malformed.
    """
    if "kind" not in row:
        _msg = f"catalogue version {version!r}, entry {svc_id!r}: missing required key 'kind'"
        raise ValueError(_msg)
    _reported_raw = row.get("reported", {})
    if not isinstance(_reported_raw, dict):
        _msg = (f"catalogue version {version!r}, entry {svc_id!r}: "
                f"'reported' must be an object when present")
        raise ValueError(_msg)
    _reported: dict[str, float] = {}
    for _key, _val in _reported_raw.items():
        _reported[str(_key)] = float(_val)  # type: ignore[arg-type]
    _ans = ServiceCatalogueEntry(svc_id=svc_id,
                                 kind=str(row["kind"]),
                                 reported=_reported)
    return _ans


@dataclass(frozen=True)
class FailureModesCfg:
    """Sidecar `failure_modes.json` parsed into a typed shape.

    Attributes:
        default_mix (dict[FailureMechanism, float]): probability mass over `timeout` / `drop` / `5xx` applied to any service not listed in `services`.
        services (dict[str, dict[FailureMechanism, float]]): per-service overrides keyed by `svc_id`.
    """

    default_mix: dict[FailureMechanism, float]
    services: dict[str, dict[FailureMechanism, float]]

    def mix_for(self, svc_id: str) -> dict[FailureMechanism, float]:
        """Return the failure-mechanism mix for `svc_id`, falling back to the default.

        Args:
            svc_id (str): service identifier.

        Returns:
            dict[FailureMechanism, float]: probability mass for this service.
        """
        _ans = self.services.get(svc_id, self.default_mix)
        return _ans


def load_failure_modes(version: str | None = None,
                       *,
                       path: Path | None = None) -> FailureModesCfg:
    """Load one version layer from `failure_modes.json` into a typed `FailureModesCfg`.

    Layout mirrors `external_services.json`: top-level `_setpoint`, `_versions`, and per-version `services` blocks. Top-level `_default` is the cross-version fallback used by `mix_for(...)` when the chosen version layer omits a service.

    Args:
        version (str | None, optional): version stem to read (e.g. `weyns_2015`). Defaults to None, which reads the file's `_setpoint`.
        path (Path | None, optional): override the sidecar path (tests). Defaults to `DFLT_CATALOGUE_DIR / DFLT_FAILURE_MODES_FILE`.

    Returns:
        FailureModesCfg: parsed sidecar for the chosen version.

    Raises:
        FileNotFoundError: if the sidecar file does not exist.
        ValueError: if `_default` / `_versions` / `_setpoint` are missing, the requested version is unknown, or an entry contains an unknown mechanism.
    """
    if path is None:
        _path = DFLT_CATALOGUE_DIR / DFLT_FAILURE_MODES_FILE
    else:
        _path = path
    if not _path.exists():
        _msg = f"failure modes sidecar not found: {_path}"
        raise FileNotFoundError(_msg)
    with _path.open(encoding="utf-8") as _fh:
        _doc = json.load(_fh)
    _default_raw = _doc.get("_default")
    if not isinstance(_default_raw, dict):
        _msg = "failure modes sidecar: `_default` mix is required at top level"
        raise ValueError(_msg)
    _default = _coerce_mix("_default", _default_raw)
    _versions = _doc.get("_versions")
    if not isinstance(_versions, list) or not _versions:
        _msg = "failure modes sidecar: `_versions` non-empty list is required"
        raise ValueError(_msg)
    if version is None:
        _setpoint = _doc.get("_setpoint")
        if not isinstance(_setpoint, str):
            _msg = "failure modes sidecar: `_setpoint` is required when version=None"
            raise ValueError(_msg)
        _version = _setpoint
    else:
        _version = version
    if _version not in _versions:
        _msg = f"unknown failure-modes version {_version!r}; known: {_versions}"
        raise ValueError(_msg)
    _layer = _doc.get(_version)
    if not isinstance(_layer, dict):
        _msg = f"failure modes sidecar version {_version!r}: missing or not an object"
        raise ValueError(_msg)
    _services_raw = _layer.get("services") or {}
    if not isinstance(_services_raw, dict):
        _msg = (f"failure modes sidecar version {_version!r}: "
                f"`services` must be an object when present")
        raise ValueError(_msg)
    _services: dict[str, dict[FailureMechanism, float]] = {}
    for _svc_id, _mix_raw in _services_raw.items():
        if not isinstance(_mix_raw, dict):
            _msg = (f"failure modes sidecar version {_version!r}, service {_svc_id!r}: "
                    f"override must be an object")
            raise ValueError(_msg)
        _services[str(_svc_id)] = _coerce_mix(str(_svc_id), _mix_raw)
    _ans = FailureModesCfg(default_mix=_default, services=_services)
    return _ans


def _coerce_mix(label: str,
                raw: dict[str, object]) -> dict[FailureMechanism, float]:
    """Validate one mix dict and coerce values to float.

    Args:
        label (str): owning entry label (for error messages).
        raw (dict): mix dict from JSON.

    Returns:
        dict[FailureMechanism, float]: typed mix.

    Raises:
        ValueError: if any key is not a known mechanism.
    """
    _ans: dict[FailureMechanism, float] = {}
    for _mech, _prob in raw.items():
        if _mech not in ("timeout", "drop", "5xx"):
            _msg = (f"failure modes sidecar, entry {label!r}: "
                    f"unknown mechanism {_mech!r}; expected 'timeout', 'drop', or '5xx'")
            raise ValueError(_msg)
        _ans[_mech] = float(_prob)  # type: ignore[arg-type]
    return _ans


__all__ = [
    "DFLT_CATALOGUE_DIR",
    "DFLT_CATALOGUE_FILE",
    "DFLT_FAILURE_MODES_FILE",
    "FailureModesCfg",
    "ServiceCatalogue",
    "ServiceCatalogueEntry",
    "load_catalogue",
    "load_failure_modes",
]
