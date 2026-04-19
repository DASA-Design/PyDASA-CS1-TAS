"""Config-driven PyDASA Schema construction for the TAS case study."""

from __future__ import annotations

from typing import Any

from pydasa.dimensional.vaschy import Schema


def build_schema(fdus: list[dict[str, Any]], *, fwk: str = "CUSTOM") -> Schema:
    """Build a PyDASA Schema from a list of FDU dicts.

    Args:
        fdus: list of dicts with keys `_idx`, `_sym`, `_fwk`, `_name`, `_unit`,
            `description` — the shape that `Schema._fdu_lt` expects. Typically
            loaded from `data/config/method/dimensional.json`.
        fwk: framework name; must match every FDU's `_fwk` field. Defaults to
            `"CUSTOM"` (the TAS convention).

    Returns:
        A `Schema` with `_setup_fdus()` already called, ready to pass to
        `AnalysisEngine(_schema=...)`.

    Raises:
        ValueError: if any FDU's `_fwk` does not match `fwk`.
    """
    _mismatched = [fdu for fdu in fdus if fdu.get("_fwk") != fwk]
    if _mismatched:
        _syms = ", ".join(fdu.get("_sym", "?") for fdu in _mismatched)
        raise ValueError(f"FDUs with _fwk != {fwk!r}: {_syms}")

    _schema = Schema(_fwk=fwk, _fdu_lt=list(fdus), _idx=0)  # type: ignore[call-arg]
    _schema._setup_fdus()
    return _schema
