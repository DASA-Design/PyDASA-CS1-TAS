# -*- coding: utf-8 -*-
"""
demo_client.py
==============

Show a `ClientSimulator` sending ONE kind-tagged request end-to-end
through the in-process mesh. Prints:

    - the resolved `ClientCfg` (kind weights, ramp, size map, seed)
    - the request that goes out (id, kind, size_bytes, payload blob preview)
    - the headers attached to the HTTP call
    - the response body received
    - the client-side `RequestRecord` (status, success flags)

No ramp is driven; just one send, so this runs in a couple of seconds
instead of minutes.

Run:
    python src/scripts/demo_client.py
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

from src.experiment.client import (CascadeCfg,  # noqa: E402
                                   ClientCfg,
                                   ClientSimulator,
                                   RampCfg,
                                   RequestRecord)
from src.experiment.architecture import TasArchitecture  # noqa: E402
from src.experiment.wire import generate_payload as _generate_payload  # noqa: E402
from src.experiment.wire import resolve_size_for_kind  # noqa: E402
from src.experiment.services import SvcReq  # noqa: E402
from src.io import load_method_cfg, load_profile  # noqa: E402


def _banner(s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


async def _demo() -> None:
    """*_demo()* spin up the architecture, send one request, show the RequestRecord."""
    _cfg = load_profile(adaptation="baseline")
    _mcfg = load_method_cfg("experiment")
    # keep the ramp tiny; we send ONE request manually below so ramp config values do not really matter but must be present to satisfy validation
    _mcfg["ramp"] = {"min_samples_per_kind": 32,
                     "max_probe_window_s": 5.0,
                     "rates": [2.0],
                     "cascade": {"mode": "rolling",
                                 "threshold": 0.5, "window": 50}}

    async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                               adaptation="baseline") as _lnc:
        # ---- 1. show the client config the architecture would build ------
        _banner("1. ClientCfg (seed, entry, kind weights, size-by-kind, ramp)")
        _seed = int(_mcfg["seed"])
        _sizes_by_kind = dict(_mcfg.get("request_size_bytes", {}))
        _client_cfg = ClientCfg(
            entry_service="TAS_{1}",
            seed=_seed,
            req_size_b=int(_sizes_by_kind.get("analyse_request", 256)),
            req_sizes_by_kind=_sizes_by_kind,
            kind_prob=dict(_lnc.kind_prob),
            ramp=RampCfg(min_n_per_kind=32,
                         max_probe_s=5.0,
                         rates=[2.0],
                         cascade=CascadeCfg()),
        )
        print(f"  seed            = {_client_cfg.seed}")
        print(f"  entry_service   = {_client_cfg.entry_service!r}")
        print(f"  kind_prob          = {_client_cfg.kind_prob}")
        print(f"  sizes_by_kind   = {_client_cfg.req_sizes_by_kind}")
        print(f"  fallback size   = {_client_cfg.req_size_b} bytes")
        print(f"  ramp rates      = {_client_cfg.ramp.rates}")

        _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)
        print(f"  picked kind (deterministic) = {_sim.driver._pick_kind()!r}")

        # ---- 2. show how RequestSender would build + send a request ------
        _banner("2. build one SvcReq (kind + real ASCII payload)")
        # route a medical request into the TAS mesh
        _kind = "TAS_{2}"
        _size = resolve_size_for_kind(_client_cfg.req_sizes_by_kind, _kind,
                                      default=_client_cfg.req_size_b)
        _payload = _generate_payload(_kind, _size,
                                     rng=random.Random(_seed))
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
            f"  entry URL        = {_lnc.registry.build_invoke_url('TAS_{1}')}")

        # ---- 3. actually send it ----
        _banner("3. HTTP POST to the TAS entry and observe the response")
        _url = _lnc.registry.build_invoke_url("TAS_{1}")
        _headers = {"X-Request-Id": _req.req_id,
                    "X-Request-Size-Bytes": str(_req.size_bytes),
                    "X-Request-Kind": _req.kind}
        for _k, _v in _headers.items():
            print(f"  header  {_k}: {_v}")

        try:
            _r = await _lnc.client.post(_url, json=_req.model_dump(),
                                        headers=_headers, timeout=10.0)
            print(f"\n  status_code      = {_r.status_code}")
            print(f"  response body    = {_r.json()}")
        except httpx.HTTPStatusError as _exc:
            print(f"  HTTP error: {_exc}")

        # ---- 4. the client-side RequestRecord shape ----
        # No second HTTP send; we construct the record directly from step 3's response. Calling `_sim.sender.send_one()` here would fire another request through the mesh and this demo is meant to terminate quickly; the record shape is the interesting thing.
        _banner("4. what a RequestRecord would look like post-send")
        _body = _r.json()
        _rec = RequestRecord(
            req_id=_req.req_id,
            kind=_req.kind,
            size_bytes=_req.size_bytes,
            # placeholder: 10 ms before now
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
        print("  stopping TasArchitecture context manager...")

    # once the architecture's __aexit__ returns (client aclose + transport aclose), we're back at the async-fn top level with nothing left to do except print the farewell banner
    _banner("demo complete; exiting")
    print("  ok")


def main() -> None:
    """*main()* entry point: run the async demo to completion."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
