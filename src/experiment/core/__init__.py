"""Generic queueing primitives — framework-agnostic.

No FastAPI, no httpx. Unit-testable in isolation from the HTTP stack.

    - `ServiceSpec`, `derive_seed` — immutable knobs + deterministic per-component seed derivation (`core/spec.py`).
    - `AtomicQueue` — one M/M/c/K primitive (`core/atomic.py`).
    - `CompositeQueue` — container of atomic queues + internal routing (`core/composite.py`).
    - `run_instrumented`, `@instrumented`, `LOG_COLUMNS`, `ServiceRequest`, `ServiceResponse` — shared admission → service-time → ε → logging core, with aspect-oriented decorator alias `@activity_logged` (`core/instrumented.py`).
"""

from src.experiment.core.atomic import AtomicQueue
from src.experiment.core.composite import CompositeQueue, ExternalForwardFn
from src.experiment.core.instrumented import (LOG_COLUMNS,
                                              NextHopFn,
                                              ServiceRequest,
                                              ServiceResponse,
                                              activity_logged,
                                              instrumented,
                                              run_instrumented)
from src.experiment.core.spec import ServiceSpec, derive_seed

__all__ = [
    "AtomicQueue",
    "CompositeQueue",
    "ExternalForwardFn",
    "LOG_COLUMNS",
    "NextHopFn",
    "ServiceRequest",
    "ServiceResponse",
    "ServiceSpec",
    "activity_logged",
    "derive_seed",
    "instrumented",
    "run_instrumented",
]
