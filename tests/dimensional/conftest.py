"""Shared fixtures for `tests/dimensional/`.

Module-scope fixtures so each test file builds the TAS_{1} engine exactly
once. Heavier engine setup (post `run_analysis` + `derive_coefficients`)
lives in `engine_ready` to keep per-test coefficient verifications cheap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dimensional import (
    analyse_symbolic,
    build_engine,
    build_schema,
    derive_coefficients,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_METHOD_CFG_PATH = _REPO_ROOT / "data" / "config" / "method" / "dimensional.json"
_DFLT_PATH = _REPO_ROOT / "data" / "config" / "profile" / "dflt.json"
_OPTI_PATH = _REPO_ROOT / "data" / "config" / "profile" / "opti.json"


@pytest.fixture(scope="session")
def method_cfg() -> dict:
    return json.loads(_METHOD_CFG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def dflt_profile() -> dict:
    return json.loads(_DFLT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def opti_profile() -> dict:
    return json.loads(_OPTI_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema(method_cfg):
    return build_schema(method_cfg["fdus"])


@pytest.fixture(scope="module")
def tas1_vars(dflt_profile) -> dict:
    return dflt_profile["artifacts"]["TAS_{1}"]["vars"]


@pytest.fixture(scope="module")
def engine_bare(schema, tas1_vars):
    """Engine with variables but before `run_analysis`."""
    return build_engine("TAS_{1}", tas1_vars, schema)


@pytest.fixture(scope="module")
def engine_ready(schema, tas1_vars, method_cfg):
    """Engine post `run_analysis` + `derive_coefficients`, setpoints evaluated.

    Returns `(engine, derived)` where `derived` is the 4-entry dict
    returned by `derive_coefficients`.
    """
    _engine = build_engine("TAS_{1}", tas1_vars, schema)
    _engine.run_analysis()
    for _coeff in _engine.coefficients.values():
        _coeff.calculate_setpoint()

    _derived = derive_coefficients(
        _engine, method_cfg["coefficients"], artifact_key="TAS_{1}"
    )
    for _coeff in _derived.values():
        _coeff.calculate_setpoint()

    return _engine, _derived


@pytest.fixture(scope="module")
def sensitivity_results(engine_ready, schema, method_cfg):
    _engine, _ = engine_ready
    _cfg = method_cfg["sensitivity"]
    return analyse_symbolic(
        _engine, schema, val_type=_cfg["val_type"], cat=_cfg["cat"]
    )
