"""Tests for `src.experimental.prototype.runtime.async_loop`.

**TestRunAsyncSafe**:

- `test_no_ambient_loop`: with no live loop, the coroutine runs via `asyncio.run` and the return value comes back.
- `test_with_ambient_loop`: with a live loop, the coroutine runs on a worker thread and the return value comes back synchronously.
- `test_propagates_exception`: exceptions raised inside the coroutine surface on the calling thread.
- `test_factory_in_worker`: the factory runs exactly once, on the worker thread, not the caller's.
- `test_returns_dict`: a coroutine returning a dict round-trips unchanged.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from src.experimental.prototype.runtime.async_loop import run_async_safe


async def _make_int() -> int:
    """Trivial coroutine returning 42 after a single yield."""
    await asyncio.sleep(0)
    return 42


async def _make_str() -> str:
    """Trivial coroutine returning `"ok"` after a single yield."""
    await asyncio.sleep(0)
    return "ok"


async def _make_dict() -> dict[str, int]:
    """Trivial coroutine returning `{"answer": 42}`."""
    return {"answer": 42}


async def _make_raises() -> None:
    """Coroutine that yields once and then raises `ValueError("boom")`."""
    await asyncio.sleep(0)
    _msg = "boom"
    raise ValueError(_msg)


async def _outer_str() -> str:
    """Re-entry helper for the ambient-loop branch: drive `_make_str` through `run_async_safe` and return its value."""
    return run_async_safe(_make_str)


async def _outer_with_factory(factory: Callable[[], Coroutine[Any, Any, int]]) -> int:
    """Re-entry helper that runs `run_async_safe(factory)` from inside a live event loop.

    Args:
        factory (Callable[[], Coroutine[Any, Any, int]]): the coroutine factory to drive.

    Returns:
        int: whatever the driven coroutine resolved to.
    """
    return run_async_safe(factory)


class _ThreadLoggingFactory:
    """Coroutine factory that records each call's thread id.

    Used by `test_factory_in_worker` to confirm the factory runs on the worker thread spawned by `run_async_safe`, not on the calling thread.

    Attributes:
        threads (list[int]): one entry per `__call__`; the thread id at the moment the factory built the coroutine.
    """

    def __init__(self) -> None:
        """Initialise an empty thread-id log."""
        self.threads: list[int] = []

    def __call__(self) -> Coroutine[Any, Any, int]:
        """Record the calling thread, then return a fresh coroutine.

        Returns:
            Coroutine[Any, Any, int]: a fresh `_make_int` coroutine that resolves to 42.
        """
        self.threads.append(threading.get_ident())
        return _make_int()


class TestRunAsyncSafe:
    """Sync entry that survives an ambient event loop."""

    def test_no_ambient_loop(self) -> None:
        """With no live loop on the calling thread, `run_async_safe` resolves the coroutine via `asyncio.run` and returns its value."""
        _val = run_async_safe(_make_int)
        assert _val == 42

    def test_with_ambient_loop(self) -> None:
        """With an ambient loop on the calling thread, `run_async_safe` spawns a worker thread, drives the coroutine to completion there, and returns the value synchronously."""
        _val = asyncio.run(_outer_str())
        assert _val == "ok"

    def test_propagates_exception(self) -> None:
        """Exceptions raised inside the driven coroutine surface on the calling thread."""
        with pytest.raises(ValueError, match="boom"):
            run_async_safe(_make_raises)

    def test_factory_in_worker(self) -> None:
        """The factory is called exactly once, on the worker thread (not the caller's), so the coroutine binds to the worker's event loop."""
        _factory = _ThreadLoggingFactory()
        _calling = threading.get_ident()
        _val = asyncio.run(_outer_with_factory(_factory))
        assert _val == 42
        assert len(_factory.threads) == 1
        assert _factory.threads[0] != _calling

    def test_returns_dict(self) -> None:
        """A dict-returning coroutine round-trips through `run_async_safe` unchanged."""
        _out = run_async_safe(_make_dict)
        assert _out == {"answer": 42}
