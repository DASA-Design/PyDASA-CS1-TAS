"""TCP port helpers shared by the spawners.

Windows holds a torn-down socket in TIME_WAIT for up to two minutes; rebinding the same port inside that window fails with `WinError 10048`. This module's `pick_free_port` probes a small range starting at the caller's preferred port and returns the first one that is bindable right now, letting back-to-back spawner cycles continue without manual port management.

Picks are clamped at or above `MIN_USER_PORT = 8000` to keep the apparatus out of:

- The IANA system-port range (0-1023) which usually requires elevated privileges to bind.
- The registered-port range (1024-49151) where many third-party daemons live (PostgreSQL 5432, Redis 6379, Jupyter 8888, etc.).

Any `start_port < 8000` is raised to 8000 before the probe begins; the caller's `start_port` value is treated as a preference, not a hard floor.
"""

from __future__ import annotations

import socket

MIN_USER_PORT = 8000


def pick_free_port(*,
                   host: str,
                   start_port: int,
                   max_skip: int = 32) -> int:
    """Return the lowest bindable port at or above `max(start_port, MIN_USER_PORT)`.

    Loops over `start_port`, `start_port + 1`, ..., up to `max_skip` candidates. Skipping handles TIME_WAIT lingering after a clean teardown on Windows (and any genuine collision with a foreign listener). Each probe opens, binds, and immediately closes a transient socket; the caller is responsible for actually binding the spawner on the returned port afterwards.

    Picks below `MIN_USER_PORT` (8000) are skipped automatically to keep the apparatus out of the system / registered port ranges.

    Args:
        host (str): bind address.
        start_port (int): preferred port; clamped up to `MIN_USER_PORT` when lower.
        max_skip (int, optional): how many sequential ports to probe before giving up. Defaults to 32.

    Returns:
        int: a port the caller can `bind` on right now. Always `>= MIN_USER_PORT`.

    Raises:
        RuntimeError: when no port in `[effective_start, effective_start + max_skip)` is bindable; the message hints how to inspect the conflict.
    """
    _effective_start = max(start_port, MIN_USER_PORT)
    _last_err: OSError | None = None
    for _offset in range(max_skip):
        _candidate = _effective_start + _offset
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _sock.bind((host, _candidate))
        except OSError as _err:
            _last_err = _err
        else:
            _sock.close()
            return _candidate
        finally:
            _sock.close()
    _msg = (f"no bindable port in [{_effective_start}, {_effective_start + max_skip}) on {host} "
            f"(last OSError: {_last_err}); orphaned processes may be hoarding the range. "
            f"Inspect with `netstat -ano | findstr :{_effective_start}`.")
    raise RuntimeError(_msg)


__all__ = ["MIN_USER_PORT", "pick_free_port"]
