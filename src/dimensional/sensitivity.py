"""Symbolic sensitivity analysis wrapper around PyDASA's SensitivityAnalysis."""

from __future__ import annotations

from typing import Any

from pydasa.dimensional.vaschy import Schema
from pydasa.workflows.influence import SensitivityAnalysis
from pydasa.workflows.phenomena import AnalysisEngine


def analyse_symbolic(
    engine: AnalysisEngine,
    schema: Schema,
    *,
    val_type: str = "mean",
    cat: str = "SYM",
    fwk: str = "CUSTOM",
    idx: int = 0,
    name: str = "sensitivity",
) -> dict[str, dict[str, float]]:
    """Run symbolic sensitivity analysis at a single value type.

    Args:
        engine: AnalysisEngine with variables and coefficients already populated.
        schema: the Schema used to build `engine`.
        val_type: one of `"mean"`, `"setpoint"`, `"min"`, `"max"` — value at
            which partial derivatives are evaluated.
        cat: sensitivity category; `"SYM"` for symbolic differentiation.
        fwk: framework name.
        idx: workflow index (informational).
        name: human-readable workflow name.

    Returns:
        Nested dict `{coefficient_symbol: {variable_symbol: sensitivity_value}}`
        over ALL coefficients (raw Pi-groups and derived). Non-numeric entries
        are filtered out.
    """
    _sens = SensitivityAnalysis(
        _idx=idx, _fwk=fwk, _schema=schema, _name=name, _cat=cat,
    )
    _sens.variables = engine.variables
    _sens.coefficients = engine.coefficients

    _raw = _sens.analyze_symbolic(val_type=val_type)

    _clean: dict[str, dict[str, float]] = {}
    for _coeff_sym, _var_map in _raw.items():
        _clean[_coeff_sym] = {
            _var_sym: float(_val)
            for _var_sym, _val in _var_map.items()
            if isinstance(_val, (int, float))
        }
    return _clean
