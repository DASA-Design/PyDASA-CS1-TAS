# -*- coding: utf-8 -*-
"""
demo_tas.py
===========

Walk through `src.experiment.instances.build_tas` piece by piece so a
human can watch the six-member TAS app shape up: one FastAPI app
hosting TAS_{1..3}, kind-dispatch at the entry, Jackson-weighted
hops inside the app, and the external-forward boundary when a
routing row names a non-TAS target. Every app is poked directly
through `httpx.ASGITransport`; no launcher, no uvicorn, no ports.

Three sections, one per behaviour:

    1. Kind-dispatch entry: the client's `kind` selects the target at TAS_{1} via `kind_to_target`.
    2. In-process hops: TAS_{1} -> TAS_{2} -> TAS_{3}; every visited member logs exactly one row.
    3. External-forward boundary: the closure fires iff the target is NOT a TAS member.

Run:
    python src/scripts/demo_tas.py
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

from src.experiment.instances import build_tas  # noqa: E402
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


def _tas_spec(name: str, *, seed: int = 1) -> SvcSpec:
    """*_tas_spec()* stock TAS-member spec; `mu=1e9` keeps service time near-zero."""
    _specs = SvcSpec(name=name,
                     role="tas",
                     port=8000,
                     mu=1e9,
                     epsilon=0.0,
                     c=1,
                     K=10,
                     seed=seed)
    return _specs


async def _no_forward(_target: str, _req: SvcReq) -> SvcResp:
    """*_no_forward()* raise on any call; used by sections that must stay in-process."""
    raise AssertionError(f"unexpected forward to {_target!r}")


def _recorded_forward(_calls: List[Tuple[str, str]]):
    """*_recorded_forward()* build a forward closure that appends `(target, request_id)` to `_calls`."""

    async def _fwd(target: str, req: SvcReq) -> SvcResp:
        _calls.append((target, req.request_id))
        _res = SvcResp(request_id=req.request_id,
                       service_name=target,
                       success=True,
                       message="recorded")
        return _res

    return _fwd


async def _post_entry(_app, _kind: str,
                      _size_bytes: int = 64) -> httpx.Response:
    """*_post_entry()* POST one `SvcReq` to `/TAS_1/invoke` over `ASGITransport`."""
    _transport = httpx.ASGITransport(app=_app)
    async with httpx.AsyncClient(transport=_transport,
                                 base_url="http://t") as _c:
        _req = SvcReq(kind=_kind, size_bytes=_size_bytes)
        return await _c.post("/TAS_1/invoke", json=_req.model_dump())


async def _demo() -> None:
    """*_demo()* run the three demo sections in sequence."""
    # -------- 1. kind-dispatch at the entry member -----------------------
    _banner("1. build_tas - kind-dispatch at TAS_{1}")
    _specs = {
        "TAS_{1}": _tas_spec("TAS_{1}", seed=1),
        "TAS_{2}": _tas_spec("TAS_{2}", seed=2),
    }
    _rows = {
        "TAS_{1}": [],
        "TAS_{2}": [],
    }
    _k2t = {"analyse": "TAS_{2}"}
    _app = build_tas(_specs, _rows, _k2t, _no_forward)
    _r = await _post_entry(_app, _kind="analyse")
    print(f"  POST /TAS_1/invoke  status = {_r.status_code}")
    print(f"  body                      = {_r.json()}")
    print(f"  TAS_{{1}}.log rows          = {len(_app.state.tas_components['TAS_{1}'].log)}")
    print(f"  TAS_{{2}}.log rows          = {len(_app.state.tas_components['TAS_{2}'].log)}")

    # -------- 2. in-process hops across three members --------------------
    _banner("2. build_tas - in-process chain TAS_{1} -> TAS_{2} -> TAS_{3}")
    _specs = {
        "TAS_{1}": _tas_spec("TAS_{1}", seed=1),
        "TAS_{2}": _tas_spec("TAS_{2}", seed=2),
        "TAS_{3}": _tas_spec("TAS_{3}", seed=3),
    }
    _rows = {
        "TAS_{1}": [],
        "TAS_{2}": [("TAS_{3}", 1.0)],
        "TAS_{3}": [],
    }
    _k2t = {"analyse": "TAS_{2}"}
    _app = build_tas(_specs, _rows, _k2t, _no_forward)
    _r = await _post_entry(_app, _kind="analyse")
    print(f"  POST /TAS_1/invoke  status = {_r.status_code}")
    print(f"  body                      = {_r.json()}")
    for _name, _ctx in _app.state.tas_components.items():
        _rid = _ctx.log[0]["request_id"] if _ctx.log else None
        print(f"    {_name:<10}  log_rows={len(_ctx.log)}  request_id={_rid}")
    _row = _app.state.tas_components["TAS_{1}"].log[0]
    print(f"  LOG_COLUMNS present       = "
          f"{sorted(set(LOG_COLUMNS).intersection(_row))}")

    # -------- 3. external-forward boundary -------------------------------
    _banner("3. build_tas - external forward at TAS_{2} -> MAS_{1}")
    _calls: List[Tuple[str, str]] = []
    _fwd = _recorded_forward(_calls)
    _specs = {
        "TAS_{1}": _tas_spec("TAS_{1}", seed=1),
        "TAS_{2}": _tas_spec("TAS_{2}", seed=2),
    }
    _rows = {
        "TAS_{1}": [],
        "TAS_{2}": [("MAS_{1}", 1.0)],
    }
    _k2t = {"analyse": "TAS_{2}"}
    _app = build_tas(_specs, _rows, _k2t, _fwd)
    _r = await _post_entry(_app, _kind="analyse")
    print(f"  POST /TAS_1/invoke  status = {_r.status_code}")
    print(f"  body                      = {_r.json()}")
    print(f"  forward calls             = {_calls}")

    _banner("demo complete - exiting")
    print("  ok")


def main() -> None:
    """*main()* CLI entry point; wraps the async demo."""
    asyncio.run(_demo())


if __name__ == "__main__":
    main()
