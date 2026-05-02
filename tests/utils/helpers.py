"""
Module helpers.py
=================

Shared fixtures, builders, and callable mocks for service / instance / client tests.
"""
# native python modules
import json
from typing import Any, Dict, List, Optional, Tuple

# web stack (used by the client-side helpers)
import httpx

# modules for tests
from src.experiment.architecture import TasArchitecture
from src.experiment.client.records import RequestRecord
from src.experiment.wire import SvcRegistry
from src.experiment.services import LOG_COLUMNS, SvcReq, SvcResp, SvcSpec


# ---------------------------------------------------------------- service-side


class _SpecBuilder:
    """*_SpecBuilder* callable that builds a `SvcSpec` with sensible defaults; tests call it like `spec_builder(name=...)`."""

    def __call__(self, *,
                 name: str = "MAS_{1}",
                 role: str = "atomic",
                 port: int = 8006,
                 mu: float = 1000.0,
                 epsilon: float = 0.0,
                 c: int = 1,
                 K: int = 10,
                 seed: int = 42) -> SvcSpec:
        """*__call__()* return a `SvcSpec` with the given (or default) knobs.

        Args:
            name (str): artifact key. Defaults to `"MAS_{1}"`.
            role (str): registry role tag. Defaults to `"atomic"`.
            port (int): TCP port. Defaults to 8006.
            mu (float, req/s): service rate. Defaults to 1000.0.
            epsilon (float): Bernoulli failure probability. Defaults to 0.0.
            c (int): parallel handlers. Defaults to 1.
            K (int): admission ceiling. Defaults to 10.
            seed (int): per-service RNG seed. Defaults to 42.

        Returns:
            SvcSpec: built spec.
        """
        specs = SvcSpec(name=name,
                        role=role,
                        port=port,
                        mu=mu,
                        epsilon=epsilon,
                        c=c,
                        K=K,
                        seed=seed)
        return specs


async def _no_forward(_tgt: str, _req: SvcReq) -> SvcResp:
    """*_no_forward()* test-side `ext_fwd` that fails loudly when reached.

    Use as the `ext_fwd` argument for handlers that should never delegate (terminal services or in-process-only chains). Reaching this function in a test means the routing logic took an unexpected branch.

    Args:
        _tgt (str): downstream target name; reproduced verbatim in the failure message.
        _req (SvcReq): inbound request (ignored).

    Raises:
        AssertionError: always; carries the offending target name.

    Returns:
        SvcResp: never returns.
    """
    raise AssertionError(f"unexpected external forward to {_tgt!r}")


class _RecordedForward:
    """*_RecordedForward* test-side `ext_fwd` that captures every `(target, req_id)` pair into an externally-owned list and returns a synthetic success response.

    Pair this with `tests/utils/helpers.py::_no_forward` when the test needs to assert *which* targets the handler tried to delegate to.
    """

    def __init__(self, calls: List[Tuple[str, str]]) -> None:
        """*__init__()* bind the externally-owned list that will receive `(target, req_id)` tuples.

        Args:
            calls (List[Tuple[str, str]]): caller-owned accumulator; the test reads it after the handler runs.
        """
        self.calls = calls

    async def __call__(self, target: str, req: SvcReq) -> SvcResp:
        """*__call__()* append `(target, req.req_id)` to `self.calls` and synthesise a success response.

        Args:
            target (str): downstream target name passed by the calling handler.
            req (SvcReq): inbound request; only `req_id` is read.

        Returns:
            SvcResp: status-equivalent body with `success=True` and `message="recorded"`.
        """
        self.calls.append((target, req.req_id))
        return SvcResp(req_id=req.req_id,
                       srv_name=target,
                       success=True,
                       message="recorded")


def _seed_one_row_per_tas_member(arch: TasArchitecture) -> None:
    """*_seed_one_row_per_tas_member()* prime every deployed TAS member with a single CSV-shaped log row so that downstream flush / counting tests see at least one entry per member.

    Iterates `arch.apps` filtered to the `TAS_` prefix; deduplicates by `id(app.state.tas_components)` since the six TAS_{i} keys share one composite app, then appends one zero-filled row per `LOG_COLUMNS` field to each member context's log.

    Args:
        arch (TasArchitecture): live architecture instance whose member logs are mutated in place.
    """
    _seen: set = set()
    for _name, _app in arch.apps.items():
        if not _name.startswith("TAS_"):
            continue
        _members = _app.state.tas_components
        if id(_members) in _seen:
            continue
        _seen.add(id(_members))
        for _ctx in _members.values():
            _ctx.log.append({_col: 0 for _col in LOG_COLUMNS})


# ----------------------------------------------------------------- client-side


def _one_svc_registry() -> SvcRegistry:
    """*_one_svc_registry()* minimal `SvcRegistry` with a single composite-client entry.

    Used by client-side tests that just need an entry-service URL resolver and don't care about any other artifact in the mesh.

    Returns:
        SvcRegistry: registry holding `TAS_{1}` at `host=127.0.0.1`, `port=9000`, role `composite_client`.
    """
    _spec: Dict[str, Any] = {}
    _spec["host"] = "127.0.0.1"
    _spec["base_port"] = 9000
    _spec["service_registry"] = {
        "TAS_{1}": {"port_offset": 0, "role": "composite_client"},
    }
    _reg = SvcRegistry.from_config(_spec)
    return _reg


def _make_mock_async_client(handler) -> httpx.AsyncClient:
    """*_make_mock_async_client()* wrap `handler` in `httpx.MockTransport` and hand back a configured `AsyncClient`.

    Centralises the `httpx.AsyncClient(transport=MockTransport(handler), base_url=...)` boilerplate that otherwise repeats across every client-side test.

    Args:
        handler: callable taking `httpx.Request` and returning `httpx.Response`.

    Returns:
        httpx.AsyncClient: client routed at `http://test`; the caller owns the lifetime (`async with` or explicit `aclose()`).
    """
    _transport = httpx.MockTransport(handler)
    _client = httpx.AsyncClient(transport=_transport,
                                base_url="http://test")
    return _client


def _ok_httpx_handler(request: httpx.Request) -> httpx.Response:
    """*_ok_httpx_handler()* baseline-success mock handler for happy-path client tests.

    Args:
        request (httpx.Request): inbound mock request; only `X-Request-Id` is echoed back.

    Returns:
        httpx.Response: status 200 with body `{"req_id", "srv_name", "success": True, "message": "ok"}`.
    """
    _body: Dict[str, Any] = {}
    _body["req_id"] = request.headers.get("X-Request-Id", "x")
    _body["srv_name"] = "TAS_{1}"
    _body["success"] = True
    _body["message"] = "ok"
    _resp = httpx.Response(200, json=_body)
    return _resp


def _err_503_httpx_handler(request: httpx.Request) -> httpx.Response:
    """*_err_503_httpx_handler()* permanent-overload mock handler used to drive guard-trip tests.

    Args:
        request (httpx.Request): inbound mock request (ignored).

    Returns:
        httpx.Response: status 503 with body `{"detail": "overloaded"}`.
    """
    _body: Dict[str, Any] = {"detail": "overloaded"}
    _resp = httpx.Response(503, json=_body)
    return _resp


class _StatefulHttpxHandler:
    """*_StatefulHttpxHandler* mock handler that succeeds for the first `n_ok` calls then fails forever.

    Used to exercise mid-schedule guard trips: configure with `n_ok=0` for an immediate 503 storm, or with `n_ok > 0` to delay the trip until a known number of healthy responses have flowed.
    """

    def __init__(self, n_ok: int) -> None:
        """*__init__()* fix the success budget and reset the call counter.

        Args:
            n_ok (int): number of initial requests that get the 200 response before the handler flips to 503.
        """
        self.n_ok = n_ok
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """*__call__()* return 200 while `self.calls <= self.n_ok`, else 503; bumps the counter on every call.

        Args:
            request (httpx.Request): inbound mock request; `X-Request-Id` is echoed in the 200 body.

        Returns:
            httpx.Response: 200 with the OK body, or 503 with `{"detail": "overloaded"}`.
        """
        self.calls += 1
        if self.calls <= self.n_ok:
            _ok_body: Dict[str, Any] = {}
            _ok_body["req_id"] = request.headers.get("X-Request-Id", "x")
            _ok_body["srv_name"] = "TAS_{1}"
            _ok_body["success"] = True
            _ok_body["message"] = "ok"
            return httpx.Response(200, json=_ok_body)
        _err_body: Dict[str, Any] = {"detail": "overloaded"}
        return httpx.Response(503, json=_err_body)


class _RequestCapture:
    """*_RequestCapture* mock handler that records the inbound JSON body and headers, then synthesises a success response.

    Tests poke `self.body` and `self.headers` directly after the call to assert what the SUT actually put on the wire.
    """

    def __init__(self) -> None:
        """*__init__()* allocate empty capture stores ready for the first call to populate."""
        self.body: Dict[str, Any] = {}
        self.headers: Dict[str, str] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """*__call__()* copy `request.content` (parsed JSON) and `request.headers` into the capture stores; echo a 200 response carrying the same `req_id`.

        Args:
            request (httpx.Request): inbound mock request.

        Returns:
            httpx.Response: status 200 with body `{"req_id", "srv_name": "TAS_{1}", "success": True, "message": "ok"}`.
        """
        self.body.update(json.loads(request.content))
        self.headers.update(dict(request.headers))
        _resp_body: Dict[str, Any] = {}
        _resp_body["req_id"] = self.body["req_id"]
        _resp_body["srv_name"] = "TAS_{1}"
        _resp_body["success"] = True
        _resp_body["message"] = "ok"
        return httpx.Response(200, json=_resp_body)


def _make_records(*,
                  n: int = 1,
                  kind: str = "k",
                  status_code: int = 200,
                  success: bool = True,
                  rts_ms: Optional[List[float]] = None,
                  id_prefix: str = "r") -> List[RequestRecord]:
    """*_make_records()* unified `RequestRecord` factory for client-side tests.

    Default call yields one OK record. Pass `rts_ms=[...]` to inject explicit per-record latencies (overrides `n`); pass `status_code=503, success=False, id_prefix="e"` to build infra-failure records. Replaces the per-test `_ok` / `_infra` / `_ok_with_rt` / `_build_ok_records` helpers that were previously duplicated.

    Args:
        n (int): record count when `rts_ms is None`. Defaults to 1.
        kind (str): kind label for every record. Defaults to `"k"`.
        status_code (int): HTTP status for every record. Defaults to 200.
        success (bool): body-level success flag for every record. Defaults to True.
        rts_ms (Optional[List[float]]): when supplied, overrides `n` and assigns each record `recv_ts = rts_ms[i] / 1000` (with `send_ts = 0.0`).
        id_prefix (str): `req_id` becomes `f"{id_prefix}{i}"`. Defaults to `"r"`.

    Returns:
        List[RequestRecord]: built records in index order.
    """
    if rts_ms is None:
        _count = n
        _times: List[Optional[float]] = [None] * _count
    else:
        _count = len(rts_ms)
        _times = [float(_t) for _t in rts_ms]
    _recs: List[RequestRecord] = []
    for _i in range(_count):
        _rt_ms = _times[_i]
        if _rt_ms is None:
            _send = 0.0
            _recv = 0.0
        else:
            _send = 0.0
            _recv = _rt_ms / 1000.0
        _rec = RequestRecord(req_id=f"{id_prefix}{_i}",
                             kind=kind,
                             send_ts=_send,
                             recv_ts=_recv,
                             status_code=status_code,
                             success=success)
        _recs.append(_rec)
    return _recs
