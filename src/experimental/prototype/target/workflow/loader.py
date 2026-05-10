"""Parse `data/config/method/prototype/workflow/<name>.json` into a `WorkflowSpec`.

Schema:

    {
        "entry": "pickTask",
        "branches": {
            "vitalParamsMsg": {
            "first": {"svc_kind": "medical_analysis", "operation": "analyseData"},
            "on_result": {
                "changeDrug":  {"svc_kind": "drug",  "operation": "changeDrug"},
                "changeDose":  {"svc_kind": "drug",  "operation": "changeDose"},
                "sendAlarm":   {"svc_kind": "alarm", "operation": "sendAlarm"}
            }
            },
            "buttonMsg": {
            "first": {"svc_kind": "alarm", "operation": "triggerAlarm"}
            }
        }
    }

`first` is the initial atomic call; `on_result` (optional) maps the first call's `result` field to a follow-up atomic call. Each step targets either a catalogue `svc_kind` (engine resolves to a concrete service via the active strategy) or a concrete `svc_id` (cache lookup, no picker). Adaptation strategies can swap kind-side pickers without touching the spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DFLT_WORKFLOW_DIR = Path("data/config/method/prototype/workflow")
DFLT_WORKFLOW_NAME = "tas"


@dataclass(frozen=True)
class WorkflowStepSpec:
    """One atomic-dispatch step inside a workflow branch.

    Two mutually exclusive step-forms:

    - `svc_kind` step: the engine picks a concrete service from the catalogue (e.g. one of `MAS_{1..3}` for `medical_analysis`). Used in collapsed mode.
    - `svc_id` step: the engine looks up a specific service id in the cache (e.g. `TAS_{2}`). Used in expanded mode.

    Exactly one of `svc_kind` and `svc_id` must be set; the loader rejects steps that set both or neither.

    Attributes:
        operation (str): logical operation name passed to the dispatched service (e.g. `analyseData`).
        svc_kind (str | None): catalogue group; None when this step is `svc_id`-driven.
        svc_id (str | None): concrete service id; None when this step is `svc_kind`-driven.
    """

    operation: str
    svc_kind: str | None = None
    svc_id: str | None = None


@dataclass(frozen=True)
class BranchSpec:
    """One workflow branch, picked by the request's `kind`.

    Attributes:
        first (WorkflowStepSpec): initial atomic call.
        on_result (dict[str, WorkflowStepSpec]): follow-up atomic call keyed by the `result` field returned by `first`. Empty when the branch is single-step.
    """

    first: WorkflowStepSpec
    on_result: dict[str, WorkflowStepSpec] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowSpec:
    """Parsed `<name>.json` workflow specification.

    Attributes:
        entry (str): entry-point name (e.g. `pickTask`); informational, the engine routes by `kind`.
        branches (dict[str, BranchSpec]): branch keyed by request `kind` (e.g. `vitalParamsMsg`, `buttonMsg`).
        kind_aliases (dict[str, str]): optional map from request `kind` (e.g. `medical_analysis`) to branch key (`vitalParamsMsg`); identity when absent.
    """

    entry: str
    branches: dict[str, BranchSpec]
    kind_aliases: dict[str, str] = field(default_factory=dict)

    def branch_for(self, kind: str) -> BranchSpec:
        """Resolve a request `kind` to its `BranchSpec` (applying aliases if present).

        Args:
            kind (str): the request `kind` (e.g. `medical_analysis`, `vitalParamsMsg`).

        Returns:
            BranchSpec: matching branch.

        Raises:
            KeyError: when the resolved key is not in `branches`.
        """
        _key = self.kind_aliases.get(kind, kind)
        try:
            _ans = self.branches[_key]
        except KeyError as _err:
            _msg = (f"workflow has no branch for kind {kind!r} "
                    f"(resolved to {_key!r}); known: {list(self.branches)}")
            raise KeyError(_msg) from _err
        return _ans


def load_workflow(name: str = DFLT_WORKFLOW_NAME,
                  *,
                  base_dir: Path | None = None) -> WorkflowSpec:
    """Load `<base_dir>/<name>.json` into a `WorkflowSpec`.

    Args:
        name (str, optional): workflow stem. Defaults to `tas`.
        base_dir (Path | None, optional): override the workflow directory (tests). Defaults to `DFLT_WORKFLOW_DIR`.

    Returns:
        WorkflowSpec: parsed spec.

    Raises:
        FileNotFoundError: if the workflow file does not exist.
        ValueError: if the JSON is missing required keys or has a malformed branch.
    """
    if base_dir is None:
        _base = DFLT_WORKFLOW_DIR
    else:
        _base = base_dir
    _path = _base / f"{name}.json"
    if not _path.exists():
        _msg = f"workflow file not found: {_path}"
        raise FileNotFoundError(_msg)
    with _path.open(encoding="utf-8") as _fh:
        _doc = json.load(_fh)
    _ans = _parse_workflow(name, _doc)
    return _ans


def _parse_workflow(name: str, doc: dict[str, object]) -> WorkflowSpec:
    """Validate the parsed JSON shape and build the typed spec.

    Args:
        name (str): workflow stem (for error messages).
        doc (dict): parsed JSON content.

    Returns:
        WorkflowSpec: typed spec.

    Raises:
        ValueError: when the document lacks `entry` or `branches`, or a branch is malformed.
    """
    if "entry" not in doc:
        _msg = f"workflow {name!r}: missing required key 'entry'"
        raise ValueError(_msg)
    _branches_raw = doc.get("branches")
    if not isinstance(_branches_raw, dict):
        _msg = f"workflow {name!r}: top-level 'branches' object is required"
        raise ValueError(_msg)
    _branches: dict[str, BranchSpec] = {}
    for _key, _branch in _branches_raw.items():
        if not isinstance(_branch, dict):
            _msg = (f"workflow {name!r}: branch {_key!r} must be an object, "
                    f"got {type(_branch).__name__}")
            raise ValueError(_msg)
        _branches[_key] = _build_branch(name, _key, _branch)
    _aliases_raw = doc.get("kind_aliases", {})
    if not isinstance(_aliases_raw, dict):
        _msg = f"workflow {name!r}: 'kind_aliases' must be an object when present"
        raise ValueError(_msg)
    _aliases = {str(_k): str(_v) for _k, _v in _aliases_raw.items()}
    _ans = WorkflowSpec(entry=str(doc["entry"]),
                        branches=_branches,
                        kind_aliases=_aliases)
    return _ans


def _build_branch(workflow_name: str,
                  branch_key: str,
                  branch: dict[str, object]) -> BranchSpec:
    """Build one `BranchSpec` from a JSON branch dict.

    Args:
        workflow_name (str): owning workflow (for error messages).
        branch_key (str): branch identifier.
        branch (dict): branch contents.

    Returns:
        BranchSpec: typed branch.

    Raises:
        ValueError: if `first` is missing or `on_result` is malformed.
    """
    _first_raw = branch.get("first")
    if not isinstance(_first_raw, dict):
        _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}: "
                f"'first' must be an object")
        raise ValueError(_msg)
    _first = _build_step(workflow_name, branch_key, "first", _first_raw)
    _on_result_raw = branch.get("on_result", {})
    if not isinstance(_on_result_raw, dict):
        _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}: "
                f"'on_result' must be an object when present")
        raise ValueError(_msg)
    _on_result: dict[str, WorkflowStepSpec] = {}
    for _result_key, _step_raw in _on_result_raw.items():
        if not isinstance(_step_raw, dict):
            _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}: "
                    f"on_result[{_result_key!r}] must be an object")
            raise ValueError(_msg)
        _on_result[_result_key] = _build_step(workflow_name,
                                              branch_key,
                                              f"on_result[{_result_key!r}]",
                                              _step_raw)
    _ans = BranchSpec(first=_first, on_result=_on_result)
    return _ans


def _build_step(workflow_name: str,
                branch_key: str,
                step_label: str,
                step: dict[str, object]) -> WorkflowStepSpec:
    """Build one `WorkflowStepSpec` from a JSON step dict.

    Args:
        workflow_name (str): owning workflow (for error messages).
        branch_key (str): owning branch.
        step_label (str): step identifier (`first` / `on_result[...]`).
        step (dict): step contents.

    Returns:
        WorkflowStepSpec: typed step.

    Raises:
        ValueError: if `operation` is missing, if neither `svc_kind` nor `svc_id` is set, or if both are set.
    """
    if "operation" not in step:
        _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}, "
                f"step {step_label}: missing required key 'operation'")
        raise ValueError(_msg)
    _has_kind = "svc_kind" in step
    _has_id = "svc_id" in step
    if _has_kind and _has_id:
        _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}, "
                f"step {step_label}: exactly one of 'svc_kind' / 'svc_id' "
                f"must be set, not both")
        raise ValueError(_msg)
    if not _has_kind and not _has_id:
        _msg = (f"workflow {workflow_name!r}, branch {branch_key!r}, "
                f"step {step_label}: exactly one of 'svc_kind' / 'svc_id' "
                f"must be set, neither is")
        raise ValueError(_msg)
    if _has_kind:
        _ans = WorkflowStepSpec(operation=str(step["operation"]),
                                svc_kind=str(step["svc_kind"]))
    else:
        _ans = WorkflowStepSpec(operation=str(step["operation"]),
                                svc_id=str(step["svc_id"]))
    return _ans


__all__ = [
    "DFLT_WORKFLOW_DIR",
    "DFLT_WORKFLOW_NAME",
    "BranchSpec",
    "WorkflowSpec",
    "WorkflowStepSpec",
    "load_workflow",
]
