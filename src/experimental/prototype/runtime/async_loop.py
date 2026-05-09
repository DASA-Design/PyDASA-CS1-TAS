"""Run an async coroutine from sync code, with or without a live event loop.

`asyncio.run(...)` works from scripts but raises inside Jupyter or IPython where a loop is already running. `run_async_safe` handles both cases so callers don't have to check.
"""

from __future__ import annotations

import asyncio
import gc
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeAlias

CoroFactory: TypeAlias = Callable[[], Coroutine[Any, Any, Any]]


def run_async_safe(coro_factory: CoroFactory) -> Any:
    """Drive a coroutine to completion regardless of whether the calling thread already owns an event loop.

    Two branches:

    - No ambient loop: straight `asyncio.run(coro_factory())`.
    - Ambient loop: spawn a worker thread, give it a fresh event loop, drive the coroutine to completion there, and join. The calling thread still sees a synchronous return.

    Args:
        coro_factory (CoroFactory): zero-arg callable producing the coroutine to drive. Re-invoked from inside the worker thread so the coroutine binds to the worker-thread loop.

    Returns:
        Any: whatever the coroutine resolved to.

    Raises:
        BaseException: re-raises any exception that fired inside the coroutine.
    """
    try:
        asyncio.get_running_loop()
        _ambient = True
    except RuntimeError:
        _ambient = False
    if not _ambient:
        return asyncio.run(coro_factory())

    _result_box: list[Any] = [None]
    _error_box: list[BaseException | None] = [None]
    _t = threading.Thread(target=_worker_run_coro,
                          args=(coro_factory,
                                _result_box,
                                _error_box),
                          daemon=False)
    _t.start()
    _t.join()
    _err = _error_box[0]
    if _err is not None:
        raise _err
    _out = _result_box[0]
    _result_box.clear()
    _error_box.clear()
    # Memory hygiene: force GC so the boxes and the worker-thread closure are released before returning.
    gc.collect()
    return _out


def _worker_run_coro(coro_factory: CoroFactory,
                     result_box: list[Any],
                     error_box: list[BaseException | None]) -> None:
    """Worker-thread body: own a fresh asyncio loop, drive one coroutine, hand back via the boxes.

    Success goes into `result_box[0]`; failure into `error_box[0]`. The caller (the joining parent thread in `run_async_safe`) re-raises from `error_box` if it is non-empty. `asyncio.new_event_loop()` returns the platform default (Python 3.8+ uses `WindowsProactorEventLoopPolicy` on Windows, so the loop class is correct without an explicit branch).

    Args:
        coro_factory (CoroFactory): zero-arg callable producing the coroutine to drive.
        result_box (list[Any]): single-element list the caller pre-allocates; slot 0 receives the coroutine's return value on success.
        error_box (list[BaseException | None]): single-element list the caller pre-allocates; slot 0 receives any exception that fired inside `coro_factory()` or the loop machinery.
    """
    try:
        _loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(_loop)
            result_box[0] = _loop.run_until_complete(coro_factory())
        finally:
            _loop.close()
    except BaseException as _exc:
        error_box[0] = _exc
