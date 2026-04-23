# -*- coding: utf-8 -*-
"""CS-01 service instantiations.

Case-study-specific composition: the TAS target system (ONE FastAPI app with six atomic handlers as members) and the third-party services (one FastAPI app per MAS / AS / DS).

Both are parameterised FUNCTIONS, not classes; they assemble generic `services/` building blocks (ServiceSpec, ServiceContext, atomic / composite mounts) with CS-01-specific parameters.

    - `build_tas(specs, routing_rows, kind_to_target, forward)` -> FastAPI
    - `build_third_party(spec, targets, forward)` -> FastAPI
"""

from src.experiment.instances.tas import build_tas
from src.experiment.instances.third_party import build_third_party
from src.experiment.services import (ServiceRequest,
                                     ServiceResponse,
                                     ServiceSpec)

__all__ = [
    "ServiceRequest",
    "ServiceResponse",
    "ServiceSpec",
    "build_tas",
    "build_third_party",
]
