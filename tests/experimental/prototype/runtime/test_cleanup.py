"""Tests for `src.experimental.prototype.runtime.cleanup`.

**TestCleanupCalibrationPorts**:

- `test_no_listeners`: returns an empty list when nothing is listening in the target range.
- `test_kills_listener`: a process LISTENING on a target port is killed and its `(port, pid)` recorded.
- `test_skips_non_listen`: ESTABLISHED / TIME_WAIT entries on the same port are ignored.
- `test_skips_outside_range`: listeners on ports outside the target range are left alone.
- `test_dedup_pids`: a single PID listening on multiple wanted ports is killed once and reported once.
- `test_swallows_no_such_proc`: a race where the PID exits between `net_connections` and `Process.kill` is logged silently and does not raise.
"""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import MagicMock, patch

import psutil

from src.experimental.prototype.runtime.cleanup import (
    DFLT_CALIB_PORT_RANGE,
    cleanup_calibration_ports,
)

_Laddr = namedtuple("_Laddr", ["ip", "port"])
_Conn = namedtuple("_Conn", ["status", "laddr", "pid"])


def _make_conn(port: int, pid: int | None, status: str = psutil.CONN_LISTEN) -> _Conn:
    return _Conn(status=status, laddr=_Laddr("127.0.0.1", port), pid=pid)


class TestCleanupCalibrationPorts:
    """Notebook-callable port-sweep utility."""

    def test_no_listeners(self) -> None:
        """*test_no_listeners()* returns `[]` when no socket is listening in the range."""
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=[]):
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == []

    def test_kills_listener(self) -> None:
        """*test_kills_listener()* kills the owning PID and reports `(port, pid)`."""
        _conns = [_make_conn(9042, 4321)]
        _proc = MagicMock()
        _proc.name.return_value = "python.exe"
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=_conns), \
             patch("src.experimental.prototype.runtime.cleanup.psutil.Process", return_value=_proc):
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == [(9042, 4321)]
        _proc.kill.assert_called_once()
        _proc.wait.assert_called_once_with(timeout=2.0)

    def test_skips_non_listen(self) -> None:
        """*test_skips_non_listen()* leaves non-LISTEN entries on target ports alone."""
        _conns = [_make_conn(9042, 4321, status=psutil.CONN_ESTABLISHED),
                  _make_conn(9043, 5555, status=psutil.CONN_TIME_WAIT)]
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=_conns), \
             patch("src.experimental.prototype.runtime.cleanup.psutil.Process") as _proc_cls:
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == []
        _proc_cls.assert_not_called()

    def test_skips_outside_range(self) -> None:
        """*test_skips_outside_range()* ignores listeners outside the requested ports."""
        _conns = [_make_conn(8000, 1111), _make_conn(9100, 2222)]
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=_conns), \
             patch("src.experimental.prototype.runtime.cleanup.psutil.Process") as _proc_cls:
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == []
        _proc_cls.assert_not_called()

    def test_dedup_pids(self) -> None:
        """*test_dedup_pids()* kills a multi-port PID exactly once."""
        _conns = [_make_conn(9042, 7777), _make_conn(9043, 7777)]
        _proc = MagicMock()
        _proc.name.return_value = "python.exe"
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=_conns), \
             patch("src.experimental.prototype.runtime.cleanup.psutil.Process", return_value=_proc):
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == [(9042, 7777)]
        _proc.kill.assert_called_once()

    def test_swallows_no_such_proc(self) -> None:
        """*test_swallows_no_such_proc()* logs and continues when the PID exits between listing and kill."""
        _conns = [_make_conn(9042, 4321)]
        with patch("src.experimental.prototype.runtime.cleanup.psutil.net_connections", return_value=_conns), \
             patch("src.experimental.prototype.runtime.cleanup.psutil.Process",
                   side_effect=psutil.NoSuchProcess(4321)):
            _killed = cleanup_calibration_ports(verbose=False)
        assert _killed == []

    def test_dflt_range(self) -> None:
        """*test_dflt_range()* points at the calibration port band 9042-9050."""
        assert list(DFLT_CALIB_PORT_RANGE) == list(range(9042, 9051))
