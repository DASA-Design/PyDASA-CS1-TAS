"""TCP port helpers shared by the spawners.

Windows holds a torn-down socket in TIME_WAIT for up to two minutes; rebinding the same port inside that window fails with `WinError 10048`. This module's `pick_free_port` probes a small range starting at the caller's preferred port and returns the first one that is bindable right now, letting back-to-back spawner cycles continue without manual port management.
"""

from __future__ import annotations

import socket


def pick_free_port(*,
                   host: str,
                   start_port: int,
                   max_skip: int = 32) -> int:
    """Return the lowest bindable port at or above `start_port`.

    Loops over `start_port`, `start_port + 1`, ..., up to `max_skip` candidates. Skipping handles TIME_WAIT lingering after a clean teardown on Windows (and any genuine collision with a foreign listener). Each probe opens, binds, and immediately closes a transient socket; the caller is responsible for actually binding the spawner on the returned port afterwards.

    Args:
        host (str): bind address.
        start_port (int): preferred port; tried first.
        max_skip (int, optional): how many sequential ports to probe before giving up. Defaults to 32.

    Returns:
        int: a port the caller can `bind` on right now.

    Raises:
        RuntimeError: when no port in `[start_port, start_port + max_skip)` is bindable; the message hints how to inspect the conflict.
    """
    _last_err: OSError | None = None
    for _offset in range(max_skip):
        _candidate = start_port + _offset
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
    _msg = (f"no bindable port in [{start_port}, {start_port + max_skip}) on {host} "
            f"(last OSError: {_last_err}); orphaned processes may be hoarding the range. "
            f"Inspect with `netstat -ano | findstr :{start_port}`.")
    raise RuntimeError(_msg)


__all__ = ["pick_free_port"]
