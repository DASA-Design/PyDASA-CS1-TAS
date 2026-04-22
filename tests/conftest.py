# -*- coding: utf-8 -*-
"""
Module conftest.py
==================

Shared pytest fixtures for the whole test tree. Fixtures are lazy and
scoped so files that do not depend on them pay no runtime cost:

    - `method_cfg` / `dflt_profile` / `opti_profile` are session-scoped json loads.
    - `schema` / `tas1_vars` / `engine_bare` / `engine_ready` are module-scoped PyDASA build steps for TAS_{1}; reused by every `tests/dimensional/` file.
    - `sensitivity_results` is module-scoped and derives from `engine_ready`.
"""
# native python modules
from __future__ import annotations

import json
from pathlib import Path

# testing framework
import pytest

# local modules
from src.dimensional import (analyse_symbolic,
                             build_engine,
                             build_schema,
                             derive_coefs)


_ROOT = Path(__file__).resolve().parents[1]
_METHOD_DIM = _ROOT / "data" / "config" / "method" / "dimensional.json"
_DFLT_PATH = _ROOT / "data" / "config" / "profile" / "dflt.json"
_OPTI_PATH = _ROOT / "data" / "config" / "profile" / "opti.json"


@pytest.fixture(scope="session")
def method_cfg() -> dict:
    """*method_cfg()* loaded `data/config/method/dimensional.json` once per session."""
    return json.loads(_METHOD_DIM.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def dflt_profile() -> dict:
    """*dflt_profile()* loaded `data/config/profile/dflt.json` once per session."""
    return json.loads(_DFLT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def opti_profile() -> dict:
    """*opti_profile()* loaded `data/config/profile/opti.json` once per session."""
    return json.loads(_OPTI_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema(method_cfg):
    """*schema()* PyDASA Schema built from the method-config FDUs, module-cached."""
    return build_schema(method_cfg["fdus"])


@pytest.fixture(scope="module")
def tas1_vars(dflt_profile) -> dict:
    """*tas1_vars()* TAS_{1} variable dict from `dflt.json`, module-cached."""
    return dflt_profile["artifacts"]["TAS_{1}"]["vars"]


@pytest.fixture(scope="module")
def engine_bare(schema, tas1_vars):
    """*engine_bare()* TAS_{1} engine with variables attached but BEFORE `run_analysis()`."""
    return build_engine("TAS_{1}", tas1_vars, schema)


@pytest.fixture(scope="module")
def engine_ready(schema, tas1_vars, method_cfg):
    """*engine_ready()* TAS_{1} engine post `run_analysis()` + `derive_coefs()`, setpoints evaluated.

    Returns:
        tuple: `(engine, derived)` where `derived` is the 4-entry dict returned by `derive_coefs`.
    """
    # build engine and run the Buckingham analysis
    _eng = build_engine("TAS_{1}", tas1_vars, schema)
    _eng.run_analysis()

    # evaluate raw Pi setpoints
    for _c in _eng.coefficients.values():
        _c.calculate_setpoint()

    # derive named coefficients and evaluate their setpoints
    _der = derive_coefs(_eng, method_cfg["coefficients"],
                        artifact_key="TAS_{1}")
    for _c in _der.values():
        _c.calculate_setpoint()

    return _eng, _der


@pytest.fixture(scope="module")
def sensitivity_results(engine_ready, schema, method_cfg):
    """*sensitivity_results()* symbolic-sensitivity dict derived from `engine_ready`, module-cached."""
    _eng, _ = engine_ready
    _sc = method_cfg["sensitivity"]
    return analyse_symbolic(_eng, schema,
                            val_type=_sc["val_type"],
                            cat=_sc["cat"])
