"""Tests for `src.experimental.prototype.target.workflow.loader`.

**TestWorkflowLoader**:

- `test_load_tas_default`: loading `tas.json` from the default dir yields the two branches keyed by aliases (svc_kind step-form).
- `test_load_tas_expanded`: loading `tas_expanded.json` yields the same branches but with svc_id step-form pointing at TAS_{2..6}.
- `test_alias_resolves`: `branch_for('medical_analysis')` resolves via `kind_aliases` to `vitalParamsMsg`.
- `test_unknown_kind`: an unknown kind raises `KeyError`.
- `test_no_branches`: a JSON without `branches` raises `ValueError`.
- `test_no_operation`: a step without `operation` raises `ValueError`.
- `test_step_neither`: a step with neither `svc_kind` nor `svc_id` raises `ValueError`.
- `test_step_both`: a step with both `svc_kind` and `svc_id` raises `ValueError`.
- `test_step_id_only`: a step with `svc_id` set parses successfully; the resulting `WorkflowStepSpec.svc_id` is set and `svc_kind` is None.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experimental.prototype.target.workflow.loader import (
    DFLT_WORKFLOW_NAME,
    load_workflow,
)


class TestWorkflowLoader:
    """`WorkflowSpec` loader."""

    def test_load_tas_default(self) -> None:
        """*test_load_tas_default()* default-dir load returns spec with both `vitalParamsMsg` and `buttonMsg` branches."""
        _spec = load_workflow(DFLT_WORKFLOW_NAME)
        assert _spec.entry == "pickTask"
        assert "vitalParamsMsg" in _spec.branches
        assert "buttonMsg" in _spec.branches

    def test_alias_resolves(self) -> None:
        """*test_alias_resolves()* `branch_for('medical_analysis')` resolves via `kind_aliases` to `vitalParamsMsg`."""
        _spec = load_workflow(DFLT_WORKFLOW_NAME)
        _branch = _spec.branch_for("medical_analysis")
        assert _branch.first.svc_kind == "medical_analysis"
        assert _branch.first.operation == "analyseData"

    def test_unknown_kind(self) -> None:
        """*test_unknown_kind()* an unknown kind raises `KeyError`."""
        _spec = load_workflow(DFLT_WORKFLOW_NAME)
        with pytest.raises(KeyError):
            _spec.branch_for("nope")

    def test_no_branches(self, tmp_path: Path) -> None:
        """*test_no_branches()* a JSON without `branches` raises `ValueError`."""
        (tmp_path / "bad.json").write_text(json.dumps({"entry": "x"}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_workflow("bad", base_dir=tmp_path)

    def test_load_tas_expanded(self) -> None:
        """*test_load_tas_expanded()* `tas_expanded.json` parses; vitalParamsMsg.first uses svc_id=TAS_{2}."""
        _spec = load_workflow("tas_expanded")
        _branch = _spec.branch_for("medical_analysis")
        assert _branch.first.svc_id == "TAS_{2}"
        assert _branch.first.svc_kind is None
        assert _branch.first.operation == "analyseData"
        assert _branch.on_result["changeDrug"].svc_id == "TAS_{5}"
        assert _branch.on_result["sendAlarm"].svc_id == "TAS_{4}"

    def test_no_operation(self, tmp_path: Path) -> None:
        """*test_no_operation()* a step without `operation` raises `ValueError`."""
        _doc = {
            "entry": "x",
            "branches": {
                "vitalParamsMsg": {
                    "first": {"svc_kind": "alarm"},
                },
            },
        }
        (tmp_path / "bad.json").write_text(json.dumps(_doc), encoding="utf-8")
        with pytest.raises(ValueError, match="operation"):
            load_workflow("bad", base_dir=tmp_path)

    def test_step_neither(self, tmp_path: Path) -> None:
        """*test_step_neither()* a step with neither `svc_kind` nor `svc_id` raises `ValueError`."""
        _doc = {
            "entry": "x",
            "branches": {
                "vitalParamsMsg": {
                    "first": {"operation": "go"},
                },
            },
        }
        (tmp_path / "bad.json").write_text(json.dumps(_doc), encoding="utf-8")
        with pytest.raises(ValueError, match="svc_kind"):
            load_workflow("bad", base_dir=tmp_path)

    def test_step_both(self, tmp_path: Path) -> None:
        """*test_step_both()* a step with both `svc_kind` and `svc_id` raises `ValueError`."""
        _doc = {
            "entry": "x",
            "branches": {
                "vitalParamsMsg": {
                    "first": {"operation": "go", "svc_kind": "alarm", "svc_id": "TAS_{3}"},
                },
            },
        }
        (tmp_path / "bad.json").write_text(json.dumps(_doc), encoding="utf-8")
        with pytest.raises(ValueError, match="not both"):
            load_workflow("bad", base_dir=tmp_path)

    def test_step_id_only(self, tmp_path: Path) -> None:
        """*test_step_id_only()* a step with `svc_id` parses cleanly; resulting spec has `svc_id` set, `svc_kind` None."""
        _doc = {
            "entry": "x",
            "branches": {
                "vitalParamsMsg": {
                    "first": {"operation": "go", "svc_id": "TAS_{3}"},
                },
            },
        }
        (tmp_path / "ok.json").write_text(json.dumps(_doc), encoding="utf-8")
        _spec = load_workflow("ok", base_dir=tmp_path)
        _step = _spec.branch_for("vitalParamsMsg").first
        assert _step.svc_id == "TAS_{3}"
        assert _step.svc_kind is None
        assert _step.operation == "go"
