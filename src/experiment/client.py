# -*- coding: utf-8 -*-
"""
Module client.py
================

Client simulator for the architectural experiment. Sends kind-tagged requests at a deterministic rate, ramps the rate through a configured schedule, and stops on the first cascade signal from the infrastructure layer (503 / timeout / real 500).

Key design choices (see `notes/experiment.md` for rationale):

    - **Deterministic interarrival** via `await asyncio.sleep(1/rate)`. Poisson emerges naturally from downstream routing and service-time variability; not enforced here.
    - **Kind weights from the profile routing matrix**. The CLIENT samples the request kind according to `TAS_{1}`'s routing-row probabilities; the architecture then routes deterministically on `req.kind`.
    - **Sample-count probes**. At each rate in the schedule, send until every kind has `>= min_samples_per_kind` completed requests (or a safety timeout fires), then step to the next rate.
    - **Cascade stop on infrastructure failures only**. Business failures (HTTP 200 with `success=False`) are counted but do NOT stop the ramp; they are the adaptation-target signal we want to measure. Only 503 / timeout / 5xx trigger stop, per the configured cascade rule (rolling-window or fail-fast).
    - **No cost field**. Cost is a domain concept (R3); the client records only what is architecturally observable.

Public API:
    - `InvocationRecord` one client-side measurement with derived failure flags.
    - `CascadeConfig` / `RampConfig` / `ClientConfig` dataclasses.
    - `validate_ramp(ramp)` / `build_ramp_cfg(ramp)` config helpers.
    - `ClientSimulator(client, registry, cfg)` wraps an httpx client.
    - `ClientSimulator.run_ramp()` drives the full schedule and returns per-rate probe stats.
"""
# native python modules
from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections import deque

# data types
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

# web stack
import httpx

# local modules
from src.experiment.payload import generate_payload as _generate_payload
from src.experiment.payload import resolve_size_for_kind as _resolve_size_for_kind
from src.experiment.registry import ServiceRegistry
from src.experiment.services import ServiceRequest


# --- data records ---------------------------------------------------------


@dataclass
class InvocationRecord:
    """*InvocationRecord* one end-to-end client-side measurement.

    Fields are architecturally observable only; domain concepts (cost) live elsewhere. Three failure-mode flags are derived from `(status_code, success)` via helper properties so downstream analysis never has to guess.

    Attributes:
        request_id (str): UUID4 identifying this invocation.
        kind (str): request kind label (e.g. `"TAS_{2}"`).
        send_ts (float): epoch seconds when the client dispatched the request.
        recv_ts (float): epoch seconds when the response was received (or the transport exception was captured).
        status_code (int): HTTP status; `-1` means transport exception (timeout, connection reset, DNS failure, etc.).
        success (bool): body-level `success` flag; business-level outcome.
        size_bytes (int): declared payload size in bytes.
    """

    request_id: str

    kind: str

    send_ts: float = 0.0

    recv_ts: float = 0.0

    # HTTP status; -1 means transport exception (timeout, reset, etc.)
    status_code: int = 0

    # body.success; business-level outcome
    success: bool = False

    size_bytes: int = 0

    @property
    def response_time_s(self) -> float:
        """*response_time_s* non-negative end-to-end latency in seconds."""
        return max(0.0, self.recv_ts - self.send_ts)

    @property
    def infra_failure(self) -> bool:
        """*infra_failure* transport / 5xx failure. Counts toward cascade."""
        return self.status_code < 0 or self.status_code >= 500

    @property
    def business_failure(self) -> bool:
        """*business_failure* HTTP 200 but body says no. Adaptation target; does NOT stop ramp."""
        return self.status_code == 200 and not self.success


@dataclass
class CascadeConfig:
    """*CascadeConfig* when to stop the ramp.

    Attributes:
        mode (str): `"rolling"` (threshold over a rolling window) or `"fail_fast"` (stop on any single infra failure).
        threshold (float): rolling-mode only. Infra-fail rate above this stops the ramp.
        window (int): rolling-mode only. Size of the trailing window in number of requests.
    """

    mode: str = "rolling"

    threshold: float = 0.10

    window: int = 50


@dataclass
class RampConfig:
    """*RampConfig* the rate schedule + per-rate probe knobs + cascade rule.

    Attributes:
        min_samples_per_kind (int): CLT floor; each probe runs until every kind has at least this many successful responses.
        max_probe_window_s (float): safety timeout per probe, in seconds.
        rates (List[float]): monotonically increasing list of target rates (req/s).
        cascade (CascadeConfig): cascade-detection rule applied across probes.
    """

    min_samples_per_kind: int = 32

    max_probe_window_s: float = 60.0

    rates: List[float] = field(default_factory=lambda: [
        1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0
    ])

    cascade: CascadeConfig = field(default_factory=CascadeConfig)


@dataclass
class ClientConfig:
    """*ClientConfig* full client runtime config.

    `kind_weights` maps kind labels (arbitrary strings chosen at the launcher level when it inspects `TAS_{1}`'s routing row) to probabilities summing to 1.

    Attributes:
        entry_service (str): name of the service that receives the client's traffic.
        seed (int): RNG seed for kind sampling + payload generation.
        request_size_bytes (int): fallback size used when `request_sizes_by_kind` has no entry for a kind.
        request_sizes_by_kind (Dict[str, int]): FR-2.3 per-kind payload-size map, read from the method config's `request_size_bytes` block. Keys either match kind labels exactly (e.g. `TAS_{2}`) or use the `<kind>_request` alias form (e.g. `analyse_request`); `resolve_size_for_kind()` resolves both.
        kind_weights (Dict[str, float]): probability mass per request kind for client-side sampling.
        ramp (RampConfig): rate schedule + cascade rule.
    """

    entry_service: str = "TAS_{1}"

    seed: int = 42

    request_size_bytes: int = 256

    request_sizes_by_kind: Dict[str, int] = field(default_factory=dict)

    kind_weights: Dict[str, float] = field(default_factory=dict)

    ramp: RampConfig = field(default_factory=RampConfig)


# --- validation helpers ---------------------------------------------------


def validate_ramp(ramp: Dict[str, Any]) -> None:
    """*validate_ramp()* check the `ramp` sub-dict of `experiment.json`.

    Accepts either `rates` (legacy, direct request-rate list) or `rho_grid` (FR-3.5, target-utilisation list that the orchestrator inverts to rates via the analytic Jackson solver); never both.

    Args:
        ramp (Dict[str, Any]): raw `ramp` block from the method config.

    Raises:
        ValueError: when any knob is out of the supported range or when both `rates` and `rho_grid` are supplied.
    """
    _n = int(ramp.get("min_samples_per_kind", 32))
    if _n < 32:
        raise ValueError(
            f"ramp.min_samples_per_kind must be >= 32 for CLT validity; got {_n}")

    _rates = ramp.get("rates", [])
    _rho_grid = ramp.get("rho_grid", [])
    if _rates and _rho_grid:
        raise ValueError(
            "ramp accepts either 'rates' or 'rho_grid', not both")
    if not _rates and not _rho_grid:
        raise ValueError(
            "ramp must specify 'rates' (legacy) or 'rho_grid' (FR-3.5)")

    if _rates:
        if any(float(_r) <= 0 for _r in _rates):
            raise ValueError("ramp.rates must be a list of positive floats")
        if _rates != sorted(_rates):
            raise ValueError("ramp.rates must be monotonically increasing")

    if _rho_grid:
        if any(not 0.0 < float(_r) < 1.0 for _r in _rho_grid):
            raise ValueError("ramp.rho_grid values must be in (0, 1)")
        if _rho_grid != sorted(_rho_grid):
            raise ValueError("ramp.rho_grid must be monotonically increasing")

    _cas = ramp.get("cascade", {})
    _mode = _cas.get("mode", "rolling")
    if _mode not in ("rolling", "fail_fast"):
        raise ValueError(f"cascade.mode must be 'rolling' or 'fail_fast', got {_mode!r}")
    if _mode == "rolling":
        _w = int(_cas.get("window", 50))
        _t = float(_cas.get("threshold", 0.10))
        if _w < 10:
            raise ValueError(f"cascade.window must be >= 10, got {_w}")
        if not 0.0 < _t < 1.0:
            raise ValueError(f"cascade.threshold must be in (0, 1), got {_t}")


def build_ramp_cfg(ramp: Dict[str, Any]) -> RampConfig:
    """*build_ramp_cfg()* convert the raw `ramp` dict into a `RampConfig`.

    Validates first via `validate_ramp`.

    Args:
        ramp (Dict[str, Any]): raw `ramp` block from the method config.

    Raises:
        ValueError: propagated from `validate_ramp`.

    Returns:
        RampConfig: populated ramp config.
    """
    validate_ramp(ramp)
    _cas = ramp.get("cascade", {})
    return RampConfig(
        min_samples_per_kind=int(ramp.get("min_samples_per_kind", 32)),
        max_probe_window_s=float(ramp.get("max_probe_window_s", 60.0)),
        rates=[float(_r) for _r in ramp.get("rates", [])],
        cascade=CascadeConfig(
            mode=_cas.get("mode", "rolling"),
            threshold=float(_cas.get("threshold", 0.10)),
            window=int(_cas.get("window", 50)),
        ),
    )


# --- cascade detector -----------------------------------------------------


class _CascadeDetector:
    """*_CascadeDetector* rolling-window or fail-fast cascade trip.

    Call `observe(rec)` on each completed invocation; read `tripped`
    after each observation to decide whether to stop the ramp.

    Attributes:
        tripped (bool): `True` once the cascade rule has fired.
        trip_reason (Optional[str]): human-readable trip cause, or `None`.
    """

    def __init__(self, cfg: CascadeConfig):
        """*__init__()* bind the cascade rule and set up the rolling window."""
        self._cfg = cfg
        self._window: Deque[bool] = deque(maxlen=cfg.window)
        self.tripped: bool = False
        self.trip_reason: Optional[str] = None

    def observe(self, rec: InvocationRecord) -> None:
        """*observe()* feed one invocation record into the detector.

        Updates `tripped` / `trip_reason` in place. Idempotent once tripped: further observations are ignored.

        Args:
            rec (InvocationRecord): the completed invocation.
        """
        if self.tripped:
            return
        _infra = rec.infra_failure

        if self._cfg.mode == "fail_fast":
            if _infra:
                self.tripped = True
                self.trip_reason = f"fail_fast: status={rec.status_code}"
            return

        # rolling-window mode
        self._window.append(_infra)
        if len(self._window) < self._cfg.window:
            return
        _rate = sum(self._window) / len(self._window)
        if _rate > self._cfg.threshold:
            self.tripped = True
            self.trip_reason = (f"rolling: {_rate:.3f} > "
                                f"{self._cfg.threshold:.3f} "
                                f"over last {self._cfg.window}")


# --- client simulator -----------------------------------------------------


class ClientSimulator:
    """*ClientSimulator* async request generator + ramp driver.

    Attributes:
        _client (httpx.AsyncClient): shared client (routed to the in-process mesh or a real TCP target).
        _registry (ServiceRegistry): service-name to URL resolver.
        _cfg (ClientConfig): static runtime config.
    """

    def __init__(self, client: httpx.AsyncClient,
                 registry: ServiceRegistry,
                 cfg: ClientConfig):
        """*__init__()* bind httpx client + registry + config; normalise kind weights.

        Args:
            client (httpx.AsyncClient): already-configured async client.
            registry (ServiceRegistry): resolver for `cfg.entry_service`.
            cfg (ClientConfig): runtime config.

        Raises:
            ValueError: if `cfg.kind_weights` sums to <= 0.
        """
        self._client = client
        self._registry = registry
        self._cfg = cfg
        self._rng = random.Random(cfg.seed)

        # sort kinds + weights into parallel lists for rng.choices()
        _kinds = sorted(cfg.kind_weights.keys())
        _total = sum(cfg.kind_weights[_k] for _k in _kinds)
        if _total <= 0:
            raise ValueError("ClientConfig.kind_weights must sum to > 0")
        self._kind_names: List[str] = _kinds
        self._kind_weights_norm: List[float] = [
            cfg.kind_weights[_k] / _total for _k in _kinds
        ]

    def _pick_kind(self) -> str:
        """*_pick_kind()* draw one kind label using the normalised weights."""
        return self._rng.choices(self._kind_names,
                                 weights=self._kind_weights_norm,
                                 k=1)[0]

    async def _send_one(self, kind: str) -> InvocationRecord:
        """*_send_one()* send one kind-tagged request; return an InvocationRecord.

        FR-2.3: generates a real mock payload of the declared per-kind size, attaches it to `ServiceRequest.payload`, and mirrors the byte count in the `X-Request-Size-Bytes` header so downstream services see the same number without re-decoding the body.

        Args:
            kind (str): request kind label; must be a key of the client's weights map.

        Returns:
            InvocationRecord: populated record (status, success, timing).
        """
        # resolve per-kind payload size; fall back to the scalar default
        _size = _resolve_size_for_kind(self._cfg.request_sizes_by_kind,
                                       kind,
                                       default=int(self._cfg.request_size_bytes))
        # generate a real byte payload under the client's seeded RNG so two runs at the same seed produce identical payloads
        _payload = _generate_payload(kind, _size, rng=self._rng)

        # FR-3.7: derive request_id from the client's seeded RNG rather than an unseeded uuid4(), so two runs at the same config seed produce byte-identical request streams (payload + id)
        _rid = str(uuid.UUID(int=self._rng.getrandbits(128), version=4))
        _req = ServiceRequest(request_id=_rid,
                              kind=kind,
                              size_bytes=_size,
                              payload=_payload.to_dict())
        _url = self._registry.build_invoke_url(self._cfg.entry_service)
        _headers = {"X-Request-Id": _req.request_id,
                    "X-Request-Size-Bytes": str(_size),
                    "X-Request-Kind": kind}
        _rec = InvocationRecord(request_id=_req.request_id,
                                kind=kind,
                                size_bytes=_req.size_bytes,
                                send_ts=time.time())
        try:
            _r = await self._client.post(_url,
                                         json=_req.model_dump(),
                                         headers=_headers,
                                         timeout=10.0)
            _rec.recv_ts = time.time()
            _rec.status_code = _r.status_code
            if _r.status_code == 200:
                _body = _r.json()
                _rec.success = bool(_body.get("success", False))
        except Exception:
            _rec.recv_ts = time.time()
            _rec.status_code = -1
            _rec.success = False
        return _rec

    async def _probe_at_rate(self,
                             rate: float,
                             detector: _CascadeDetector
                             ) -> Dict[str, Any]:
        """*_probe_at_rate()* drive one probe at `rate` req/s until every kind reaches `min_samples_per_kind`.

        Exits on any of: sample target met, `max_probe_window_s` elapsed, or the detector tripping.

        Args:
            rate (float): deterministic target rate in req/s.
            detector (_CascadeDetector): shared cascade state across probes.

        Returns:
            Dict[str, Any]: probe summary with keys `rate`, `duration_s`, `samples_per_kind`, `stats_per_kind`, `infra_fail_rate`, `business_fail_rate`, `stopped_reason`.
        """
        _target = int(self._cfg.ramp.min_samples_per_kind)
        _max_s = float(self._cfg.ramp.max_probe_window_s)
        if rate > 0:
            _interarrival = 1.0 / rate
        else:
            _interarrival = _max_s

        _records: List[InvocationRecord] = []
        _in_flight: List[asyncio.Task] = []
        _counts: Dict[str, int] = {_k: 0 for _k in self._kind_names}
        _probe_start = time.time()
        _stop_reason = "samples_reached"

        async def _collect(task: asyncio.Task) -> None:
            """*_collect()* await one in-flight task; update records + counters + cascade."""
            _rec = await task
            _records.append(_rec)
            if _rec.status_code == 200:
                _counts[_rec.kind] = _counts.get(_rec.kind, 0) + 1
            detector.observe(_rec)

        # send loop
        while True:
            # stop conditions
            if detector.tripped:
                _stop_reason = f"cascade: {detector.trip_reason}"
                break
            if time.time() - _probe_start > _max_s:
                _stop_reason = "probe_timeout"
                break
            if all(_c >= _target for _c in _counts.values()):
                break

            # spawn one request; also drain any completed tasks to update counts
            _kind = self._pick_kind()
            _t = asyncio.create_task(self._send_one(_kind))
            _in_flight.append(_t)

            # drain finished tasks opportunistically
            _still_pending: List[asyncio.Task] = []
            for _ift in _in_flight:
                if _ift.done():
                    await _collect(_ift)
                else:
                    _still_pending.append(_ift)
            _in_flight = _still_pending

            await asyncio.sleep(_interarrival)

        # drain any remaining in-flight tasks (bounded by individual timeouts)
        for _t in _in_flight:
            try:
                await _collect(_t)
            except Exception:
                pass

        # compute probe stats per kind
        _duration = time.time() - _probe_start
        _samples_per_kind: Dict[str, int] = dict(_counts)
        _stats_per_kind: Dict[str, Dict[str, float]] = {}
        for _kind in self._kind_names:
            _kind_recs = [_r for _r in _records
                          if _r.kind == _kind and _r.status_code == 200]
            if not _kind_recs:
                _stats_per_kind[_kind] = {"n": 0}
                continue
            _rts = sorted(_r.response_time_s * 1000 for _r in _kind_recs)
            _n = len(_rts)
            _stats_per_kind[_kind] = {
                "n": _n,
                "mean_ms": sum(_rts) / _n,
                "p50_ms": _rts[_n // 2],
                "p95_ms": _rts[min(int(_n * 0.95), _n - 1)],
            }

        _total = len(_records)
        _infra = sum(1 for _r in _records if _r.infra_failure)
        _biz = sum(1 for _r in _records if _r.business_failure)
        if _total > 0:
            _infra_rate = _infra / _total
            _biz_rate = _biz / _total
        else:
            _infra_rate = 0.0
            _biz_rate = 0.0

        return {
            "rate": rate,
            "duration_s": _duration,
            "total": _total,
            "samples_per_kind": _samples_per_kind,
            "stats_per_kind": _stats_per_kind,
            "infra_fail_rate": _infra_rate,
            "business_fail_rate": _biz_rate,
            "stopped_reason": _stop_reason,
            "records": _records,
        }

    async def run_ramp(self) -> Dict[str, Any]:
        """*run_ramp()* drive the full ramp schedule; stop on cascade.

        Returns:
            Dict[str, Any]: `{"probes": [...], "saturation_rate": float|None, "stopped_reason": str}`.
        """
        _detector = _CascadeDetector(self._cfg.ramp.cascade)
        _probes: List[Dict[str, Any]] = []
        _saturation: Optional[float] = None
        _stop = "schedule_complete"

        for _rate in self._cfg.ramp.rates:
            _probe = await self._probe_at_rate(_rate, _detector)
            _probes.append(_probe)
            if _detector.tripped:
                _saturation = _rate
                _stop = f"cascade at rate={_rate}: {_detector.trip_reason}"
                break

        return {
            "probes": _probes,
            "saturation_rate": _saturation,
            "stopped_reason": _stop,
        }
