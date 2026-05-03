# -*- coding: utf-8 -*-
"""
Module instances/gauge.py
=========================

Single-vernier FastAPI app for host-floor calibration. Sibling of `third_party.py`: where third-party builds an atomic-handler app for the TAS mesh, gauge builds a vernier-handler app for the calibration probes (terminal echo, no routing).

In-process usage (`UvicornThread` callers, calibration localhost mode)::

    from src.experiment.instances import build_gauge
    from src.experiment.services import SvcSpec

    spec = SvcSpec(name="CALIB", role="atomic", port=8000,
                   mu=0.0, epsilon=0.0, c=1, K=50,
                   seed=0, mem_per_buffer=...)
    app = build_gauge(spec, payload_size_bytes=131072)

Multi-process usage (`UvicornProcess` callers, calibration multiprocess mode and SOA case-study mesh)::

    from src.experiment.instances import make_gauge_factory
    from src.experiment.runtime import UvicornProcess

    factory = make_gauge_factory(spec, payload_size_bytes=131072)
    proc = UvicornProcess(factory, port=8000)
    proc.start()
    proc.wait_ready()

`make_gauge_factory` returns a `functools.partial` over the top-level `build_gauge`; both the function reference and `SvcSpec` (frozen dataclass with primitive fields) are picklable across the Windows `spawn` boundary, so the factory survives the `multiprocessing.Process` argument-pickling step without any extra plumbing.
"""
# native python modules
from __future__ import annotations

import functools
from typing import Callable, Optional

# web stack
from fastapi import FastAPI

# local modules
from src.experiment.services import SvcSpec, make_base_app, mount_vernier_svc


def build_gauge(spec: SvcSpec,
                payload_size_bytes: int = 0,
                *,
                title: Optional[str] = None) -> FastAPI:
    """*build_gauge()* assemble a single-vernier echo app for calibration probes.

    Mirrors `build_third_party` for the calibration use case: terminal handler at `/invoke`, no routing, payload echoed end-to-end so `phi` is measurable on constant-payload workloads.

    Args:
        spec (SvcSpec): per-service knobs; `mu` and `epsilon` are typically 0 at calibration time so the loopback floor stays honest.
        payload_size_bytes (int): declared payload size echoed in `SvcResp.message` for cross-checks against the recorded `size_bytes` CSV column.
        title (Optional[str]): FastAPI app title; defaults to `"calibration-vernier::<spec.name>"`.

    Returns:
        FastAPI: app with `/healthz` (from `make_base_app`) and `/invoke` (from vernier); `SvcCtx` exposed on `app.state.ctx`.
    """
    if title is None:
        _title = f"calibration-vernier::{spec.name}"
    else:
        _title = title
    _app = make_base_app(_title)
    mount_vernier_svc(_app, spec, payload_size_bytes=int(payload_size_bytes))
    return _app


def make_gauge_factory(spec: SvcSpec,
                       payload_size_bytes: int = 0,
                       *,
                       title: Optional[str] = None
                       ) -> Callable[[], FastAPI]:
    """*make_gauge_factory()* return a zero-arg picklable callable that builds a gauge app inside a worker process.

    The returned `functools.partial` binds `spec` / `payload_size_bytes` / `title` over the top-level `build_gauge`. Both `build_gauge` (module-scope) and `SvcSpec` (frozen dataclass over primitives) are picklable across the Windows `spawn` boundary, so the factory survives `multiprocessing.Process(target=worker, args=(factory, ...))` and the worker calls it inside its own address space.

    Pair with `UvicornProcess` for multiprocess calibration and the SOA case-study mesh; use `build_gauge` directly with `UvicornThread` for in-process calibration.

    Args:
        spec (SvcSpec): per-service knobs; same shape as `build_gauge`.
        payload_size_bytes (int): declared payload size; same as `build_gauge`.
        title (Optional[str]): FastAPI app title; same as `build_gauge`.

    Returns:
        Callable[[], FastAPI]: zero-arg picklable factory; calling it returns the same FastAPI app `build_gauge(spec, payload_size_bytes, title=title)` would.
    """
    return functools.partial(build_gauge,
                             spec,
                             int(payload_size_bytes),
                             title=title)
