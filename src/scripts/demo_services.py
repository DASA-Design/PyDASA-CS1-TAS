# -*- coding: utf-8 -*-
"""
demo_services.py
================

Walk through the generic `src/experiment/services/` layer piece by piece so a human can watch what each part produces and see that it behaves as intended. No queueing classes; the layer only provides specs, per-service contexts, an `@logger` annotation, and two mount helpers (atomic + composite).

Run:
    python src/scripts/demo_services.py
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

from src.experiment.services import (  # noqa: E402
    LOG_COLUMNS,
    ServiceContext,
    ServiceRequest,
    ServiceResponse,
    ServiceSpec,
    derive_seed,
    logger,
    make_base_app,
    mount_atomic_service,
    mount_composite_service,
)


def _banner(_s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {_s}")
    print("=" * 72)


async def _recorded_forward_factory(_calls: List[Tuple[str, str]]):
    """*_recorded_forward_factory()* build a forward closure that appends `(target, request_id)` to `_calls` and returns `success=True`."""
    async def _fwd(target: str, req: ServiceRequest) -> ServiceResponse:
        _calls.append((target, req.request_id))
        return ServiceResponse(request_id=req.request_id,
                               service_name=target,
                               success=True,
                               message="recorded")
    return _fwd


async def _demo() -> None:
    """*_demo()* walk the six services-layer primitives (spec, derive_seed, ctx, @logger, atomic, composite) in sequence."""
    # -------- 1. ServiceSpec ---------------------------------------------
    _banner("1. ServiceSpec - frozen per-service knobs (no queueing logic)")
    _spec = ServiceSpec(name="MAS_{1}", role="atomic", port=8006,
                        mu=500.0, epsilon=0.1, c=2, K=20,
                        seed=42, mem_per_buffer=4096)
    print(f"  name                 = {_spec.name!r}")
    print(f"  role                 = {_spec.role!r}")
    print(f"  mu / epsilon / c / K = {_spec.mu} / {_spec.epsilon} / "
          f"{_spec.c} / {_spec.K}")
    print(f"  seed                 = {_spec.seed}")
    print(f"  mem_per_buffer       = {_spec.mem_per_buffer} bytes")
    print(f"  MEM_HEADROOM_FACTOR  = {ServiceSpec.MEM_HEADROOM_FACTOR}")
    print(f"  buffer_budget_bytes()= {_spec.buffer_budget_bytes}")

    # -------- 2. derive_seed ---------------------------------------------
    _banner("2. derive_seed - single JSON seed -> one 64-bit seed per name")
    _root = 42
    for _name in ("TAS_{1}", "TAS_{2}", "MAS_{1}", "AS_{1}", "DS_{3}"):
        _s = derive_seed(_root, _name)
        print(f"  derive_seed(root={_root}, name={_name!r}) = 0x{_s:016x}")
    print(f"\n  stable across calls:  "
          f"{derive_seed(42, 'TAS_{1}') == derive_seed(42, 'TAS_{1}')}")
    print(f"  changes with root:    "
          f"{derive_seed(42, 'TAS_{1}') != derive_seed(7, 'TAS_{1}')}")

    # -------- 3. ServiceContext ------------------------------------------
    _banner("3. ServiceContext - mutable runtime state (spec + rng + log)")
    _ctx = ServiceContext(spec=_spec)
    print(f"  spec.name            = {_ctx.spec.name!r}")
    print(f"  rng (seeded)         = {_ctx.rng}")
    print(f"  log (empty at start) = {_ctx.log}")
    print(f"  first 5 service_time draws (exponential at mu={_spec.mu}):")
    for _ in range(5):
        print(f"    {_ctx.draw_svc_time():.6f} s")
    # 20 Bernoulli trials so the ~10% fire-rate is observable; 3 trials at eps=0.1 would hit zero fires ~73% of the time (sampling noise). True = Bernoulli FIRED (business FAILURE at this service); False = did not fire (this invocation would succeed locally).
    _draws = [_ctx.draw_eps() for _ in range(20)]
    _fires = sum(_draws)
    print(f"  20 epsilon-Bernoulli draws (eps={_spec.epsilon}):")
    print("    meaning: True = fired = business failure; "
          "False = did NOT fire = success")
    print(f"    sequence       = {_draws}")
    print(f"    fires (fails)  = {_fires} / 20  "
          f"(rate {_fires / 20:.2f}; expected {_spec.epsilon:.2f})")
    print(f"    non-fires (ok) = {20 - _fires} / 20")

    # -------- 4. @logger decorator ---------------------------------
    _banner("4. @logger - one CSV row per call, no queueing state")
    _ctx2 = ServiceContext(spec=ServiceSpec(name="TAS_{2}",
                                            role="composite_medical",
                                            port=8001, mu=1e9, epsilon=0.0,
                                            c=1, K=10, seed=1))

    @logger(_ctx2)
    async def _handler(req: ServiceRequest) -> ServiceResponse:
        # small sleep so recv_ts < end_ts is visible in the row. In the real atomic handler this is `asyncio.sleep(expovariate(mu))`; here we just await a fixed 5 ms so the demo prints non-zero work.
        await asyncio.sleep(0.005)
        return ServiceResponse(request_id=req.request_id,
                               service_name=_ctx2.spec.name,
                               success=True,
                               message="ok")

    _req = ServiceRequest(kind="analyse", size_bytes=128)
    _resp = await _handler(_req)
    print(f"  handler returned     = success={_resp.success}, msg={_resp.message!r}")
    print(f"  rows recorded        = {len(_ctx2.log)}")
    _row = _ctx2.log[0]
    for _c in LOG_COLUMNS:
        print(f"    {_c:<22} = {_row.get(_c)!r}")

    # -------- 5. mount_atomic_service ------------------------------------
    _banner("5. mount_atomic_service - terminal MAS handler (empty routing)")
    _app = make_base_app("demo::MAS")
    _ctx3 = mount_atomic_service(
        _app,
        ServiceSpec(name="MAS_{1}", role="atomic", port=8007,
                    mu=1e9, epsilon=0.0, c=1, K=10, seed=3),
        targets=[],
        external_forward=lambda t, r: None,  # never called for terminal
    )
    _transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=_transport,
                                 base_url="http://t") as _c:
        _r = await _c.post("/invoke",
                           json=ServiceRequest(kind="analyse",
                                               size_bytes=64).model_dump())
    print(f"  POST /invoke  status = {_r.status_code}")
    print(f"  body                 = {_r.json()}")
    print(f"  ctx.log rows         = {len(_ctx3.log)}")

    # -------- 6. mount_composite_service ---------------------------------
    _banner("6. mount_composite_service - TAS-like: entry + internal hop + external forward")
    _calls: List[Tuple[str, str]] = []
    _forward = await _recorded_forward_factory(_calls)
    _app_tas = make_base_app("demo::TAS")
    _specs = {
        "TAS_{1}": ServiceSpec(name="TAS_{1}", role="composite_client",
                               port=8001, mu=1e9, epsilon=0.0,
                               c=1, K=10, seed=derive_seed(42, "TAS_{1}")),
        "TAS_{2}": ServiceSpec(name="TAS_{2}", role="composite_medical",
                               port=8001, mu=1e9, epsilon=0.0,
                               c=1, K=10, seed=derive_seed(42, "TAS_{2}")),
    }
    _rows = {
        "TAS_{1}": [],                          # entry; dispatched by kind_to_target
        "TAS_{2}": [("MAS_{1}", 1.0)],          # forwards externally to MAS_{1}
    }
    _k2t = {"TAS_{2}": "TAS_{2}"}
    mount_composite_service(_app_tas,
                            specs=_specs,
                            routing_rows=_rows,
                            kind_to_target=_k2t,
                            external_forward=_forward,
                            entry_name="TAS_{1}")

    _transport = httpx.ASGITransport(app=_app_tas)
    async with httpx.AsyncClient(transport=_transport,
                                 base_url="http://t") as _c:
        _req = ServiceRequest(kind="TAS_{2}", size_bytes=128)
        _r = await _c.post("/TAS_1/invoke", json=_req.model_dump())
    print(f"  POST /TAS_1/invoke  status = {_r.status_code}")
    print(f"  body                     = {_r.json()}")
    print(f"  external_forward calls   = {_calls}")
    print("  per-member rows:")
    for _name, _ctx in _app_tas.state.tas_components.items():
        print(f"    {_name:<10}  log_rows={len(_ctx.log)}")

    # -------- shutdown --------------------------------------------------
    _banner("demo complete - exiting")
    print("  ok")


def main() -> None:
    """*main()* CLI entry point; wraps the async demo."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
