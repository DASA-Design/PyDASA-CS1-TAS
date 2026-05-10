"""Tests for `src.experimental.prototype.target.workflow.engine`.

**TestWorkflowEngine**:

- `test_button_one_step`: a `KIND_ALARM` request triggers one alarm dispatch and the engine returns `(body, 200)`.
- `test_vital_two_steps`: a `KIND_MED_ANSYS` request triggers `analyseData` then the on_result follow-up; both steps appear in the audit trail.
- `test_unknown_kind`: an unrecognised `kind` raises `KeyError` from `branch_for`.
- `test_status_zero_to_502`: a transport error from the client (status 0) is rewritten to 502 in the engine output.
- `test_picker_no_match`: the default picker raises `LookupError` when the catalogue has no entry of the requested kind.
- `test_svc_id_skips_picker`: a step with `svc_id` set dispatches by id directly.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.experimental.prototype.target.service.catalogue import (
    ServiceCatalogue,
    ServiceCatalogueEntry,
)
from src.experimental.prototype.target.workflow.engine import (
    WorkflowEngine,
    first_of_kind_picker,
)
from src.experimental.prototype.target.workflow.loader import (
    BranchSpec,
    WorkflowSpec,
    WorkflowStepSpec,
)


def _build_catalogue() -> ServiceCatalogue:
    """Two-entry catalogue with one alarm + one medical_analysis service."""
    _entries = {
        "AS_{1}": ServiceCatalogueEntry(svc_id="AS_{1}", kind="alarm"),
        "MAS_{1}": ServiceCatalogueEntry(svc_id="MAS_{1}", kind="medical_analysis"),
    }
    _ctlg = ServiceCatalogue(name="test_cat", source="", entries=_entries)
    return _ctlg


def _build_spec() -> WorkflowSpec:
    """Workflow spec exercising the alarm branch + the medical_analysis on_result follow-up."""
    _wf = WorkflowSpec(
        entry="pickTask",
        branches={
            "buttonMsg": BranchSpec(
                first=WorkflowStepSpec(
                    svc_kind="alarm", operation="triggerAlarm"),
            ),
            "vitalParamsMsg": BranchSpec(
                first=WorkflowStepSpec(svc_kind="medical_analysis",
                                       operation="analyseData"),
                on_result={
                    "sendAlarm": WorkflowStepSpec(svc_kind="alarm",
                                                  operation="sendAlarm"),
                },
            ),
        },
        kind_aliases={"alarm": "buttonMsg",
                      "medical_analysis": "vitalParamsMsg"},
    )
    return _wf


class _StubClient:
    """Stand-in client that records every dispatch and returns a scripted reply."""

    def __init__(self, replies: dict[str, tuple[dict[str, Any], int]]) -> None:
        self._replies = replies
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke_operation(self,
                               svc_name: str,
                               operation: str,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        self.calls.append((svc_name, operation, dict(payload)))
        _key = svc_name
        return self._replies.get(_key, ({}, 200))


class TestWorkflowEngine:
    """Drive the engine over stubbed catalogue + client."""

    @pytest.mark.asyncio
    async def test_button_one_step(self) -> None:
        """*test_button_one_step()* a `kind='alarm'` request runs one alarm dispatch and returns `(body, 200)`."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={"AS_{1}": ({"ok": True}, 200)})
        _td = {"kind": "alarm", "req_id": "r0"}
        _body, _status = await _eng.execute(payload=_td,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        assert _body["workflow"]["steps"][0]["svc_id"] == "AS_{1}"
        assert len(_stub.calls) == 1

    @pytest.mark.asyncio
    async def test_vital_two_steps(self) -> None:
        """*test_vital_two_steps()* a `kind='medical_analysis'` request that returns `result='sendAlarm'` triggers a follow-up alarm dispatch."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={
            "MAS_{1}": ({"result": "sendAlarm"}, 200),
            "AS_{1}": ({"ok": True}, 200),
        })
        _td = {"kind": "medical_analysis", "req_id": "r1"}
        _body, _status = await _eng.execute(payload=_td,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        _step_ids = [_s["svc_id"] for _s in _body["workflow"]["steps"]]
        assert _step_ids == ["MAS_{1}", "AS_{1}"]

    @pytest.mark.asyncio
    async def test_unknown_kind(self) -> None:
        """*test_unknown_kind()* an unrecognised `kind` propagates `KeyError` from `branch_for`."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={})
        with pytest.raises(KeyError):
            _td = {"kind": "nope", "req_id": "r2"}
            await _eng.execute(payload=_td,
                               client=_stub)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_status_zero_to_502(self) -> None:
        """*test_status_zero_to_502()* a transport-error reply (`status=0`) from the client is rewritten to 502 in the engine output."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={"AS_{1}": ({"error": "drop"}, 0)})
        _td = {"kind": "alarm", "req_id": "r3"}
        _body, _status = await _eng.execute(payload=_td,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 502
        assert _body["workflow"]["steps"][0]["status"] == 0

    def test_picker_no_match(self) -> None:
        """*test_picker_no_match()* a kind absent from the catalogue raises `LookupError`."""
        _cat = _build_catalogue()
        with pytest.raises(LookupError):
            first_of_kind_picker("drug", _cat)

    @pytest.mark.asyncio
    async def test_svc_id_skips_picker(self) -> None:
        """*test_svc_id_skips_picker()* a step with `svc_id` set dispatches by id directly; the catalogue picker is not consulted."""
        _spec = WorkflowSpec(
            entry="pickTask",
            branches={
                "vitalParamsMsg": BranchSpec(
                    first=WorkflowStepSpec(operation="forward", svc_id="TAS_{2}"),
                ),
            },
            kind_aliases={"medical_analysis": "vitalParamsMsg"},
        )
        _eng = WorkflowEngine(spec=_spec, catalogue=_build_catalogue())
        _stub = _StubClient(replies={"TAS_{2}": ({"ok": True}, 200)})
        _td = {"kind": "medical_analysis", "req_id": "r9"}
        _body, _status = await _eng.execute(payload=_td,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        assert _stub.calls[0][0] == "TAS_{2}"
        assert _body["workflow"]["steps"][0]["svc_id"] == "TAS_{2}"
