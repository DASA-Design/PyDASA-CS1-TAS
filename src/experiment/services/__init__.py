# -*- coding: utf-8 -*-
"""Shared service building blocks.

Five modules, one responsibility each:

    - `base.py`: `SvcSpec`, `SvcCtx`, wire schemas, `LOG_COLUMNS`, `make_base_app`, `HttpForward`, `derive_seed`.
    - `instruments.py`: `@logger` method-form decorator + `LogProbe` + `stamp_admit` / `stamp_local_end`. Records one CSV row per invocation; per-call state flows through the probe arg.
    - `atomic.py`: `mount_atomic_svc(app, spec, targets, ext_fwd, *, route, pick_tgt, dispatch)` attaches an `AtomicHandler` to a FastAPI app.
    - `composite.py`: `mount_composite_svc(app, specs, routing_rows, kind_to_tgt, ext_fwd, *, entry_name, route_for)` attaches N atomic members behind one app with in-process sibling dispatch via `CompositeDispatch` and entry-side kind routing via `KindPick`.
    - `vernier.py`: `mount_vernier_svc(app, spec, payload_size_bytes, *, route)` attaches a `VernierHandler` for host-floor calibration.

CS-01 instantiations live in `src/experiment/instances/`.
"""

from src.experiment.services.atomic import mount_atomic_svc
from src.experiment.services.base import (LOG_COLUMNS,
                                          ExtFwdFn,
                                          HttpForward,
                                          SvcCtx,
                                          SvcReq,
                                          SvcResp,
                                          SvcSpec,
                                          derive_seed,
                                          make_base_app)
from src.experiment.services.composite import mount_composite_svc
from src.experiment.services.instruments import logger
from src.experiment.services.vernier import mount_vernier_svc

__all__ = [
    "ExtFwdFn",
    "HttpForward",
    "LOG_COLUMNS",
    "SvcCtx",
    "SvcReq",
    "SvcResp",
    "SvcSpec",
    "derive_seed",
    "logger",
    "make_base_app",
    "mount_atomic_svc",
    "mount_composite_svc",
    "mount_vernier_svc",
]
