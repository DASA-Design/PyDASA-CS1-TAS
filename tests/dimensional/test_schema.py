# -*- coding: utf-8 -*-
"""
Module test_schema.py
=====================

Config-driven `build_schema()` contract:

    - **TestSchemaConstruction**: FDUs from `data/config/method/dimensional.json` land on the Schema with `_setup_fdus()` already applied.
    - **TestSchemaGuardrails**: mismatched `_fwk` raises a clear error.
"""
# testing framework
import pytest

# pydasa library
from pydasa.dimensional.vaschy import Schema

# module under test
from src.dimensional import build_schema


class TestSchemaConstruction:
    """**TestSchemaConstruction** the Schema carries the TAS T/S/D framework after construction, with `_setup_fdus()` already applied."""

    def test_returns_schema_instance(self, schema):
        """*test_returns_schema_instance()* `build_schema()` returns a genuine `Schema` instance."""
        assert isinstance(schema, Schema)

    def test_three_fdus_registered(self, schema):
        """*test_three_fdus_registered()* TAS uses exactly three FDUs (T, S, D)."""
        assert len(schema._fdu_lt) == 3

    def test_fdu_symbols_are_t_s_d(self, schema):
        """*test_fdu_symbols_are_t_s_d()* FDU symbols match the canonical T/S/D set from the config."""
        _syms = {_fdu._sym for _fdu in schema._fdu_lt}
        assert _syms == {"T", "S", "D"}

    def test_fdu_units_match_config(self, schema):
        """*test_fdu_units_match_config()* per-FDU units (s, req, kB) propagate from the config into `_unit`."""
        _units = {_fdu._sym: _fdu._unit for _fdu in schema._fdu_lt}
        assert _units == {"T": "s", "S": "req", "D": "kB"}

    def test_fwk_is_custom(self, schema):
        """*test_fwk_is_custom()* both the Schema and every FDU carry `_fwk == "CUSTOM"` end-to-end."""
        assert schema.fwk == "CUSTOM"
        for _fdu in schema._fdu_lt:
            assert _fdu._fwk == "CUSTOM"


class TestSchemaGuardrails:
    """**TestSchemaGuardrails** guard-rails fire on misconfigured inputs before PyDASA is touched."""

    def test_rejects_mismatched_fwk(self):
        """*test_rejects_mismatched_fwk()* any FDU whose `_fwk` differs from the framework arg raises `ValueError`."""
        _bad_fdus = [
            {"_idx": 0, "_sym": "T", "_fwk": "OTHER", "_name": "Time",
             "_unit": "s", "description": "time"},
        ]
        with pytest.raises(ValueError, match="_fwk"):
            build_schema(_bad_fdus)

    def test_empty_fdu_list_raises(self):
        """*test_empty_fdu_list_raises()* an empty FDU list is rejected — PyDASA rejects empty CUSTOM frameworks and this wrapper propagates the error."""
        with pytest.raises(ValueError, match="FDUs"):
            build_schema([])
