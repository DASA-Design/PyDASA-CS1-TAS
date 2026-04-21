"""CS-01 service instantiations.

This layer names what a reader thinks in case-study terms: the TAS
target system (ONE FastAPI app with six embedded atomic components)
and the third-party services (one FastAPI app per artifact).

Both are FUNCTIONS, not classes — they construct generic `AtomicQueue`
/ `CompositeQueue` instances from `core/` with CS-01-specific
parameters and mount them via `http/`. No TAS-specific or third-party-
specific inheritance anywhere; parameterised construction only.

    - `build_tas(specs, routing_rows, kind_to_target, forward)` → FastAPI
    - `build_third_party(spec, targets, forward)` → FastAPI
"""

# re-export the wire schemas + spec dataclass so external callers can keep
# a stable `from src.experiment.services import ServiceRequest, ServiceSpec`
# import even while the implementation migrates into `core/` + `http/`
from src.experiment.core import (ServiceRequest,
                                 ServiceResponse,
                                 ServiceSpec)
from src.experiment.services.tas import build_tas
from src.experiment.services.third_party import build_third_party

__all__ = [
    "ServiceRequest",
    "ServiceResponse",
    "ServiceSpec",
    "build_tas",
    "build_third_party",
]
