"""Kill leftover apparatus worker processes still bound to a calibration port.

Backstop for when a hard-killed trial leaves a worker alive past its `try/finally` + `atexit` cleanup. Only descendants of the current process are eligible, so the Jupyter kernel, the VS Code server, the shell, and unrelated apps are never touched even when they listen on a swept port.
"""

from __future__ import annotations

from collections.abc import Iterable

import psutil

DFLT_CALIB_PORT_RANGE = range(9042, 9051)


def _own_descendant_pids() -> set[int]:
    """Return the PIDs of every process descended from this one.

    Returns:
        set[int]: PIDs of all transitive children; empty when psutil cannot enumerate them.
    """
    try:
        return {_proc.pid for _proc in psutil.Process().children(recursive=True)}
    except psutil.Error:
        return set()


def _listening_descendants(ports: set[int],
                           own_pids: set[int]) -> dict[int, int]:
    """Map each owned descendant PID to a port it listens on within `ports`.

    Args:
        ports (set[int]): ports of interest.
        own_pids (set[int]): PIDs descended from the current process.

    Returns:
        dict[int, int]: `{pid: port}` for listening sockets that match both filters; one entry per PID.
    """
    _hits: dict[int, int] = {}
    for _conn in psutil.net_connections(kind="tcp"):
        _pid = _conn.pid
        _port = getattr(_conn.laddr, "port", None)
        _matches = (_conn.status == psutil.CONN_LISTEN
                    and _port in ports
                    and _pid in own_pids)
        if _matches and _pid is not None and _port is not None and _pid not in _hits:
            _hits[_pid] = _port
    return _hits


def _kill_pid(pid: int) -> str | None:
    """Kill one process by PID and wait for it to exit.

    Args:
        pid (int): target process id.

    Returns:
        str | None: the process name when it was killed and reaped, None when it could not be.
    """
    try:
        _proc = psutil.Process(pid)
        _name = _proc.name()
        _proc.kill()
        _proc.wait(timeout=2.0)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return None
    return _name


def cleanup_calibration_ports(ports: Iterable[int] = DFLT_CALIB_PORT_RANGE,
                              *,
                              verbose: bool = True) -> list[tuple[int, int]]:
    """Kill apparatus workers (descendants of this process) listening on a port in `ports`.

    A process is killed only when it is both a descendant of the current process and listening on one of `ports`. Idempotent: ports with no matching descendant listener are skipped silently.

    Args:
        ports (Iterable[int], optional): ports to sweep. Defaults to the calibration range (9042-9050).
        verbose (bool, optional): print one line per kill to stdout. Defaults to True.

    Returns:
        list[tuple[int, int]]: `(port, pid)` pairs for processes that were killed; empty when nothing matched.
    """
    _wanted = set(ports)
    _targets = _listening_descendants(_wanted, _own_descendant_pids())
    _killed: list[tuple[int, int]] = []
    for _pid, _port in _targets.items():
        _name = _kill_pid(_pid)
        if _name is None:
            if verbose:
                print(f"  port {_port}: could not kill PID {_pid}")
        else:
            _killed.append((_port, _pid))
            if verbose:
                print(f"  port {_port}: killed PID {_pid} ({_name})")
    if verbose and not _killed:
        print(f"  no apparatus workers listening in {sorted(_wanted)}")
    return _killed


__all__ = ["DFLT_CALIB_PORT_RANGE", "cleanup_calibration_ports"]
