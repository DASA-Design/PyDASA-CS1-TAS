# -*- coding: utf-8 -*-
"""
demo_third_party.py
===================

Walk through `src.experiment.instances.build_third_party` piece by
piece so a human can watch each FastAPI app shape up: a terminal MAS
(empty routing row), a forwarding MAS (one Jackson-weighted target),
and a Bernoulli-failing MAS (`epsilon = 1.0`). No launcher; every app
is poked directly through `httpx.ASGITransport`.

Three sections, one per behaviour:

    1. Terminal service: empty `targets` returns `success=True` after service time.
    2. Forward service: one target, routing picks it every call, the closure records `(target, request_id)`.
    3. Bernoulli service: eps = 1.0 returns `success=False, message="bernoulli failure"`; forward closure is never called.

Run:
    python src/scripts/demo_third_party.py
"""
# native python modules
import asyncio
import sys
from pathlib import Path
from typing import List, Tuple

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

import httpx  # noqa: E402

from src.experiment.instances import build_third_party  # noqa: E402
from src.experiment.services import (  # noqa: E402
    LOG_COLUMNS,
    SvcReq,
    SvcResp,
    SvcSpec,
)


def _banner(_s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {_s}")
    print("=" * 72)


def _mas_spec(*, epsilon: float = 0.0, seed: int = 42) -> SvcSpec:
    """*_mas_spec()* stock MAS spec for the demo; `mu=1e9` keeps service time near-zero."""
    _inst = SvcSpec(name="MAS_{1}",
                    role="atomic",
                    port=8006,
                    mu=1e9,
                    epsilon=epsilon,
                    c=1,
                    K=10,
                    seed=seed)
    return _inst


async def _no_forward(_target: str,
                      _req: SvcReq) -> SvcResp:
    """*_no_forward()* raises on any call; used by terminal + Bernoulli sections."""
    raise AssertionError(f"unexpected forward to {_target!r}")


def _recorded_forward(_calls: List[Tuple[str, str]]) -> httpx.AsyncClient:
    """*_recorded_forward()* build a forward closure that appends `(target, request_id)` to `_calls`."""

    async def _fwd(target: str, req: SvcReq) -> SvcResp:
        _calls.append((target, req.request_id))
        return SvcResp(request_id=req.request_id,
                       service_name=target,
                       success=True,
                       message="recorded")

    return _fwd


async def _post_invoke(_app, _kind: str = "analyse",
                       _size_bytes: int = 64) -> httpx.Response:
    """*_post_invoke()* POST one `SvcReq` to `/invoke` over `ASGITransport`."""
    _transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=_transport,
                                 base_url="http://t") as _c:
        _req = SvcReq(kind=_kind, size_bytes=_size_bytes)
        return await _c.post("/invoke", json=_req.model_dump())


async def _demo() -> None:
    """*_demo()* run the three demo sections in sequence."""
    # -------- 1. terminal service ----------------------------------------
    _banner("1. build_third_party - terminal MAS (empty targets)")
    _spec = _mas_spec()
    _app = build_third_party(_spec, targets=[], external_forward=_no_forward)
    _r = await _post_invoke(_app)
    print(f"  POST /invoke  status = {_r.status_code}")
    print(f"  body                 = {_r.json()}")
    print(f"  ctx.log rows         = {len(_app.state.ctx.log)}")
    _row = _app.state.ctx.log[0]
    print(f"  log columns          = {sorted(set(LOG_COLUMNS).intersection(_row))}")

    # -------- 2. forwarding service --------------------------------------
    _banner("2. build_third_party - forwarding MAS (one Jackson target)")
    _calls: List[Tuple[str, str]] = []
    _fwd = _recorded_forward(_calls)
    _spec = _mas_spec()
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             external_forward=_fwd)
    _r = await _post_invoke(_app)
    print(f"  POST /invoke  status = {_r.status_code}")
    print(f"  body                 = {_r.json()}")
    print(f"  forward calls        = {_calls}")

    # -------- 3. Bernoulli-failing service -------------------------------
    _banner("3. build_third_party - Bernoulli MAS (epsilon = 1.0)")
    _spec = _mas_spec(epsilon=1.0)
    _app = build_third_party(_spec,
                             targets=[("DS_{3}", 1.0)],
                             external_forward=_no_forward)
    _r = await _post_invoke(_app)
    print(f"  POST /invoke  status = {_r.status_code}")
    print(f"  body                 = {_r.json()}")
    print("  (forward closure was _no_forward; never called because " + "eps fired first)")

    _banner("demo complete - exiting")
    print("  ok")


def main() -> None:
    """*main()* CLI entry point; wraps the async demo."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
