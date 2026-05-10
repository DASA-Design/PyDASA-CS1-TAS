"""FastAPI app factories that mount the published service classes onto the runtime.

- `failure.py`: per-request failure dispatcher (timeout / drop / 5xx) shared across factories.
- `healthz.py`: GET `/healthz` registration helper.
- `third_party.py`: build one FastAPI app per third-party atomic (`MAS_*`, `AS_*`, `DS_*`).
- `internal_stage.py`: build one FastAPI app per internal-stage atomic (`TAS_{2..6}`) used in expanded mode.
- `tas.py`: build the composite TAS app that drives the workflow over a `ServiceClient`.

All factories are top-level + zero-arg (after `functools.partial` binding) so they pickle across `multiprocessing.spawn` on Windows.
"""

from src.experimental.prototype.target.factory.failure import (
    apply_inject_failure,
    drop_request,
    fivexx_request,
    timeout_request,
)
from src.experimental.prototype.target.factory.healthz import (
    HEALTHZ_BODY,
    add_healthz_route,
)
from src.experimental.prototype.target.factory.internal_stage import (
    TasInternalAtomic,
    build_internal_stage_fastapi_app,
)
from src.experimental.prototype.target.factory.tas import build_tas_fastapi_app
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)

__all__ = [
    "HEALTHZ_BODY",
    "TasInternalAtomic",
    "add_healthz_route",
    "apply_inject_failure",
    "build_atomic_fastapi_app",
    "build_internal_stage_fastapi_app",
    "build_tas_fastapi_app",
    "drop_request",
    "fivexx_request",
    "timeout_request",
]
