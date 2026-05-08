"""`User`: one synthetic user driving a sequence of requests through a `Sender`.

The class is an async context manager: entering opens the `httpx.AsyncClient`, exiting closes it. Inside the `async with` block, callers drive the user with `run_one()` (one request) or `run_until_stop(max=...)` (loop until the `StopGuard` trips).

Each request has a kind drawn from a seeded `random.Random` per the kind probabilities (`p_alarm` + `p_med_ansys`) given at construction. The catalogue + adaptation strategy decide whether `inject_failure` is set on a given request; until they are wired, every emitted request has `inject_failure=None`.
"""

from __future__ import annotations

import random
from types import TracebackType
from typing import Self

import httpx

from src.experimental.common.payload.request import (
    KIND_ALARM,
    KIND_MED_ANSYS,
)
from src.experimental.prototype.client.guard import StopGuard, StopReason
from src.experimental.prototype.client.records import RequestRecord
from src.experimental.prototype.client.sender import Sender
from src.experimental.prototype.client.stats import Stats

# Runtime fallbacks for data/config/method/prototype/client.json::sender.{kind_probability.alarm, payload_size_bytes}.
_DFLT_P_ALARM = 0.25
_DFLT_PAYLOAD_BYTES = 1024


class User:
    """One synthetic user issuing requests against an HTTP target.

    Owns: the user identity (`client_id`), the `httpx.AsyncClient` (opened on `__aenter__`, closed on `__aexit__`), the `Sender` that builds + dispatches each request, the `StopGuard` that decides when to halt, and the `Stats` aggregator. The seeded RNG is used for kind selection only; payload-blob bytes come from `Sender.build_request` which uses a separate seed configured at sender construction.

    Attributes:
        _client_id (str): synthetic-user identifier.
        _base_url (str): target base URL (e.g. `http://127.0.0.1:8001`).
        _endpoint_path (str): path component appended to `_base_url`.
        _payload_size_bytes (int): blob size for every request.
        _seed (int | None): seed for the kind-selection RNG.
        _p_alarm (float): probability of the next request being a `KIND_ALARM` (rest go to `KIND_MED_ANSYS`).
        _timeout_s (float): per-request wall-clock cap.
        _guard (StopGuard): caller-supplied stop controller.
        _stats (Stats): caller-supplied aggregator (or a fresh one on default).
        _client (httpx.AsyncClient | None): live client; non-None only inside the async-with body.
        _sender (Sender | None): live sender; non-None only inside the async-with body.
        _rng (random.Random): seeded kind-selection RNG; reseeded on each `__aenter__` so a re-entered context replays deterministically.
        sequential_req_ids (bool): when True, `run_one` mints sequential ids of the form `<client_id>-r<NNNN>` via `next_req_id`. When False (default), `Sender.build_request` mints UUID4 hex ids. Sequential mode is a feature for functional tests + experimental runs that prefer human-readable ids.
        next_req_idx (int): monotonic counter consumed by `next_req_id`; public so callers can inspect or reset it between phases of an experiment.
    """

    def __init__(self,
                 client_id: str,
                 base_url: str,
                 endpoint_path: str = "/",
                 payload_size_bytes: int = _DFLT_PAYLOAD_BYTES,
                 seed: int | None = None,
                 p_alarm: float = _DFLT_P_ALARM,
                 timeout_s: float = 5.0,
                 guard: StopGuard | None = None,
                 stats: Stats | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 sequential_req_ids: bool = False) -> None:
        """Configure one synthetic user (no resources opened yet).

        Args:
            client_id (str): synthetic-user identifier.
            base_url (str): target base URL.
            endpoint_path (str, optional): appended to `base_url` to form the POST target. Defaults to `"/"`.
            payload_size_bytes (int, optional): blob size in bytes. Defaults to 1024.
            seed (int | None, optional): kind-selection RNG seed. Defaults to None.
            p_alarm (float, optional): probability of the next request being `KIND_ALARM`. Defaults to 0.25 (matches Weyns-Iftikhar 2016).
            timeout_s (float, optional): per-request wall-clock cap. Defaults to 5.0.
            guard (StopGuard | None, optional): caller-supplied stop controller. Defaults to None, which builds a guard with default thresholds.
            stats (Stats | None, optional): caller-supplied aggregator. Defaults to None, which builds a fresh `Stats`.
            transport (httpx.AsyncBaseTransport | None, optional): test seam for in-memory transports. Defaults to None (real TCP via the default httpx transport). Production code never sets this.
            sequential_req_ids (bool, optional): if True, `run_one` mints sequential ids via `next_req_id` instead of letting the sender mint UUIDs. Defaults to False.
        """
        self._client_id = client_id
        self._base_url = base_url
        self._endpoint_path = endpoint_path
        self._payload_size_bytes = payload_size_bytes
        self._seed = seed
        self._p_alarm = p_alarm
        self._timeout_s = timeout_s
        if guard is None:
            self._guard = StopGuard()
        else:
            self._guard = guard
        if stats is None:
            self._stats = Stats()
        else:
            self._stats = stats
        # Test seam: production passes None and httpx uses the real-TCP default.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._sender: Sender | None = None
        self._rng = random.Random(seed)
        self.sequential_req_ids = sequential_req_ids
        self.next_req_idx = 0

    @property
    def stats(self) -> Stats:
        """Return the live aggregator so the caller can read summaries.

        Returns:
            Stats: the user's aggregator.
        """
        return self._stats

    @property
    def guard(self) -> StopGuard:
        """Return the live stop controller.

        Returns:
            StopGuard: the user's guard.
        """
        return self._guard

    async def __aenter__(self) -> Self:
        """Open the underlying `httpx.AsyncClient` and bind the sender.

        Returns:
            Self: this user, ready to drive requests inside the async-with body.
        """
        self._rng = random.Random(self._seed)

        if self._transport is None:
            self._client = httpx.AsyncClient(base_url=self._base_url,
                                             timeout=self._timeout_s)
        else:
            self._client = httpx.AsyncClient(transport=self._transport,
                                             base_url=self._base_url,
                                             timeout=self._timeout_s)

        self._sender = Sender(client=self._client,
                              client_id=self._client_id,
                              endpoint=self._endpoint_path,
                              payload_size_bytes=self._payload_size_bytes,
                              blob_seed=self._seed,
                              timeout_s=self._timeout_s)
        return self

    async def __aexit__(self,
                        _exc_type: type[BaseException] | None,
                        _exc: BaseException | None,
                        _tb: TracebackType | None) -> None:
        """Close the `httpx.AsyncClient` and clear the sender."""
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._sender = None

    async def run_one(self) -> RequestRecord:
        """Send exactly one request and update stats and the guard.

        Returns:
            RequestRecord: the completed record (also stored in `stats`).

        Raises:
            RuntimeError: if called outside the `async with` body (no live `Sender`).
        """
        if self._sender is None:
            _msg = "User.run_one() requires the async-with body to be active"
            raise RuntimeError(_msg)
        _kind = self._draw_kind()
        if self.sequential_req_ids:
            _req_id = self.next_req_id()
        else:
            _req_id = None
        _request = self._sender.build_request(kind=_kind,
                                              inject_failure=None,
                                              req_id=_req_id)
        _record = await self._sender.send(_request)
        self._stats.update(_record)
        self._guard.update(_record, self._stats)
        return _record

    async def run_until_stop(self, max_iters: int | None = None) -> list[RequestRecord]:
        """Loop `run_one()` until the guard trips or the iteration cap is reached.

        Args:
            max_iters (int | None, optional): hard upper bound on iterations as a safety net (the guard's own `max_requests` is the primary stop). Defaults to None, which derives the cap from the guard's `max_requests` so the loop matches the configured budget.

        Returns:
            list[RequestRecord]: every emitted record in submission order.
        """
        if max_iters is None:
            _cap = self._guard.max_requests
        else:
            _cap = max_iters
        _records: list[RequestRecord] = []
        # Single sentinel: keep going while there is budget left AND the guard has not tripped.
        # `run_one` advances the guard, so the post-call state is observed on the next check.
        while len(_records) < _cap and self._guard.stop_reason == StopReason.NONE:
            _record = await self.run_one()
            _records.append(_record)
        return _records

    def next_req_id(self) -> str:
        """Mint the next sequential request id of the form `<client_id>-r<NNNN>`.

        Public so callers can drive functional tests + experimental runs that prefer human-readable ids over UUIDs. Advances `next_req_idx` by one per call.

        Returns:
            str: the request id; the internal counter is now `previous + 1`.
        """
        _idx = self.next_req_idx
        self.next_req_idx += 1
        return f"{self._client_id}-r{_idx:04d}"

    def _draw_kind(self) -> str:
        """Draw the next request kind from the seeded RNG using `_p_alarm`.

        Returns:
            str: `KIND_ALARM` with probability `_p_alarm`, otherwise `KIND_MED_ANSYS`.
        """
        if self._rng.random() < self._p_alarm:
            return KIND_ALARM
        return KIND_MED_ANSYS
