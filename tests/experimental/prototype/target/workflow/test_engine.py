"""Tests for `src.experimental.prototype.target.workflow.engine`.

**TestWorkflowEngine**:

- `test_button_one_step`: a `kind='alarm'` request runs one alarm dispatch and returns `(body, 200)`.
- `test_vital_two_steps`: a `kind='medical_analysis'` request triggers `analyseData` then the on_result follow-up; both steps appear in the audit trail.
- `test_unknown_kind`: an unrecognised `kind` raises `KeyError` from `branch_for`.
- `test_status_zero_to_502`: a transport error from the client (status 0) is rewritten to 502.
- `test_picker_no_match`: the default picker raises `LookupError` when the catalogue has no entry of the requested kind.
- `test_retry_on_failure`: a picker returning `[A, B]` retries on B when A fails; both attempts land in the audit trail with `attempt=1, 2`.
- `test_observe_called`: a picker exposing `observe(svc_id, success)` is called per attempt.
- `test_all_fail`: when every candidate fails, the last response is returned verbatim with status 502.
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
    """Two-entry catalogue with one alarm + one medical_analysis service.

    Returns:
        ServiceCatalogue: fixture used across the engine tests.
    """
    _entries = {
        "AS_{1}": ServiceCatalogueEntry(svc_id="AS_{1}", kind="alarm"),
        "MAS_{1}": ServiceCatalogueEntry(svc_id="MAS_{1}", kind="medical_analysis"),
    }
    _ctlg = ServiceCatalogue(name="test_cat", source="", entries=_entries)
    return _ctlg


def _build_spec() -> WorkflowSpec:
    """Workflow spec exercising both the alarm branch and the medical_analysis on_result follow-up.

    Returns:
        WorkflowSpec: fixture used across the engine tests.
    """
    _wf = WorkflowSpec(
        entry="pickTask",
        branches={
            "buttonMsg": BranchSpec(
                first=WorkflowStepSpec(
                    svc_kind="alarm",
                    operation="triggerAlarm",
                ),
            ),
            "vitalParamsMsg": BranchSpec(
                first=WorkflowStepSpec(
                    svc_kind="medical_analysis",
                    operation="analyseData",
                ),
                on_result={
                    "sendAlarm": WorkflowStepSpec(
                        svc_kind="alarm",
                        operation="sendAlarm",
                    ),
                },
            ),
        },
        kind_aliases={
            "alarm": "buttonMsg",
            "medical_analysis": "vitalParamsMsg",
        },
    )
    return _wf


class _StubClient:
    """Stand-in client that records every dispatch and returns a scripted reply.

    Attributes:
        calls (list[tuple[str, str, dict]]): every `(svc_name, operation, payload)` seen.
    """

    def __init__(self, replies: dict[str, tuple[dict[str, Any], int]]) -> None:
        """Configure the stub.

        Args:
            replies (dict): map `svc_name -> (body, status)` to return on dispatch. Missing names default to `({}, 200)`.
        """
        self._replies = replies
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def invoke_operation(self,
                               svc_name: str,
                               operation: str,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Record the call and return the scripted reply (or default 200).

        Args:
            svc_name (str): catalogue id of the target service.
            operation (str): logical operation name.
            payload (dict[str, Any]): request body.

        Returns:
            tuple[dict[str, Any], int]: scripted reply.
        """
        self.calls.append((svc_name, operation, dict(payload)))
        return self._replies.get(svc_name, ({}, 200))


class _ChainPicker:
    """Picker that returns a hard-coded chain per kind. Module-scope test helper.

    Attributes:
        chains_by_kind (dict[str, list[ServiceCatalogueEntry]]): chain to return per kind.
    """

    def __init__(self,
                 chains_by_kind: dict[str, list[ServiceCatalogueEntry]]) -> None:
        """Configure the picker.

        Args:
            chains_by_kind (dict): kind -> ordered candidate chain.
        """
        self._chains_by_kind = chains_by_kind

    def __call__(self,
                 svc_kind: str,
                 operation: str,
                 catalogue: Any) -> list[ServiceCatalogueEntry]:
        """Return the configured chain for `svc_kind`; empty list when missing."""
        del operation, catalogue
        return list(self._chains_by_kind.get(svc_kind, []))


class _ObservingPicker(_ChainPicker):
    """Chain picker plus an `observe(svc_id, success)` callback recording calls. Module-scope test helper.

    Attributes:
        observed (list[tuple[str, bool]]): every `(svc_id, success)` seen.
    """

    def __init__(self,
                 chains_by_kind: dict[str, list[ServiceCatalogueEntry]]) -> None:
        """Configure the picker.

        Args:
            chains_by_kind (dict): kind -> ordered candidate chain.
        """
        super().__init__(chains_by_kind)
        self.observed: list[tuple[str, bool]] = []

    def observe(self, svc_id: str, success: bool) -> None:
        """Record one attempt outcome.

        Args:
            svc_id (str): id of the service that handled the attempt.
            success (bool): True when the attempt returned 2xx with no error body.
        """
        self.observed.append((svc_id, success))


class TestWorkflowEngine:
    """Drive the engine over stubbed catalogue + client."""

    @pytest.mark.asyncio
    async def test_button_one_step(self) -> None:
        """*test_button_one_step()* a `kind='alarm'` request runs one alarm dispatch and returns `(body, 200)`."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={"AS_{1}": ({"ok": True}, 200)})
        _payload = {"kind": "alarm", "req_id": "r0"}
        _body, _status = await _eng.execute(payload=_payload,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        assert _body["workflow"]["steps"][0]["svc_id"] == "AS_{1}"
        assert len(_stub.calls) == 1

    @pytest.mark.asyncio
    async def test_vital_two_steps(self) -> None:
        """*test_vital_two_steps()* a `kind='medical_analysis'` request with `result='sendAlarm'` triggers a follow-up alarm dispatch."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={
            "MAS_{1}": ({"result": "sendAlarm"}, 200),
            "AS_{1}": ({"ok": True}, 200),
        })
        _payload = {"kind": "medical_analysis", "req_id": "r1"}
        _body, _status = await _eng.execute(payload=_payload,
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
            _payload = {"kind": "nope", "req_id": "r2"}
            await _eng.execute(payload=_payload,
                               client=_stub)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_status_zero_to_502(self) -> None:
        """*test_status_zero_to_502()* a transport-error reply (`status=0`) is rewritten to 502."""
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_build_catalogue())
        _stub = _StubClient(replies={"AS_{1}": ({"error": "drop"}, 0)})
        _payload = {"kind": "alarm", "req_id": "r3"}
        _body, _status = await _eng.execute(payload=_payload,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 502
        assert _body["workflow"]["steps"][0]["status"] == 0

    def test_picker_no_match(self) -> None:
        """*test_picker_no_match()* a kind absent from the catalogue raises `LookupError`."""
        _cat = _build_catalogue()
        with pytest.raises(LookupError):
            first_of_kind_picker("drug", "changeDrug", _cat)

    @pytest.mark.asyncio
    async def test_retry_on_failure(self) -> None:
        """*test_retry_on_failure()* a picker returning `[A, B]` retries on B when A fails; both attempts in the audit trail with `attempt=1, 2`."""
        _cat = _build_catalogue()
        _picker = _ChainPicker({
            "alarm": [
                _cat.entries["AS_{1}"],
                ServiceCatalogueEntry(svc_id="AS_{2}", kind="alarm"),
            ],
        })
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_cat, picker=_picker)
        _stub = _StubClient(replies={
            "AS_{1}": ({"error": "drop"}, 502),
            "AS_{2}": ({"ok": True}, 200),
        })
        _payload = {"kind": "alarm", "req_id": "r5"}
        _body, _status = await _eng.execute(payload=_payload,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        _steps = _body["workflow"]["steps"]
        assert [_s["svc_id"] for _s in _steps] == ["AS_{1}", "AS_{2}"]
        assert [_s["attempt"] for _s in _steps] == [1, 2]

    @pytest.mark.asyncio
    async def test_observe_called(self) -> None:
        """*test_observe_called()* the engine calls `picker.observe(svc_id, success)` after each attempt."""
        _cat = _build_catalogue()
        _picker = _ObservingPicker({"alarm": [_cat.entries["AS_{1}"]]})
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_cat, picker=_picker)
        _stub = _StubClient(replies={"AS_{1}": ({"ok": True}, 200)})
        _payload = {"kind": "alarm", "req_id": "r6"}
        await _eng.execute(payload=_payload,
                           client=_stub)  # type: ignore[arg-type]
        assert _picker.observed == [("AS_{1}", True)]

    @pytest.mark.asyncio
    async def test_all_fail(self) -> None:
        """*test_all_fail()* every candidate failing returns the last response verbatim; transport error becomes 502."""
        _cat = _build_catalogue()
        _picker = _ChainPicker({"alarm": [_cat.entries["AS_{1}"]]})
        _eng = WorkflowEngine(spec=_build_spec(), catalogue=_cat, picker=_picker)
        _stub = _StubClient(replies={"AS_{1}": ({"error": "drop"}, 0)})
        _payload = {"kind": "alarm", "req_id": "r7"}
        _body, _status = await _eng.execute(payload=_payload,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 502
        assert _body["error"] == "drop"

    @pytest.mark.asyncio
    async def test_svc_id_skips_picker(self) -> None:
        """*test_svc_id_skips_picker()* a step with `svc_id` set dispatches by id directly; the picker is not consulted."""
        _spec = WorkflowSpec(
            entry="pickTask",
            branches={
                "vitalParamsMsg": BranchSpec(
                    first=WorkflowStepSpec(
                        operation="forward",
                        svc_id="TAS_{2}",
                    ),
                ),
            },
            kind_aliases={"medical_analysis": "vitalParamsMsg"},
        )
        _eng = WorkflowEngine(spec=_spec, catalogue=_build_catalogue())
        _stub = _StubClient(replies={"TAS_{2}": ({"ok": True}, 200)})
        _payload = {"kind": "medical_analysis", "req_id": "r9"}
        _body, _status = await _eng.execute(payload=_payload,
                                            client=_stub)  # type: ignore[arg-type]
        assert _status == 200
        assert _stub.calls[0][0] == "TAS_{2}"
        assert _body["workflow"]["steps"][0]["svc_id"] == "TAS_{2}"
