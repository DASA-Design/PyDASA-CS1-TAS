"""Demo: drive three atomic services in series through real localhost TCP.

Spins up three independent atomic services (`MAS_{1}` -> `AS_{1}` -> `DS_{1}`) on
consecutive ports, posts three requests, and chains each request through the
three services in order: the medical-analysis answer feeds the alarm call, and
the alarm answer feeds the drug call. Each chain prints to stdout and the full
trace lands as JSON under `_sandbox/demo_composite/`.

Run from the project root:

    python -m tests.demo.composite

This demo is intentionally simple and self-contained. The full TAS topology +
workflow engine + verdict path is exercised by the experimental method
(`python -m src.methods.experimental --stage experiment`); this demo only shows
service chaining over real HTTP.
"""

from __future__ import annotations

import asyncio
import functools
import json
import shutil
from pathlib import Path
from typing import Any

import httpx

from src.experimental.procedure.deployment import MeshSpec, bring_up_mesh
from src.experimental.prototype.target.factory.third_party import (
    build_atomic_fastapi_app,
)

DEMO_BASE_PORT = 8070
DEMO_REQUESTS = 3
SERVICE_CHAIN: tuple[tuple[str, str, float], ...] = (
    ("MAS_{1}", "medical_analysis", 50.0),
    ("AS_{1}", "alarm", 200.0),
    ("DS_{1}", "drug", 1000.0),
)


def _build_specs() -> list[MeshSpec]:
    """Build one `MeshSpec` per service in the chain.

    Returns:
        list[MeshSpec]: spawner specs in the order they appear in `SERVICE_CHAIN`.
    """
    _specs: list[MeshSpec] = []
    for _svc_name, _kind, _mu in SERVICE_CHAIN:
        _factory = functools.partial(build_atomic_fastapi_app,
                                     svc_name=_svc_name,
                                     kind=_kind,
                                     mu=_mu)
        _specs.append(MeshSpec(svc_id=_svc_name, app_factory=_factory))
    return _specs


async def _call_one(http: httpx.AsyncClient,
                    url: str,
                    payload: dict[str, Any]) -> dict[str, Any]:
    """POST `payload` to `<url>/` and return the parsed JSON body.

    Args:
        http (httpx.AsyncClient): live HTTP client.
        url (str): atomic-service base URL.
        payload (dict[str, Any]): request body.

    Returns:
        dict[str, Any]: response body augmented with `_status` (HTTP status code).
    """
    _resp = await http.post(f"{url}/", json=payload, timeout=5.0)
    _body: dict[str, Any] = _resp.json()
    _body["_status"] = _resp.status_code
    return _body


async def _run_chain(req_idx: int,
                     urls: dict[str, str]) -> list[dict[str, Any]]:
    """Drive one request through the three services in order.

    Args:
        req_idx (int): zero-based request index (used to mint `req_id`).
        urls (dict[str, str]): `svc_id -> base URL` map yielded by `bring_up_mesh`.

    Returns:
        list[dict[str, Any]]: per-step trace; each entry has `svc` (service id) and `response` (parsed body).
    """
    _trace: list[dict[str, Any]] = []
    _req_id = f"demo-r{req_idx}"
    async with httpx.AsyncClient(timeout=5.0) as _http:
        for _svc_name, _kind, _mu in SERVICE_CHAIN:
            del _mu  # only used for the spawner
            _payload = {
                "req_id": _req_id,
                "kind": _kind,
                "operation": "demo",
                "client_id": "demo-user",
                "submitted_ts": 0.0,
            }
            _body = await _call_one(_http, urls[_svc_name], _payload)
            _trace.append({"svc": _svc_name, "response": _body})
    return _trace


def _save_traces(traces: list[list[dict[str, Any]]]) -> Path:
    """Write the full chain trace to disk under `_sandbox/demo_composite/`.

    Args:
        traces (list[list[dict[str, Any]]]): all per-request chain traces.

    Returns:
        Path: file path the trace was written to (overwritten on rerun).
    """
    _scratch = Path("_sandbox/demo_composite")
    if _scratch.exists():
        shutil.rmtree(_scratch)
    _scratch.mkdir(parents=True, exist_ok=True)
    _out = _scratch / "chain.json"
    with _out.open("w", encoding="utf-8") as _fh:
        json.dump(traces, _fh, indent=4)
    return _out


def _print_chain(req_idx: int, trace: list[dict[str, Any]]) -> None:
    """Pretty-print one chain trace to stdout.

    Args:
        req_idx (int): zero-based request index (rendered as 1-based for the heading).
        trace (list[dict[str, Any]]): per-step trace as produced by `_run_chain`.
    """
    print(f"\n=== request {req_idx + 1} chain ===")
    for _step in trace:
        print(f"  -> {_step['svc']:<10} status={_step['response'].get('_status')}")


async def _drive(urls: dict[str, str]) -> list[list[dict[str, Any]]]:
    """Drive `DEMO_REQUESTS` chains in sequence and return every trace.

    Args:
        urls (dict[str, str]): `svc_id -> base URL` map yielded by `bring_up_mesh`.

    Returns:
        list[list[dict[str, Any]]]: one chain trace per request, in submission order.
    """
    _all: list[list[dict[str, Any]]] = []
    for _i in range(DEMO_REQUESTS):
        _trace = await _run_chain(_i, urls)
        _print_chain(_i, _trace)
        _all.append(_trace)
    return _all


def main() -> None:
    """Mount the three atomic services, chain three requests, save the trace, tear down.

    Returns:
        None. Side effects: prints each chain to stdout and writes the trace JSON under `_sandbox/demo_composite/`.
    """
    _specs = _build_specs()
    with bring_up_mesh(_specs, base_port=DEMO_BASE_PORT) as _urls:
        _traces = asyncio.run(_drive(_urls))
    _out = _save_traces(_traces)
    print(f"\n=== trace saved to {_out} ===")


if __name__ == "__main__":
    main()
