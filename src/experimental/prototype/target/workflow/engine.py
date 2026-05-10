"""WorkflowEngine: drive one request through a `WorkflowSpec` (Weyns & Calinescu 2015 Fig. 1).

Takes one inbound payload, picks the matching branch, dispatches the `first` atomic call via the supplied `ServiceClient`, and (when the branch declares `on_result`) follows up with the matching second call. Returns `(body, status)` plus a per-step audit trail.

Service selection within a `svc_kind` step is delegated to a pluggable `picker` callable so adaptation strategies can replace the default first-of-kind behaviour without touching the engine. Status `0` from the client (transport error) is surfaced as `502` to the outer caller.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.experimental.prototype.target.service.catalogue import (
    ServiceCatalogue,
    ServiceCatalogueEntry,
)
from src.experimental.prototype.target.service.client import ServiceClient
from src.experimental.prototype.target.workflow.loader import (
    WorkflowSpec,
    WorkflowStepSpec,
)

ServicePicker = Callable[[str, ServiceCatalogue], ServiceCatalogueEntry]


@dataclass(frozen=True)
class WorkflowStep:
    """Audit record for one atomic call inside the workflow.

    Attributes:
        svc_id (str): concrete service id picked for this step (e.g. `MAS_{1}`).
        operation (str): logical operation name passed to the atomic.
        status (int): HTTP status returned (0 on transport error).
        send_ts (float): client-side timestamp before dispatch.
        recv_ts (float): client-side timestamp after the response arrived.
        c_used_at_start (int | None): in-flight count at the receiving service when admission succeeded; None on transport error.
    """

    svc_id: str
    operation: str
    status: int
    send_ts: float
    recv_ts: float
    c_used_at_start: int | None


@dataclass
class WorkflowResult:
    """Engine output: final response body + status + per-step audit trail.

    Attributes:
        body (dict[str, Any]): final body returned to the composite caller.
        status (int): final HTTP status code.
        steps (list[WorkflowStep]): per-step audit entries (in execution order).
    """

    body: dict[str, Any]
    status: int
    steps: list[WorkflowStep] = field(default_factory=list)


def first_of_kind_picker(svc_kind: str,
                         catalogue: ServiceCatalogue) -> ServiceCatalogueEntry:
    """Default service picker: return the first catalogue entry matching `svc_kind`.

    Args:
        svc_kind (str): catalogue group.
        catalogue (ServiceCatalogue): loaded catalogue.

    Returns:
        ServiceCatalogueEntry: the first matching entry.

    Raises:
        LookupError: when the catalogue has no entry of that kind.
    """
    _matches = catalogue.by_kind(svc_kind)
    if not _matches:
        _msg = (f"catalogue {catalogue.name!r} has no entry of kind {svc_kind!r}; "
                f"known kinds: {sorted({_e.kind for _e in catalogue.entries.values()})}")
        raise LookupError(_msg)
    _ans = _matches[0]
    return _ans


class WorkflowEngine:
    """Drive a request through a `WorkflowSpec` over a `ServiceCatalogue`.

    Attributes:
        spec (WorkflowSpec): branch graph + kind aliases.
        catalogue (ServiceCatalogue): concrete service entries.
        picker (ServicePicker): selects which concrete service of a kind to call.
    """

    def __init__(self,
                 *,
                 spec: WorkflowSpec,
                 catalogue: ServiceCatalogue,
                 picker: ServicePicker | None = None) -> None:
        """Wire the engine.

        Args:
            spec (WorkflowSpec): parsed workflow.
            catalogue (ServiceCatalogue): loaded catalogue.
            picker (ServicePicker | None, optional): override the default first-of-kind picker. Defaults to None.
        """
        self.spec = spec
        self.catalogue = catalogue
        if picker is None:
            self.picker = first_of_kind_picker
        else:
            self.picker = picker

    async def execute(self,
                      payload: dict[str, Any],
                      client: ServiceClient) -> tuple[dict[str, Any], int]:
        """Run the workflow for one inbound `payload` and return `(final_body, final_status)`.

        Args:
            payload (dict[str, Any]): inbound request body. Must include `kind`.
            client (ServiceClient): pre-opened dispatch client.

        Returns:
            tuple[dict[str, Any], int]: final body + HTTP status. The body is augmented with a `workflow.steps` list summarising every atomic call.
        """
        _result = await self.execute_full(payload=payload, client=client)
        _body_out = dict(_result.body)
        _steps_dump: list[dict[str, Any]] = []
        for _s in _result.steps:
            _steps_dump.append(self._step_to_dict(_s))
        _body_out["workflow"] = {"steps": _steps_dump}
        return _body_out, _result.status

    async def execute_full(self,
                           payload: dict[str, Any],
                           client: ServiceClient) -> WorkflowResult:
        """Run the workflow and return the typed `WorkflowResult` with the audit trail.

        Args:
            payload (dict[str, Any]): inbound request body.
            client (ServiceClient): dispatch client.

        Returns:
            WorkflowResult: final body + status + per-step audit.

        Raises:
            KeyError: if the request `kind` does not resolve to any branch.
        """
        _kind = str(payload.get("kind", ""))
        _branch = self.spec.branch_for(_kind)
        _ans = WorkflowResult(body={}, status=200)
        _first_body, _first_status = await self._dispatch(step=_branch.first,
                                                          payload=payload,
                                                          client=client,
                                                          ans=_ans)
        _ans.body = _first_body
        _ans.status = _first_status
        if _first_status != 200 or not _branch.on_result:
            return _ans
        _result_key = str(_first_body.get("result", ""))
        _next_step = _branch.on_result.get(_result_key)
        if _next_step is None:
            return _ans
        _next_body, _next_status = await self._dispatch(step=_next_step,
                                                        payload=payload,
                                                        client=client,
                                                        ans=_ans)
        _ans.body = _next_body
        _ans.status = _next_status
        return _ans

    async def _dispatch(self,
                        step: WorkflowStepSpec,
                        payload: dict[str, Any],
                        client: ServiceClient,
                        ans: WorkflowResult) -> tuple[dict[str, Any], int]:
        """Resolve the concrete service for `step`, dispatch over HTTP, append the audit entry.

        - `step.svc_kind` set: catalogue picker selects the concrete id (collapsed-mode dispatch).
        - `step.svc_id` set: direct cache lookup, no picker (expanded-mode dispatch to `TAS_{2..6}`).

        Args:
            step (WorkflowStepSpec): step to execute.
            payload (dict[str, Any]): request body forwarded to the dispatched service.
            client (ServiceClient): dispatch client.
            ans (WorkflowResult): result accumulator; audit trail is mutated in place.

        Returns:
            tuple[dict[str, Any], int]: body and status from the dispatched call. Status `0` is rewritten to `502`.
        """
        if step.svc_id is not None:
            _svc_id = step.svc_id
        else:
            _entry = self.picker(step.svc_kind, self.catalogue)  # type: ignore[arg-type]
            _svc_id = _entry.svc_id
        _send_ts = time.time()
        _body, _status = await client.invoke_operation(svc_name=_svc_id,
                                                       operation=step.operation,
                                                       payload=payload)
        _recv_ts = time.time()
        if isinstance(_body, dict):
            _c_used_raw = _body.get("c_used_at_start")
        else:
            _c_used_raw = None
        if isinstance(_c_used_raw, int):
            _c_used: int | None = _c_used_raw
        else:
            _c_used = None
        ans.steps.append(WorkflowStep(svc_id=_svc_id,
                                      operation=step.operation,
                                      status=_status,
                                      send_ts=_send_ts,
                                      recv_ts=_recv_ts,
                                      c_used_at_start=_c_used))
        if _status == 0:
            _status_out = 502
        else:
            _status_out = _status
        return _body, _status_out

    @staticmethod
    def _step_to_dict(step: WorkflowStep) -> dict[str, Any]:
        """Serialise a `WorkflowStep` for inclusion in the response body."""
        _ans: dict[str, Any] = {
            "svc_id": step.svc_id,
            "operation": step.operation,
            "status": step.status,
            "send_ts": step.send_ts,
            "recv_ts": step.recv_ts,
            "c_used_at_start": step.c_used_at_start,
        }
        return _ans


__all__ = [
    "ServicePicker",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStep",
    "first_of_kind_picker",
]
