# -*- coding: utf-8 -*-
"""
Module sensitivity.py
=====================

Symbolic sensitivity analysis wrapper around PyDASA's `SensitivityAnalysis`.

Runs one symbolic-differentiation sweep at a single evaluation point (mean, setpoint, min, or max) and reshapes the raw output into a numeric-only nested dict.

Public API:
    - `analyse_symbolic(engine, schema, val_type="mean")` returns `{SEN_{coeff}: {var: float}}`.

*IMPORTANT:* pydasa keys sensitivity entries as `SEN_{<coeff_symbol>}`, so raw Pi entries become `SEN_{\\Pi_{0}}` and derived ones e.g. `SEN_{\\theta_{TAS_{1}}}`. Callers that want the raw coefficient symbol back need to strip the prefix.
"""
# native python modules
from __future__ import annotations

# pydasa library
from pydasa.dimensional.vaschy import Schema
from pydasa.workflows.influence import SensitivityAnalysis
from pydasa.workflows.phenomena import AnalysisEngine


def analyse_symbolic(engine: AnalysisEngine,
                     schema: Schema,
                     *,
                     val_type: str = "mean",
                     cat: str = "SYM",
                     fwk: str = "CUSTOM",
                     idx: int = 0,
                     name: str = "sensitivity") -> dict[str, dict[str, float]]:
    """*analyse_symbolic()* run symbolic sensitivity at a single value type.

    Args:
        engine (AnalysisEngine): engine with variables and coefficients already populated.
        schema (Schema): framework schema used to build `engine`.
        val_type (str): evaluation point for the partial derivatives; one of `"mean"`, `"setpoint"`, `"min"`, `"max"`. Defaults to `"mean"`.
        cat (str): sensitivity category; `"SYM"` for symbolic differentiation. Defaults to `"SYM"`.
        fwk (str): framework name. Defaults to `"CUSTOM"`.
        idx (int): workflow index (informational).
        name (str): human-readable workflow name.

    Returns:
        dict[str, dict[str, float]]: nested `{SEN_{coeff}: {var: sensitivity_value}}` over every coefficient in `engine.coefficients` (raw Pi and derived). Non-numeric entries are filtered out.
    """
    # spin up the pydasa workflow and attach the same variables/coefficients (pass by keyword — dataclass field order differs from our arg order)
    _sen = SensitivityAnalysis(_idx=idx,
                               _fwk=fwk,
                               _schema=schema,
                               _name=name,
                               _cat=cat)
    _sen.variables = engine.variables
    _sen.coefficients = engine.coefficients

    # run the symbolic pass at the requested evaluation point
    _raw = _sen.analyze_symbolic(val_type=val_type)

    # reshape: keep only numeric leaves, drop sympy residues
    _out: dict[str, dict[str, float]] = {}
    for _coef, _vmap in _raw.items():
        _numeric: dict[str, float] = {}
        for _var_sym, _val in _vmap.items():
            if isinstance(_val, (int, float)):
                _numeric[_var_sym] = float(_val)
        _out[_coef] = _numeric
    return _out
