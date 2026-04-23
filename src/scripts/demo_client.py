# -*- coding: utf-8 -*-
"""
demo_client.py
==============

Show a `ClientSimulator` sending ONE kind-tagged request end-to-end
through the in-process mesh. Prints:

    - the resolved `ClientConfig` (kind weights, ramp, size map, seed)
    - the request that goes out (id, kind, size_bytes, payload blob preview)
    - the headers attached to the HTTP call
    - the response body received
    - the client-side `InvocationRecord` (status, success flags)

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

from src.experiment.client import (CascadeConfig,  # noqa: E402
                                   ClientConfig,
                                   ClientSimulator,
                                   InvocationRecord,
                                   RampConfig)
from src.experiment.launcher import ExperimentLauncher  # noqa: E402
from src.experiment.payload import generate_payload as _generate_payload  # noqa: E402
from src.experiment.payload import resolve_size_for_kind  # noqa: E402
from src.experiment.services import ServiceRequest  # noqa: E402
from src.io import load_method_config, load_profile  # noqa: E402


def _banner(s: str) -> None:
    """*_banner()* print a centred header band to stdout."""
    print()
    print("=" * 72)
    print(f"  {s}")
    print("=" * 72)


async def _demo() -> None:
    """*_demo()* spin up the launcher, send one request, show the InvocationRecord."""
    _cfg = load_profile(adaptation="baseline")
    _mcfg = load_method_config("experiment")
    # keep the ramp tiny; we send ONE request manually below so ramp config values do not really matter but must be present to satisfy validation
    _mcfg["ramp"] = {"min_samples_per_kind": 32,
                     "max_probe_window_s": 5.0,
                     "rates": [2.0],
                     "cascade": {"mode": "rolling",
                                 "threshold": 0.5, "window": 50}}

    async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
                                  adaptation="baseline") as _lnc:
        # ---- 1. show the client config the launcher would build ------
        _banner("1. ClientConfig (seed, entry, kind weights, size-by-kind, ramp)")
        _seed = int(_mcfg["seed"])
        _sizes_by_kind = dict(_mcfg.get("request_size_bytes", {}))
        _client_cfg = ClientConfig(
            entry_service="TAS_{1}",
            seed=_seed,
            request_size_bytes=int(_sizes_by_kind.get("analyse_request", 256)),
            request_sizes_by_kind=_sizes_by_kind,
            kind_weights=dict(_lnc.kind_weights),
            ramp=RampConfig(min_samples_per_kind=32,
                            max_probe_window_s=5.0,
                            rates=[2.0],
                            cascade=CascadeConfig()),
        )
        print(f"  seed            = {_client_cfg.seed}")
        print(f"  entry_service   = {_client_cfg.entry_service!r}")
        print(f"  kind_weights    = {_client_cfg.kind_weights}")
        print(f"  sizes_by_kind   = {_client_cfg.request_sizes_by_kind}")
        print(f"  fallback size   = {_client_cfg.request_size_bytes} bytes")
        print(f"  ramp rates      = {_client_cfg.ramp.rates}")

        _sim = ClientSimulator(_lnc.client, _lnc.registry, _client_cfg)
        print(f"  picked kind (deterministic) = {_sim._pick_kind()!r}")

        # ---- 2. show how _send_one would build + send a request ------
        _banner("2. build one ServiceRequest (kind + real ASCII payload)")
        # route a medical request into the TAS mesh
        _kind = "TAS_{2}"
        _size = resolve_size_for_kind(_client_cfg.request_sizes_by_kind, _kind,
                                      default=_client_cfg.request_size_bytes)
        _payload = _generate_payload(_kind, _size,
                                     rng=random.Random(_seed))
        _req = ServiceRequest(request_id=str(uuid.uuid4()),
                              kind=_kind,
                              size_bytes=_size,
                              payload=_payload.to_dict())
        print(f"  request_id       = {_req.request_id}")
        print(f"  kind             = {_req.kind!r}")
        print(f"  size_bytes       = {_req.size_bytes}")
        print(f"  payload.kind     = {_req.payload['kind']!r}")
        print(f"  payload.blob[:60]= {_req.payload['blob'][:60]!r}...")
        print(f"  entry URL        = {_lnc.registry.build_invoke_url('TAS_{1}')}")

        # ---- 3. actually send it ----
        _banner("3. HTTP POST to the TAS entry and observe the response")
        _url = _lnc.registry.build_invoke_url("TAS_{1}")
        _headers = {"X-Request-Id": _req.request_id,
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

        # ---- 4. the client-side InvocationRecord shape ----
        # No second HTTP send; we construct the record directly from step 3's response. Calling `_sim._send_one()` here would fire another request through the mesh and this demo is meant to terminate quickly; the record shape is the interesting thing.
        _banner("4. what an InvocationRecord would look like post-send")
        _body = _r.json()
        _rec = InvocationRecord(
            request_id=_req.request_id,
            kind=_req.kind,
            size_bytes=_req.size_bytes,
            # placeholder: 10 ms before now
            send_ts=time.time() - 0.01,
            recv_ts=time.time(),
            status_code=_r.status_code,
            success=bool(_body.get("success", False)),
        )
        print(f"  request_id       = {_rec.request_id}")
        print(f"  kind             = {_rec.kind!r}")
        print(f"  size_bytes       = {_rec.size_bytes}")
        print(f"  response_time_s  = {_rec.response_time_s:.6f}")
        print(f"  status_code      = {_rec.status_code}")
        print(f"  success          = {_rec.success}")
        print(f"  business_failure = {_rec.business_failure}")
        print(f"  infra_failure    = {_rec.infra_failure}")

        # ---- 5. graceful shutdown trace ----
        _banner("5. shutting down")
        print("  stopping ExperimentLauncher context manager...")

    # once the launcher's __aexit__ returns (client aclose + transport aclose), we're back at the async-fn top level with nothing left to do except print the farewell banner
    _banner("demo complete; exiting")
    print("  ok")


def main() -> None:
    """*main()* entry point: run the async demo to completion."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
