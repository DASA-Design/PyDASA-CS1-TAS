"""CompositeService: workflow-driven orchestrator over atomic services (Weyns & Calinescu 2015 Fig. 2).

Sibling of `AtomicService` under `AbstractService`. Holds the workflow engine and the `ServiceClient` used to dispatch atomic calls, and exposes `invoke_composite_service(payload)` as the single entry point a composite-app route binds to. The workflow engine drives orchestration; subclasses override nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.experimental.prototype.target.service.abstract import AbstractService
from src.experimental.prototype.target.service.client import ServiceClient

if TYPE_CHECKING:
    from src.experimental.prototype.target.workflow.engine import WorkflowEngine


class CompositeService(AbstractService):
    """Workflow-driven orchestrating service.

    Attributes:
        service_name (str): composite identifier (e.g. `TAS`).
        workflow (WorkflowEngine): drives the per-request branch decisions.
        client (ServiceClient): used to dispatch atomic calls.
    """

    def __init__(self,
                 *,
                 service_name: str,
                 workflow: WorkflowEngine,
                 client: ServiceClient) -> None:
        """Wire the composite around its workflow and dispatch client.

        Args:
            service_name (str): composite identifier (e.g. `TAS`).
            workflow (WorkflowEngine): engine built from `data/config/method/prototype/workflow/<name>.json`.
            client (ServiceClient): pre-built (already entered as async-context) client used for atomic dispatch.
        """
        super().__init__(service_name=service_name)
        self.workflow = workflow
        self.client = client

    async def invoke_operation(self,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Hand the payload to the workflow engine and surface its `(body, status)`.

        Args:
            payload (dict[str, Any]): request body; must include `kind` so the engine can pick a branch.

        Returns:
            tuple[dict[str, Any], int]: workflow result body + HTTP status code.
        """
        _body, _status = await self.workflow.execute(payload=payload, client=self.client)
        return _body, _status

    async def invoke_composite_service(self,
                                       payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Fig. 2 alias for `invoke_operation`; preserved for paper-aligned callers."""
        _ans = await self.invoke_operation(payload)
        return _ans


__all__ = [
    "CompositeService",
]
