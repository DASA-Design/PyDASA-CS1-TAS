# -*- coding: utf-8 -*-
"""
Module client/sender.py
=======================

`RequestSender`: build one kind-tagged request, POST it to the entry service, and capture the outcome as a `RequestRecord`. Owns the seeded RNG so payload bytes and request IDs are reproducible across runs at the same `seed`.
"""
# native python modules
from __future__ import annotations

import asyncio
import random
import time
import uuid
from typing import Dict

# web stack
import httpx

# local modules
from src.experiment.client.config import ClientCfg
from src.experiment.client.records import RequestRecord
from src.experiment.services import SvcReq
from src.experiment.wire import SvcRegistry, generate_payload, resolve_size_for_kind


class RequestSender:
    """*RequestSender* synthesise + POST one client request, return the outcome record.

    Holds the seeded RNG, the httpx client, the registry, and the static config so each `send_one(kind)` call produces a reproducible payload + request ID at the same seed.
    """

    def __init__(self, client: httpx.AsyncClient,
                 registry: SvcRegistry,
                 cfg: ClientCfg,
                 rng: random.Random) -> None:
        """*__init__()* bind dependencies; the seeded RNG is shared with `RateDriver` for kind sampling.

        Args:
            client (httpx.AsyncClient): already-configured async client.
            registry (SvcRegistry): URL resolver for `cfg.entry_service`.
            cfg (ClientCfg): static runtime spec.
            rng (random.Random): seeded RNG; reused for payload bytes and request IDs.
        """
        self.client = client
        self.registry = registry
        self.cfg = cfg
        self.rng = rng

    async def send_one(self, kind: str) -> RequestRecord:
        """*send_one()* POST one kind-tagged request and capture the outcome.

        Generates a real per-kind payload under the seeded RNG, mirrors the byte count in headers, and stamps `send_ts` / `recv_ts` on the surrounding `perf_counter` window. Transport-level failures map to `status_code=-1` so downstream cascade detection sees them.

        Args:
            kind (str): request kind label; must be a key of the client's probability map.

        Returns:
            RequestRecord: populated record (status, success, timing).
        """
        _size = resolve_size_for_kind(self.cfg.req_sizes_by_kind,
                                      kind,
                                      default=int(self.cfg.req_size_b))
        _payload = generate_payload(kind,
                                    _size,
                                    rng=self.rng)
        _rid = str(uuid.UUID(int=self.rng.getrandbits(128), version=4))
        _req = SvcReq(req_id=_rid,
                      kind=kind,
                      size_bytes=_size,
                      payload=_payload.to_dict())
        _url = self.registry.build_invoke_url(self.cfg.entry_service)
        _headers: Dict[str, str] = {"X-Request-Id": _req.req_id,
                                    "X-Request-Size-Bytes": str(_size),
                                    "X-Request-Kind": kind}
        _rec = RequestRecord(req_id=_req.req_id,
                             kind=kind,
                             size_bytes=_req.size_bytes,
                             send_ts=time.perf_counter())
        try:
            _r = await self.client.post(_url,
                                        json=_req.model_dump(),
                                        headers=_headers,
                                        timeout=10.0)
            _rec.recv_ts = time.perf_counter()
            _rec.status_code = _r.status_code
            if _r.status_code == 200:
                _body = _r.json()
                _rec.success = bool(_body.get("success", False))
        except (httpx.HTTPError, ConnectionError, OSError,
                asyncio.TimeoutError, ValueError):
            _rec.recv_ts = time.perf_counter()
            _rec.status_code = -1
            _rec.success = False
        return _rec
