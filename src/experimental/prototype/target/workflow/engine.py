"""WorkflowEngine: drive one request through a `WorkflowSpec` (Weyns & Calinescu 2015 Fig. 1).

Picks the matching branch from the request `kind`, dispatches via the supplied `ServiceClient`, follows the `on_result` link when the first step completes, and returns `(body, status)` with a per-attempt audit trail.

Service selection is delegated to a picker callable, so adaptation strategies can swap the dispatch policy without touching the engine. Reliability-aware strategies receive feedback through an optional `picker.observe(svc_id, success)` hook.
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

ServicePicker = Callable[[str, str, ServiceCatalogue], list[ServiceCatalogueEntry]]


@dataclass(frozen=True)
class WorkflowStep:
    """Audit record for one atomic call attempt inside the workflow.

    Attributes:
        svc_id (str): concrete service id picked for this attempt (e.g. `MAS_{1}`).
        operation (str): logical operation name passed to the atomic.
        status (int): HTTP status returned (0 on transport error).
        send_ts (float): client-side timestamp before dispatch.
        recv_ts (float): client-side timestamp after the response arrived.
        c_used_at_start (int | None): in-flight count at the receiving service when admission succeeded; None on transport error.
        attempt (int): 1-indexed attempt number within the step. >1 means the first attempt failed and the picker fell through to the next candidate.
    """

    svc_id: str
    operation: str
    status: int
    send_ts: float
    recv_ts: float
    c_used_at_start: int | None
    attempt: int = 1


@dataclass
class WorkflowResult:
    """Engine output: final response body + status + per-step audit trail.

    Attributes:
        body (dict[str, Any]): final body returned to the composite caller.
        status (int): final HTTP status code.
        steps (list[WorkflowStep]): per-attempt audit entries (in execution order).
    """

    body: dict[str, Any]
    status: int
    steps: list[WorkflowStep] = field(default_factory=list)


def first_of_kind_picker(svc_kind: str,
                         operation: str,
                         catalogue: ServiceCatalogue) -> list[ServiceCatalogueEntry]:
    """Default picker: return a single-element list with the first catalogue entry of `svc_kind`.

    Used as the workflow engine's fallback when no strategy picker is supplied. The `operation` argument is part of the picker contract for parity with strategy pickers, but this default ignores it.

    Args:
        svc_kind (str): catalogue group.
        operation (str): logical operation name; ignored by this default.
        catalogue (ServiceCatalogue): loaded catalogue.

    Returns:
        list[ServiceCatalogueEntry]: single-element list with the first matching entry.

    Raises:
        LookupError: when the catalogue has no entry of that kind.
    """
    del operation
    _matches = catalogue.by_kind(svc_kind)
    if not _matches:
        _msg = (f"catalogue {catalogue.name!r} has no entry of kind {svc_kind!r}; "
                f"known kinds: {sorted({_e.kind for _e in catalogue.entries.values()})}")
        raise LookupError(_msg)
    _ans = [_matches[0]]
    return _ans


class WorkflowEngine:
    """Drive a request through a `WorkflowSpec` over a `ServiceCatalogue`.

    Attributes:
        spec (WorkflowSpec): branch graph + kind aliases.
        catalogue (ServiceCatalogue): concrete service entries.
        picker (ServicePicker): returns an ordered candidate chain for each step.
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
            tuple[dict[str, Any], int]: final body + HTTP status. The body is augmented with a `workflow.steps` list summarising every atomic call attempt.
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
            WorkflowResult: final body + status + per-attempt audit.

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
        """Try the picker's candidate chain in order; return the first success or the last failure.

        An attempt is "successful" when the HTTP status is 200 and the body has no `error` field. When the picker exposes `observe(svc_id, success)`, the engine feeds it after every attempt so reliability-aware strategies update their rolling windows. Every attempt is appended to `ans.steps` with its 1-indexed `attempt` number.

        Args:
            step (WorkflowStepSpec): step to execute.
            payload (dict[str, Any]): request body forwarded to the dispatched service.
            client (ServiceClient): dispatch client.
            ans (WorkflowResult): result accumulator; audit trail is mutated in place.

        Returns:
            tuple[dict[str, Any], int]: body and status from the last attempt. Status 0 (transport error) is rewritten to 502.
        """
        if step.svc_kind is None:
            _kind_hint = ""
        else:
            _kind_hint = step.svc_kind
        if step.svc_id is not None:
            _candidates: list[ServiceCatalogueEntry] = [
                self._lookup_or_synth(step.svc_id, _kind_hint),
            ]
        else:
            _candidates = self.picker(_kind_hint, step.operation, self.catalogue)
        _last_body: dict[str, Any] = {"error": "no_candidate",
                                      "detail": "picker returned empty list"}
        _last_status = 502
        _observe = getattr(self.picker, "observe", None)
        _done = False
        _idx = 0
        while _idx < len(_candidates) and not _done:
            _entry = _candidates[_idx]
            _attempt_idx = _idx + 1
            _send_ts = time.time()
            _body, _status = await client.invoke_operation(svc_name=_entry.svc_id,
                                                           operation=step.operation,
                                                           payload=payload)
            _recv_ts = time.time()
            _success = (_status == 200) and not (isinstance(_body, dict) and "error" in _body)
            if callable(_observe):
                _observe(_entry.svc_id, _success)
            _c_used = _read_c_used(_body)
            ans.steps.append(WorkflowStep(svc_id=_entry.svc_id,
                                          operation=step.operation,
                                          status=_status,
                                          send_ts=_send_ts,
                                          recv_ts=_recv_ts,
                                          c_used_at_start=_c_used,
                                          attempt=_attempt_idx))
            _last_body, _last_status = _body, _status
            if _success:
                _done = True
            _idx += 1
        if _last_status == 0:
            _status_out = 502
        else:
            _status_out = _last_status
        return _last_body, _status_out

    def _lookup_or_synth(self,
                         svc_id: str,
                         kind: str) -> ServiceCatalogueEntry:
        """Return the catalogue entry for `svc_id`, or synthesise one when it isn't in the catalogue.

        Internal-stage atomics (`TAS_{2..6}`) are not in the third-party catalogue but the engine still needs a `ServiceCatalogueEntry` to thread through `_dispatch`.

        Args:
            svc_id (str): catalogue key.
            kind (str): kind hint copied into the synthesised entry when needed.

        Returns:
            ServiceCatalogueEntry: real entry from the catalogue, or a minimal synthesised one.
        """
        try:
            _ans = self.catalogue.lookup(svc_id)
        except KeyError:
            _ans = ServiceCatalogueEntry(svc_id=svc_id, kind=kind)
        return _ans

    @staticmethod
    def _step_to_dict(step: WorkflowStep) -> dict[str, Any]:
        """Serialise a `WorkflowStep` to a plain dict for inclusion in the response body.

        Args:
            step (WorkflowStep): audit record for one attempt.

        Returns:
            dict[str, Any]: dict view of the record (all fields preserved as-is).
        """
        _ans: dict[str, Any] = {
            "svc_id": step.svc_id,
            "operation": step.operation,
            "status": step.status,
            "send_ts": step.send_ts,
            "recv_ts": step.recv_ts,
            "c_used_at_start": step.c_used_at_start,
            "attempt": step.attempt,
        }
        return _ans


def _read_c_used(body: dict[str, Any]) -> int | None:
    """Extract `c_used_at_start` from a response body, if present and integer-typed.

    Args:
        body (dict[str, Any]): atomic-service response body.

    Returns:
        int | None: the in-flight count when present and a real int; None otherwise.
    """
    _ans: int | None = None
    if isinstance(body, dict):
        _raw = body.get("c_used_at_start")
        if isinstance(_raw, int):
            _ans = _raw
    return _ans


__all__ = [
    "ServicePicker",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowStep",
    "first_of_kind_picker",
]
