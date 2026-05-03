# -*- coding: utf-8 -*-
"""
demo_client.py
==============

Show the client side of the prototype end-to-end via `TasUser`. Prints:

    - the resolved `ClientCfg` the user assembled (kind weights, ramp, size map, seed)
    - one kind-tagged `SvcReq` built by hand (id, kind, size_bytes, payload preview)
    - the headers attached to the HTTP call
    - the response body received
    - the client-side `RequestRecord` shape post-send

No ramp is driven; one manual send keeps the demo to a couple of seconds.

Run:
    python tests/demos/demo_client.py
"""
import asyncio
import random
import sys
import time
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT))

import httpx   # noqa: E402

from src.experiment.architecture import TasArchitecture  # noqa: E402
from src.experiment.client import RequestRecord  # noqa: E402
from src.experiment.services import SvcReq  # noqa: E402
from src.experiment.users import TasUser  # noqa: E402
from src.experiment.wire import generate_payload as _generate_payload  # noqa: E402
from src.experiment.wire import resolve_size_for_kind  # noqa: E402
from src.io import load_method_cfg, load_profile  # noqa: E402


def _banner(s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


async def _demo() -> None:
    """*_demo()* spin up the architecture, attach a TasUser, send one request, show the RequestRecord."""
    _cfg = load_profile(adaptation="baseline")
    _mcfg = load_method_cfg("experiment")
    # tiny ramp; we only manually send one request below, but the ramp block must satisfy load_ramp_cfg validation when TasUser builds the ClientCfg.
    _mcfg["ramp"] = {"min_samples_per_kind": 32,
                     "max_probe_window_s": 5.0,
                     "rates": [2.0],
                     "cascade": {"mode": "rolling",
                                 "threshold": 0.5, "window": 50}}

    async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                               adaptation="baseline") as _arch:
        if _arch.client is None or _arch.registry is None:
            raise RuntimeError("TasArchitecture did not populate client / registry")

        async with TasUser(client=_arch.client,
                           registry=_arch.registry,
                           method_cfg=_mcfg,
                           kind_prob=dict(_arch.kind_prob)) as _user:

            # ---- 1. show the ClientCfg the user assembled ----
            _banner("1. ClientCfg (seed, entry, kind weights, size-by-kind, ramp)")
            _client_cfg = _user.cfg
            if _client_cfg is None:
                raise RuntimeError("TasUser.__aenter__ did not populate cfg")
            print(f"  seed            = {_client_cfg.seed}")
            print(f"  entry_service   = {_client_cfg.entry_service!r}")
            print(f"  kind_prob       = {_client_cfg.kind_prob}")
            print(f"  sizes_by_kind   = {_client_cfg.req_sizes_by_kind}")
            print(f"  fallback size   = {_client_cfg.req_size_b} bytes")
            print(f"  ramp rates      = {_client_cfg.ramp.rates}")

            _sim = _user.simulator
            if _sim is None:
                raise RuntimeError("TasUser.__aenter__ did not populate simulator")
            print(f"  picked kind (deterministic) = {_sim.driver._pick_kind()!r}")

            # ---- 2. build one SvcReq by hand ----
            _banner("2. build one SvcReq (kind + real ASCII payload)")
            _kind = "TAS_{2}"
            _size = resolve_size_for_kind(_client_cfg.req_sizes_by_kind, _kind,
                                          default=_client_cfg.req_size_b)
            _payload = _generate_payload(_kind, _size,
                                         rng=random.Random(_client_cfg.seed))
            _req = SvcReq(req_id=str(uuid.uuid4()),
                          kind=_kind,
                          size_bytes=_size,
                          payload=_payload.to_dict())
            print(f"  req_id           = {_req.req_id}")
            print(f"  kind             = {_req.kind!r}")
            print(f"  size_bytes       = {_req.size_bytes}")
            print(f"  payload.kind     = {_req.payload['kind']!r}")
            print(f"  payload.blob[:60]= {_req.payload['blob'][:60]!r}...")
            print(
                f"  entry URL        = {_arch.registry.build_invoke_url('TAS_{1}')}")

            # ---- 3. send it through the architecture's transport ----
            _banner("3. HTTP POST to the TAS entry and observe the response")
            _url = _arch.registry.build_invoke_url("TAS_{1}")
            _headers = {"X-Request-Id": _req.req_id,
                        "X-Request-Size-Bytes": str(_req.size_bytes),
                        "X-Request-Kind": _req.kind}
            for _k, _v in _headers.items():
                print(f"  header  {_k}: {_v}")

            _r = None
            try:
                _r = await _arch.client.post(_url, json=_req.model_dump(),
                                             headers=_headers, timeout=10.0)
                print(f"\n  status_code      = {_r.status_code}")
                print(f"  response body    = {_r.json()}")
            except httpx.HTTPStatusError as _exc:
                print(f"  HTTP error: {_exc}")

            # ---- 4. RequestRecord shape ----
            # Construct the record from step 3's response (no second HTTP send so the demo terminates quickly). Skip cleanly if step 3 failed.
            _banner("4. what a RequestRecord would look like post-send")
            if _r is None:
                print("  step 3 failed; skipping RequestRecord construction")
            else:
                _body = _r.json()
                _rec = RequestRecord(
                    req_id=_req.req_id,
                    kind=_req.kind,
                    size_bytes=_req.size_bytes,
                    send_ts=time.time() - 0.01,
                    recv_ts=time.time(),
                    status_code=_r.status_code,
                    success=bool(_body.get("success", False)),
                )
                print(f"  req_id           = {_rec.req_id}")
                print(f"  kind             = {_rec.kind!r}")
                print(f"  size_bytes       = {_rec.size_bytes}")
                print(f"  response_time_s  = {_rec.response_time_s:.6f}")
                print(f"  status_code      = {_rec.status_code}")
                print(f"  success          = {_rec.success}")
                print(f"  business_failure = {_rec.business_failure}")
                print(f"  infra_failure    = {_rec.infra_failure}")

            # ---- 5. graceful shutdown trace ----
            _banner("5. shutting down")
            print("  stopping TasUser + TasArchitecture context managers...")

    # both __aexit__ blocks have returned (user resets the guard, architecture aclose-s the client + transports)
    _banner("demo complete; exiting")
    print("  ok")


def main() -> None:
    """*main()* entry point: run the async demo to completion."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
