"""Manual port-cleanup utility for the calibration / experimental ports.

Backstop for notebook sessions where the watchdog wasn't deployed yet, fired too late, or where a stale worker from an earlier kernel still binds the apparatus range. Same effect as `Get-NetTCPConnection -LocalPort 9042 | Stop-Process -Force` on PowerShell, but cross-platform and callable from a notebook cell.
"""

from __future__ import annotations

from collections.abc import Iterable

import psutil

DFLT_CALIB_PORT_RANGE = range(9042, 9051)


def cleanup_calibration_ports(ports: Iterable[int] = DFLT_CALIB_PORT_RANGE,
                              *,
                              verbose: bool = True) -> list[tuple[int, int]]:
    """Kill every process LISTENING on a port in `ports`; return what was killed.

    Idempotent: ports with no listener are skipped silently. Sockets in TIME_WAIT or CLOSE_WAIT are also skipped because they don't have an owning process to kill.

    Args:
        ports (Iterable[int], optional): ports to sweep. Defaults to the calibration range (9042-9050).
        verbose (bool, optional): print one line per kill to stdout. Defaults to True.

    Returns:
        list[tuple[int, int]]: `(port, pid)` pairs for processes that were killed; empty when nothing was listening.
    """
    _wanted = set(ports)
    _killed: list[tuple[int, int]] = []
    _seen_pids: set[int] = set()
    for _conn in psutil.net_connections(kind="tcp"):
        if _conn.status != psutil.CONN_LISTEN:
            continue
        if _conn.laddr is None:
            continue
        _port = _conn.laddr.port
        if _port not in _wanted:
            continue
        _pid = _conn.pid
        if _pid is None or _pid in _seen_pids:
            continue
        _seen_pids.add(_pid)
        try:
            _proc = psutil.Process(_pid)
            _name = _proc.name()
            _proc.kill()
            _proc.wait(timeout=2.0)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as _err:
            if verbose:
                print(f"  port {_port}: could not kill PID {_pid} ({_err})")
            continue
        _killed.append((_port, _pid))
        if verbose:
            print(f"  port {_port}: killed PID {_pid} ({_name})")
    if verbose and not _killed:
        print(f"  no listeners in {sorted(_wanted)}")
    return _killed


__all__ = ["DFLT_CALIB_PORT_RANGE", "cleanup_calibration_ports"]
