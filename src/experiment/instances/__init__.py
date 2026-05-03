# -*- coding: utf-8 -*-
"""CS-01 service instantiations.

Case-study-specific composition: the TAS target system (ONE FastAPI app with six atomic handlers), the third-party services (one FastAPI app per MAS / AS / DS), and the calibration gauge (a single-vernier echo app for host-floor probes).

All three are parameterised FUNCTIONS, not classes; they assemble generic `services/` building blocks with CS-01-specific parameters.

    - `build_tas(specs, routing_rows, kind_to_tgt, ext_fwd, *, entry_name)` -> FastAPI
    - `build_third_party(spec, targets, ext_fwd)` -> FastAPI
    - `build_gauge(spec, payload_size_bytes, *, title)` -> FastAPI
    - `make_gauge_factory(spec, payload_size_bytes, *, title)` -> Callable[[], FastAPI] (picklable zero-arg factory for `UvicornProcess`)
"""

from src.experiment.instances.gauge import build_gauge, make_gauge_factory
from src.experiment.instances.tas import build_tas
from src.experiment.instances.third_party import build_third_party
from src.experiment.services import (SvcReq,
                                     SvcResp,
                                     SvcSpec)

__all__ = [
    "SvcReq",
    "SvcResp",
    "SvcSpec",
    "build_gauge",
    "build_tas",
    "build_third_party",
    "make_gauge_factory",
]
