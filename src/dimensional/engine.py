"""Per-artifact PyDASA AnalysisEngine construction for the TAS case study."""

from __future__ import annotations

from typing import Any

from pydasa.dimensional.vaschy import Schema
from pydasa.elements.parameter import Variable
from pydasa.workflows.phenomena import AnalysisEngine


def build_engine(
    artifact_key: str,
    artifact_vars: dict[str, dict[str, Any]],
    schema: Schema,
    *,
    fwk: str = "CUSTOM",
    idx: int = 0,
) -> AnalysisEngine:
    """Build and configure an AnalysisEngine for one TAS artifact.

    Args:
        artifact_key: artifact identifier in LaTeX subscript form, e.g.
            `"TAS_{1}"`. Used in the engine name / description.
        artifact_vars: dict of variable dicts from the PACS envelope
            (`config["artifacts"][artifact_key]["vars"]`). Each value must
            match `Variable(**params)` signature.
        schema: pre-built Schema (see `build_schema`).
        fwk: framework name; must match the Schema's `_fwk`.
        idx: engine index (informational).

    Returns:
        An `AnalysisEngine` with `engine.variables` already assigned.
        Call `engine.run_analysis()` to derive Pi-groups.
    """
    _variables = {sym: Variable(**params) for sym, params in artifact_vars.items()}

    _engine = AnalysisEngine(
        _idx=idx,
        _fwk=fwk,
        _schema=schema,
        _name=f"TAS {artifact_key} dimensional analysis",
        description=(
            f"Dimensional analysis for artifact {artifact_key} "
            "(M/M/c/K queueing node)."
        ),
    )
    _engine.variables = _variables
    return _engine
