"""Bridge async service classes (asyncio.Semaphore, async handlers) onto Flask/WSGI.

Flask handlers run synchronously inside a waitress worker thread. The async service classes (`AtomicService`, `CompositeService`, `WorkflowEngine`) build their `c` / `K` admission gates on `asyncio.Semaphore` + a shared in-flight counter; those primitives only work when every consumer shares the same event loop. Spawning a fresh loop per request via `asyncio.run` would isolate each request and break gate sharing.

`AsyncLoopThread` owns one daemon thread that hosts a single asyncio loop for the whole Flask app lifetime. Request handlers submit coroutines via `submit(coro)` and block on the result. The bridge plus the existing async service classes give Flask the same `c` / `K` semantics FastAPI gets natively.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class AsyncLoopThread:
    """One asyncio loop running on a dedicated daemon thread.

    Attributes:
        loop (asyncio.AbstractEventLoop): the loop callers submit coroutines to.
    """

    def __init__(self) -> None:
        """Spawn the daemon thread and wait until its loop is running."""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _serve(self) -> None:
        """Daemon-thread body: create a new event loop, signal readiness, run forever."""
        _loop = asyncio.new_event_loop()
        self._loop = _loop
        asyncio.set_event_loop(_loop)
        self._ready.set()
        _loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The running loop. Raises `RuntimeError` if accessed before the worker thread starts."""
        if self._loop is None:
            _msg = "AsyncLoopThread.loop accessed before the worker thread initialised"
            raise RuntimeError(_msg)
        return self._loop

    def submit(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine on the worker loop and block until it resolves.

        For sync callers (Flask / WSGI handlers). Async callers use `submit_async` so their own loop stays free.

        Args:
            coro (Coroutine[Any, Any, T]): coroutine to drive.

        Returns:
            T: whatever the coroutine returned.

        Raises:
            BaseException: re-raises whatever the coroutine raised.
        """
        _fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return _fut.result()

    async def submit_async(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run a coroutine on the worker loop; await the result from the caller's loop.

        The async sibling of `submit`: instead of blocking the calling thread, it suspends the calling coroutine so the caller's own event loop stays free to do other work while the worker loop drives `coro`. For async callers (FastAPI / ASGI handlers).

        Args:
            coro (Coroutine[Any, Any, T]): coroutine to drive on the worker loop.

        Returns:
            T: whatever the coroutine returned.

        Raises:
            BaseException: re-raises whatever the coroutine raised.
        """
        _fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return await asyncio.wrap_future(_fut)

    def shutdown(self) -> None:
        """Stop the loop and join the worker thread."""
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5.0)


__all__ = ["AsyncLoopThread"]
