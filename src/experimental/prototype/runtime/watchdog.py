"""Parent-PID watchdog for spawned worker processes.

`multiprocessing.Process(daemon=True)` only kills the child when the parent exits *cleanly*. On a Jupyter kernel hard-kill, Ctrl+C-during-startup, or any abnormal parent exit, the daemon hook never fires and the worker keeps running, holding its TCP port until manually terminated. `atexit` hooks have the same limitation.

The fix is a poll-based watchdog: each worker spawns a daemon thread at startup that checks whether the recorded parent PID is still alive on a slow interval. On parent death the thread runs an optional graceful callback (e.g. `server.should_exit = True` for uvicorn), then `os._exit(0)` after a short grace period so the worker releases its port deterministically.

Cross-platform via `psutil.pid_exists`; no signal-0 nonsense and no ctypes.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

import psutil

_DFLT_POLL_INTERVAL_S = 2.0
_DFLT_GRACE_S = 5.0


def watch_parent(parent_pid: int,
                 *,
                 on_orphan: Callable[[], None] | None = None,
                 poll_interval_s: float = _DFLT_POLL_INTERVAL_S,
                 grace_s: float = _DFLT_GRACE_S) -> threading.Thread:
    """Start a daemon thread that force-exits this process when `parent_pid` dies.

    Polling cadence is deliberately slow (2 s default) so the watchdog adds negligible CPU load; the latency before a leaked worker dies is bounded by `poll_interval_s + grace_s`, typically under 10 s.

    Args:
        parent_pid (int): the parent process to watch. Capture once at worker start with `os.getppid()`; do not re-read inside the worker since orphaned processes are re-parented to PID 1 on POSIX and the watchdog would never fire.
        on_orphan (Callable[[], None] | None, optional): graceful-shutdown callback invoked once when the parent is detected gone (e.g. `lambda: setattr(server, "should_exit", True)` for uvicorn). Defaults to None (skip straight to hard exit). Exceptions raised by the callback are swallowed so a faulty callback cannot block the hard-exit fallback.
        poll_interval_s (float, optional): seconds between `pid_exists` polls. Defaults to 2.0.
        grace_s (float, optional): seconds to wait between the graceful callback and `os._exit(0)`. Defaults to 5.0.

    Returns:
        threading.Thread: the daemon watchdog thread, already started. Callers normally discard the handle; the thread exits the process on parent death.
    """
    def _loop() -> None:
        while True:
            time.sleep(poll_interval_s)
            if not psutil.pid_exists(parent_pid):
                break
        if on_orphan is not None:
            try:
                on_orphan()
            except Exception:
                pass
        time.sleep(grace_s)
        os._exit(0)
    _thread = threading.Thread(target=_loop,
                               daemon=True,
                               name=f"parent-watchdog-{parent_pid}")
    _thread.start()
    return _thread


__all__ = ["watch_parent"]
