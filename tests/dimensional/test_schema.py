# -*- coding: utf-8 -*-
"""
Module test_schema.py
=====================

Config-driven `build_schema()` contract:

    - **TestSchemaConstruction**: FDUs from `data/config/method/dimensional.json` land on the Schema with `_setup_fdus()` already applied.
    - **TestSchemaGuardrails**: mismatched `_fwk` raises a clear error.
"""
import pytest

from pydasa.dimensional.vaschy import Schema

from src.dimensional import build_schema


class TestSchemaConstruction:
    """Verifies the Schema carries the TAS T/S/D framework after construction."""

    def test_returns_schema_instance(self, schema):
        assert isinstance(schema, Schema)

    def test_three_fdus_registered(self, schema):
        assert len(schema._fdu_lt) == 3

    def test_fdu_symbols_are_t_s_d(self, schema):
        _syms = {fdu._sym for fdu in schema._fdu_lt}
        assert _syms == {"T", "S", "D"}

    def test_fdu_units_match_config(self, schema):
        _units = {fdu._sym: fdu._unit for fdu in schema._fdu_lt}
        assert _units == {"T": "s", "S": "req", "D": "kB"}

    def test_fwk_is_custom(self, schema):
        assert schema.fwk == "CUSTOM"
        for _fdu in schema._fdu_lt:
            assert _fdu._fwk == "CUSTOM"


class TestSchemaGuardrails:
    """Verifies error handling on misconfigured inputs."""

    def test_rejects_mismatched_fwk(self):
        _bad_fdus = [
            {"_idx": 0, "_sym": "T", "_fwk": "OTHER", "_name": "Time",
             "_unit": "s", "description": "time"},
        ]
        with pytest.raises(ValueError, match="_fwk"):
            build_schema(_bad_fdus)

    def test_empty_fdu_list_raises(self):
        # PyDASA rejects an empty CUSTOM framework; our wrapper propagates.
        with pytest.raises(ValueError, match="FDUs"):
            build_schema([])
