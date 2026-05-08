"""Tests for `src.experimental.prototype.client.users`.

**TestUser**:

- `test_run_one_echo`: confirms a single request through the in-memory transport produces a `RequestRecord` with `outcome="success"` and updates the live `Stats`.
- `test_run_until_stop`: confirms `run_until_stop` halts when the request budget is reached so the cap is respected end-to-end.
- `test_run_one_outside_ctx`: confirms `run_one()` outside the `async with` body raises so callers cannot accidentally use a closed sender.
- `test_seeded_kinds`: confirms two users with the same seed draw the same kind sequence so flag-driven experiments stay bit-reproducible.
- `test_real_localhost`: confirms the no-transport (production) branch reaches a stdlib `ThreadingHTTPServer` over real localhost TCP, exercising the path that production runs use.
- `test_explicit_stats_and_cap`: confirms callers can supply their own `Stats` aggregator and an explicit `max_iters` so external orchestration paths bypass the auto-cap from the guard's budget.
- `test_sequential_req_ids`: confirms the opt-in `sequential_req_ids=True` mode mints `<client_id>-r<NNNN>` ids via `User.next_req_id`, so functional + experimental runs can use human-readable ids instead of UUIDs.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.client.guard import StopGuard, StopReason
from src.experimental.prototype.client.stats import Stats
from src.experimental.prototype.client.users import User
from tests.utils.exp.apps import build_echo_app, start_echo_server


def _make_app() -> FastAPI:
    """Build the canonical echo app used across every in-memory test in this module.

    Returns:
        FastAPI: echo app with one POST `/` handler.
    """
    return build_echo_app()


class TestUser:
    """One synthetic user driving requests through `Sender`, `StopGuard`, and `Stats`."""

    def test_run_one_echo(self) -> None:
        """A single request through the in-memory transport produces a `RequestRecord` with `outcome="success"` and the live `Stats` aggregator records the call, demonstrating the User wires Sender + Stats correctly."""
        async def _exercise() -> None:
            _transport = make_test_transport(_make_app(), "fastapi")
            async with User(client_id="u1",
                            base_url="http://testserver",
                            payload_size_bytes=64,
                            seed=42,
                            transport=_transport) as _user:
                _record = await _user.run_one()
                assert _record.outcome == "success"
                assert _record.status_code == 200
                assert _user.stats.count() == 1
        asyncio.run(_exercise())

    def test_run_until_stop(self) -> None:
        """`run_until_stop()` (no `max_iters` argument) keeps issuing requests until the guard's `max_requests` budget trips, returning every emitted record. With no explicit cap the user derives its iteration limit from `guard.max_requests`, so the loop matches the budget."""
        async def _exercise() -> None:
            _transport = make_test_transport(_make_app(), "fastapi")
            _guard = StopGuard(max_requests=3)
            async with User(client_id="u1",
                            base_url="http://testserver",
                            payload_size_bytes=64,
                            seed=42,
                            guard=_guard,
                            transport=_transport) as _user:
                _records = await _user.run_until_stop()
                assert len(_records) == 3
                assert _user.guard.stop_reason == StopReason.REQUEST_BUDGET
                # second call must observe the sticky stop-reason and return immediately
                _again = await _user.run_until_stop()
                assert _again == []
        asyncio.run(_exercise())

    def test_run_one_outside_ctx(self) -> None:
        """Calling `run_one()` before `__aenter__` (or after `__aexit__`) raises `RuntimeError`, so callers never accidentally exercise a closed sender."""
        async def _exercise() -> None:
            _user = User(client_id="u1", base_url="http://testserver")
            with pytest.raises(RuntimeError, match="async-with body"):
                await _user.run_one()
        asyncio.run(_exercise())

    def test_real_localhost(self) -> None:
        """Constructing a `User` with `transport=None` (the default) takes the real-TCP code path: the test stands up a stdlib `ThreadingHTTPServer` echo on a free localhost port, drives one request through `User.run_one`, and confirms the round trip succeeds. This is the path production runs use; the in-memory transport in other tests is a test seam only."""
        _server, _thread, _base_url = start_echo_server()
        try:
            async def _exercise() -> str:
                async with User(client_id="u1",
                                base_url=_base_url,
                                payload_size_bytes=64,
                                seed=42) as _user:
                    _record = await _user.run_one()
                    return _record.outcome
            _outcome = asyncio.run(_exercise())
            assert _outcome == "success"
        finally:
            _server.shutdown()
            _server.server_close()
            _thread.join(timeout=2.0)

    def test_explicit_stats_and_cap(self) -> None:
        """Constructing a `User` with an explicit `Stats` instance and calling `run_until_stop(max_iters=N)` exercises both the user-supplied-stats path and the explicit-cap path; the user emits exactly the requested number of records when the cap is the binding constraint."""
        async def _exercise() -> int:
            _transport = make_test_transport(_make_app(), "fastapi")
            _stats = Stats(max_records=100)
            async with User(client_id="u1",
                            base_url="http://testserver",
                            payload_size_bytes=64,
                            seed=42,
                            guard=StopGuard(max_requests=1000),
                            stats=_stats,
                            transport=_transport) as _user:
                _records = await _user.run_until_stop(max_iters=2)
                return len(_records)
        _count = asyncio.run(_exercise())
        assert _count == 2

    def test_seeded_kinds(self) -> None:
        """Two users with the same `seed` draw the same kind sequence, demonstrating the kind-selection RNG is seeded deterministically so flag-driven experiments stay bit-reproducible."""
        async def _exercise() -> tuple[list[str], list[str]]:
            _transport_a = make_test_transport(_make_app(), "fastapi")
            _transport_b = make_test_transport(_make_app(), "fastapi")
            async with User(client_id="u1",
                            base_url="http://testserver",
                            payload_size_bytes=32,
                            seed=42,
                            p_alarm=0.5,
                            guard=StopGuard(max_requests=10),
                            transport=_transport_a,
            ) as _ua, User(client_id="u1",
                           base_url="http://testserver",
                           payload_size_bytes=32,
                           seed=42,
                           p_alarm=0.5,
                           guard=StopGuard(max_requests=10),
                           transport=_transport_b,
            ) as _ub:
                _ra = await _ua.run_until_stop(max_iters=10)
                _rb = await _ub.run_until_stop(max_iters=10)
                return [_r.kind for _r in _ra], [_r.kind for _r in _rb]
        _kinds_a, _kinds_b = asyncio.run(_exercise())
        assert _kinds_a == _kinds_b
        assert len(_kinds_a) == 10

    def test_sequential_req_ids(self) -> None:
        """With `sequential_req_ids=True`, `run_one` mints ids via `User.next_req_id` of the form `<client_id>-r<NNNN>`, advancing `next_req_idx` monotonically; the public counter is also visible to the caller."""
        async def _exercise() -> tuple[list[str], int]:
            _transport = make_test_transport(_make_app(), "fastapi")
            async with User(client_id="u9",
                            base_url="http://testserver",
                            payload_size_bytes=32,
                            seed=42,
                            guard=StopGuard(max_requests=3),
                            transport=_transport,
                            sequential_req_ids=True) as _user:
                _records = await _user.run_until_stop()
                _ids = [_r.req_id for _r in _records]
                return _ids, _user.next_req_idx
        _ids, _next = asyncio.run(_exercise())
        assert _ids == ["u9-r0000", "u9-r0001", "u9-r0002"]
        assert _next == 3
