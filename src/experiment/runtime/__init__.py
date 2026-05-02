# -*- coding: utf-8 -*-
"""Runtime layer: helpers that cross the OS / process boundary.

Concentrates anything that mutates or wraps host facilities (asyncio entry-point shims, OS-timer resolution, daemon-thread uvicorn) so the rest of `src/experiment/` stays platform-agnostic and pure-asyncio.

Public API:
    - `run_async_safe(coro_factory)`: run an awaitable from a sync caller, even when an event loop is already alive.
    - `windows_timer_resolution(period_ms)`: context manager lowering the Windows OS-timer floor.
    - `UvicornThread`: daemon-thread wrapper around `uvicorn.Server` for in-thread test/launcher use.
"""
from src.experiment.runtime.async_loop import run_async_safe
from src.experiment.runtime.os_timer import windows_timer_resolution
from src.experiment.runtime.uvicorn_thread import UvicornThread

__all__ = [
    "UvicornThread",
    "run_async_safe",
    "windows_timer_resolution",
]
