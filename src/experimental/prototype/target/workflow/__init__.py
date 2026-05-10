"""Workflow layer for the composite TAS service.

- `loader.py`: parses `data/config/method/prototype/workflow/<name>.json` into a `WorkflowSpec`.
- `engine.py`: walks the spec for one request, dispatching atomic calls via a `ServiceClient`.

`CompositeService` owns one engine and consults it at every branch decision.
"""

from src.experimental.prototype.target.workflow.engine import (
    WorkflowEngine,
    WorkflowResult,
    WorkflowStep,
)
from src.experimental.prototype.target.workflow.loader import (
    DFLT_WORKFLOW_DIR,
    DFLT_WORKFLOW_NAME,
    BranchSpec,
    WorkflowSpec,
    load_workflow,
)

__all__ = [
    "DFLT_WORKFLOW_DIR",
    "DFLT_WORKFLOW_NAME",
    "BranchSpec",
    "WorkflowEngine",
    "WorkflowResult",
    "WorkflowSpec",
    "WorkflowStep",
    "load_workflow",
]
