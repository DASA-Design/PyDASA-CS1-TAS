# -*- coding: utf-8 -*-
"""
Module runtime/async_loop.py
============================

Bridge sync code to asyncio without caring whether an event loop is already alive. CLI processes have no ambient loop and `asyncio.run` works directly; Jupyter / IPython / the calibration rate-sweep all keep one alive and `asyncio.run` would crash. This module hides that branch behind one entry point.
"""
# native python modules
from __future__ import annotations

import asyncio
import gc
import sys
import threading
from typing import Any, Callable, Coroutine, Dict, List, Optional


def run_async_safe(
    coro_factory: Callable[[], Coroutine[Any, Any, Dict[str, Any]]],
) -> Dict[str, Any]:
    """*run_async_safe()* sync entry point that always works, regardless of whether an event loop is already running on the calling thread.

    Two branches:

        - No ambient loop -> straight `asyncio.run(coro_factory())`.
        - Ambient loop -> spawn a worker thread, give it a fresh `ProactorEventLoop` (Windows) or `SelectorEventLoop` (POSIX), and run the coroutine to completion there. The calling thread joins the worker so the caller still sees a synchronous return.

    Args:
        coro_factory: zero-arg callable producing the coroutine to drive. Re-invoked from inside the worker thread so the coroutine binds to the worker-thread loop.

    Raises:
        Exception: re-raises any exception that fired inside the coroutine.

    Returns:
        Dict[str, Any]: value the coroutine resolved to.
    """
    try:
        asyncio.get_running_loop()
        _ambient_loop = True
    except RuntimeError:
        _ambient_loop = False

    if not _ambient_loop:
        return asyncio.run(coro_factory())

    _result_box: List[Any] = [None]
    _error_box: List[Optional[BaseException]] = [None]

    _t = threading.Thread(target=_worker_run_coro,
                          args=(coro_factory, _result_box, _error_box),
                          daemon=False)
    _t.start()
    _t.join()
    _err = _error_box[0]
    if _err is not None:
        raise _err
    _out = _result_box[0]
    _result_box.clear()
    _error_box.clear()
    gc.collect()
    return _out


def _worker_run_coro(
    coro_factory: Callable[[], Coroutine[Any, Any, Dict[str, Any]]],
    result_box: List[Any],
    error_box: List[Optional[BaseException]],
) -> None:
    """*_worker_run_coro()* thread-target body: own a fresh asyncio loop, drive one coroutine to completion, hand the outcome back through the two boxes.

    Success goes into `result_box[0]`, failure into `error_box[0]`; the caller (the joining parent thread in `run_async_safe`) re-raises from `error_box` if it is non-empty. The loop class is platform-dependent: `ProactorEventLoop` on Windows (subprocess + named-pipe support) and the default `new_event_loop()` elsewhere.

    Args:
        coro_factory: zero-arg callable producing the coroutine to drive; invoked inside this thread so the coroutine binds to the loop allocated here.
        result_box (List[Any]): single-element list the caller pre-allocates; slot 0 receives the coroutine's return value on success.
        error_box (List[Optional[BaseException]]): single-element list the caller pre-allocates; slot 0 receives any exception that fired inside `coro_factory()` (or the loop machinery).
    """
    try:
        if sys.platform == "win32":
            _loop = asyncio.ProactorEventLoop()
        else:
            _loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(_loop)
            result_box[0] = _loop.run_until_complete(coro_factory())
        finally:
            _loop.close()
    except BaseException as _exc:
        error_box[0] = _exc
