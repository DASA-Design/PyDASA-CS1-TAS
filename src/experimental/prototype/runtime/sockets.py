"""TCP port helpers for the apparatus spawners.

- `pick_free_port`: find the first bindable port at or above a preferred one.
- `PortRegistry`: track spawned workers' ports so a crashed run's leftovers get reaped on the next run.

Ports stay at or above `MIN_USER_PORT` (8000), clear of the system and registered ranges.
"""

from __future__ import annotations

import json
import socket
import tempfile
from pathlib import Path
from typing import Any

import psutil

MIN_USER_PORT = 8000

# Machine-local registry file; in the temp dir so it survives sessions without polluting the repo.
_DFLT_REGISTRY_PATH = Path(tempfile.gettempdir()) / "pydasa_cs1_apparatus_ports.json"


def pick_free_port(*,
                   host: str,
                   start_port: int,
                   max_skip: int = 32) -> int:
    """Return the lowest bindable port at or above `max(start_port, MIN_USER_PORT)`.

    Probes `start_port`, `start_port + 1`, ... up to `max_skip` candidates, opening and immediately closing a transient socket on each. Skipping absorbs a port held in TIME_WAIT after a clean teardown, or a clash with a foreign listener. The caller binds the spawner on the returned port afterwards.

    Args:
        host (str): bind address.
        start_port (int): preferred port; raised to `MIN_USER_PORT` when lower.
        max_skip (int, optional): how many sequential ports to probe before giving up. Defaults to 32.

    Returns:
        int: a port bindable right now, always `>= MIN_USER_PORT`.

    Raises:
        RuntimeError: when no port in the probed window is bindable.
    """
    _effective_start = max(start_port, MIN_USER_PORT)
    _last_err: OSError | None = None
    _ans: int | None = None
    for _offset in range(max_skip):
        _candidate = _effective_start + _offset
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            _sock.bind((host, _candidate))
        except OSError as _err:
            _last_err = _err
        else:
            _ans = _candidate
        finally:
            _sock.close()
        if _ans is not None:
            break
    if _ans is None:
        _msg = (f"no bindable port in [{_effective_start}, {_effective_start + max_skip}) on {host} "
                f"(last OSError: {_last_err}); orphaned processes may be hoarding the range. "
                f"Inspect with `netstat -ano | findstr :{_effective_start}`.")
        raise RuntimeError(_msg)
    return _ans


def _proc_create_time(pid: int) -> float | None:
    """Return one process's create-time.

    Args:
        pid (int): target process id.

    Returns:
        float | None: create-time in epoch seconds, or None when the process is gone or unreadable.
    """
    _ans: float | None = None
    try:
        _ans = psutil.Process(pid).create_time()
    except psutil.Error:
        _ans = None
    return _ans


def _kill_pid(pid: int) -> str | None:
    """Kill one process by PID and wait for it to exit.

    Args:
        pid (int): target process id.

    Returns:
        str | None: the process name when it was killed and reaped, None when it could not be.
    """
    _name: str | None = None
    try:
        _proc = psutil.Process(pid)
        _name = _proc.name()
        _proc.kill()
        _proc.wait(timeout=2.0)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        _name = None
    return _name


def _listeners_on(ports: set[int]) -> dict[int, tuple[int, float]]:
    """Resolve the `(pid, create_time)` of whatever listens on each port in `ports`.

    Identifies the apparatus workers just bound on known ports; not a discovery sweep, since the caller already owns these exact ports.

    Args:
        ports (set[int]): the ports the caller just bound.

    Returns:
        dict[int, tuple[int, float]]: `{port: (pid, create_time)}`, one entry per port with a readable listener.
    """
    _ans: dict[int, tuple[int, float]] = {}
    for _conn in psutil.net_connections(kind="tcp"):
        _pid = _conn.pid
        _port = getattr(_conn.laddr, "port", None)
        _matches = (_conn.status == psutil.CONN_LISTEN
                    and _port in ports
                    and _pid is not None
                    and _port not in _ans)
        if _matches and _pid is not None and _port is not None:
            _ct = _proc_create_time(_pid)
            if _ct is not None:
                _ans[_port] = (_pid, _ct)
    return _ans


def _is_same_process(pid: int, create_time: float) -> bool:
    """Check that `pid` is alive and is still the process the registry recorded.

    Args:
        pid (int): the recorded process id.
        create_time (float): the create-time recorded alongside `pid`.

    Returns:
        bool: True when `pid` is alive and its create-time matches; False when it is gone or the PID was reused.
    """
    _ct = _proc_create_time(pid)
    return _ct is not None and _ct == create_time


class PortRegistry:
    """Tracks the `(port, pid, create_time)` of apparatus workers across runs.

    Backed by a machine-local JSON file. `bring_up` / `bring_up_mesh` call `register` once a mesh is up and `release` on clean shutdown; `reap` runs at the next startup and kills anything a crash left behind. Recording `create_time` per PID means a reused PID is never mistaken for an apparatus worker, so only processes the apparatus provably spawned are ever killed.

    Attributes:
        _path (Path): the JSON registry file.
    """

    def __init__(self, path: Path = _DFLT_REGISTRY_PATH) -> None:
        """Bind the registry to its backing file.

        Args:
            path (Path, optional): the JSON registry file. Defaults to a machine-local temp-dir path.
        """
        self._path = path

    def _load(self) -> dict[str, list[Any]]:
        """Read the registry file into a dict.

        Returns:
            dict[str, list[Any]]: the `{port: [pid, create_time]}` map, or an empty dict when the file is missing or corrupt.
        """
        _ans: dict[str, list[Any]] = {}
        try:
            _data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _data = {}
        if isinstance(_data, dict):
            _ans = _data
        return _ans

    def _save(self, reg: dict[str, list[Any]]) -> None:
        """Write the registry dict to disk.

        A write failure is swallowed: registry bookkeeping must never break a run.

        Args:
            reg (dict[str, list[Any]]): the `{port: [pid, create_time]}` map to persist.
        """
        try:
            self._path.write_text(json.dumps(reg), encoding="utf-8")
        except OSError:
            pass

    def register(self, ports: list[int]) -> None:
        """Record the `(pid, create_time)` of the apparatus workers bound on `ports`.

        Called once a mesh is up. `reap` reads these back on the next run to kill anything a crash leaves behind. Each port's listener PID is resolved by a lookup of that exact (caller-owned) port, never a range scan.

        Args:
            ports (list[int]): ports the caller just brought up.
        """
        if ports:
            _found = _listeners_on(set(ports))
            if _found:
                _reg = self._load()
                for _port, (_pid, _ct) in _found.items():
                    _reg[str(_port)] = [_pid, _ct]
                self._save(_reg)

    def release(self, ports: list[int]) -> None:
        """Drop `ports` from the registry after a clean shutdown.

        Args:
            ports (list[int]): ports whose workers have just been shut down.
        """
        if ports:
            _reg = self._load()
            _changed = False
            for _port in ports:
                if str(_port) in _reg:
                    del _reg[str(_port)]
                    _changed = True
            if _changed:
                self._save(_reg)

    def reap(self, *, verbose: bool = True) -> list[tuple[int, int]]:
        """Kill every registered apparatus worker still alive from a crashed prior run.

        For each recorded `(port, pid, create_time)`, kills the process only when it still exists and its create-time matches the recorded value, so a reused PID is never mistaken for our worker. The registry is then cleared: a clean prior run already emptied it via `release`, so anything left is crash debris. Assumes no other apparatus run is concurrently live.

        Args:
            verbose (bool, optional): print one line per reaped orphan. Defaults to True.

        Returns:
            list[tuple[int, int]]: `(port, pid)` pairs for processes that were reaped.
        """
        _killed: list[tuple[int, int]] = []
        _reg = self._load()
        for _port_s, _entry in _reg.items():
            _pid, _ct = int(_entry[0]), float(_entry[1])
            if _is_same_process(_pid, _ct):
                _name = _kill_pid(_pid)
                if _name is not None:
                    _killed.append((int(_port_s), _pid))
                    if verbose:
                        print(f"  port {_port_s}: reaped orphan PID {_pid} ({_name})")
        if _reg:
            self._save({})
        return _killed


__all__ = ["MIN_USER_PORT", "PortRegistry", "pick_free_port"]
