"""Tests for `src.experimental.prototype.runtime.sockets`.

**TestPickFreePort**: the stateless free-port probe.

- `test_returns_preferred`: a bindable preferred port is returned unchanged.
- `test_skips_taken`: a taken port is skipped; the next bindable one is returned.
- `test_clamps_below_min`: a start port below `MIN_USER_PORT` is raised to it.
- `test_raises_when_exhausted`: no bindable port in range raises `RuntimeError`.

**TestPortRegistry**: the spawn registry, exercised against a throwaway file.

- `test_register_records`: `register` writes one `[pid, create_time]` entry per resolved port.
- `test_register_empty_noop`: `register([])` writes nothing.
- `test_release_drops`: `release` removes the named ports and leaves the rest.
- `test_reap_kills_match`: `reap` kills an entry whose PID + create-time still match, and clears the file.
- `test_reap_skips_reused_pid`: `reap` leaves an entry alone when the create-time no longer matches.
- `test_reap_empty`: `reap` on an empty / absent registry returns `[]`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.experimental.prototype.runtime.sockets import (
    MIN_USER_PORT,
    PortRegistry,
    pick_free_port,
)

_SOCKET_PATH = "src.experimental.prototype.runtime.sockets.socket.socket"
_LISTENERS_PATH = "src.experimental.prototype.runtime.sockets._listeners_on"
_SAME_PROC_PATH = "src.experimental.prototype.runtime.sockets._is_same_process"
_KILL_PATH = "src.experimental.prototype.runtime.sockets._kill_pid"


class TestPickFreePort:
    """Stateless free-port probe."""

    def test_returns_preferred(self) -> None:
        """*test_returns_preferred()* a bindable preferred port comes back unchanged."""
        _sock = MagicMock()
        with patch(_SOCKET_PATH, return_value=_sock):
            _port = pick_free_port(host="127.0.0.1", start_port=9000)
        assert _port == 9000

    def test_skips_taken(self) -> None:
        """*test_skips_taken()* a port whose bind raises `OSError` is skipped for the next one."""
        _sock = MagicMock()
        _sock.bind.side_effect = [OSError("taken"), None]
        with patch(_SOCKET_PATH, return_value=_sock):
            _port = pick_free_port(host="127.0.0.1", start_port=9000)
        assert _port == 9001

    def test_clamps_below_min(self) -> None:
        """*test_clamps_below_min()* a start port below `MIN_USER_PORT` is raised to it before probing."""
        _sock = MagicMock()
        with patch(_SOCKET_PATH, return_value=_sock):
            _port = pick_free_port(host="127.0.0.1", start_port=80)
        assert _port == MIN_USER_PORT

    def test_raises_when_exhausted(self) -> None:
        """*test_raises_when_exhausted()* no bindable port within `max_skip` raises `RuntimeError`."""
        _sock = MagicMock()
        _sock.bind.side_effect = OSError("taken")
        with patch(_SOCKET_PATH, return_value=_sock):
            with pytest.raises(RuntimeError, match="no bindable port"):
                pick_free_port(host="127.0.0.1", start_port=9000, max_skip=4)


class TestPortRegistry:
    """Spawn registry: record / release / reap against a throwaway file."""

    def test_register_records(self, tmp_path: Path) -> None:
        """*test_register_records()* `register` writes one `[pid, create_time]` entry per resolved port."""
        _reg = PortRegistry(path=tmp_path / "reg.json")
        with patch(_LISTENERS_PATH, return_value={8000: (1234, 111.0)}):
            _reg.register([8000])
        _data = json.loads((tmp_path / "reg.json").read_text(encoding="utf-8"))
        assert _data == {"8000": [1234, 111.0]}

    def test_register_empty_noop(self, tmp_path: Path) -> None:
        """*test_register_empty_noop()* `register([])` writes no registry file."""
        _path = tmp_path / "reg.json"
        PortRegistry(path=_path).register([])
        assert not _path.exists()

    def test_release_drops(self, tmp_path: Path) -> None:
        """*test_release_drops()* `release` removes the named ports and keeps the rest."""
        _path = tmp_path / "reg.json"
        _path.write_text(json.dumps({"8000": [1, 1.0], "8020": [2, 2.0]}), encoding="utf-8")
        PortRegistry(path=_path).release([8000])
        assert json.loads(_path.read_text(encoding="utf-8")) == {"8020": [2, 2.0]}

    def test_reap_kills_match(self, tmp_path: Path) -> None:
        """*test_reap_kills_match()* `reap` kills an entry whose PID + create-time match, then clears the file."""
        _path = tmp_path / "reg.json"
        _path.write_text(json.dumps({"8000": [1234, 111.0]}), encoding="utf-8")
        with patch(_SAME_PROC_PATH, return_value=True), \
             patch(_KILL_PATH, return_value="python.exe"):
            _killed = PortRegistry(path=_path).reap(verbose=False)
        assert _killed == [(8000, 1234)]
        assert json.loads(_path.read_text(encoding="utf-8")) == {}

    def test_reap_skips_reused_pid(self, tmp_path: Path) -> None:
        """*test_reap_skips_reused_pid()* `reap` leaves an entry alone when the create-time no longer matches."""
        _path = tmp_path / "reg.json"
        _path.write_text(json.dumps({"8000": [1234, 111.0]}), encoding="utf-8")
        with patch(_SAME_PROC_PATH, return_value=False), \
             patch(_KILL_PATH) as _kill:
            _killed = PortRegistry(path=_path).reap(verbose=False)
        assert _killed == []
        _kill.assert_not_called()

    def test_reap_empty(self, tmp_path: Path) -> None:
        """*test_reap_empty()* `reap` on an absent registry returns an empty list."""
        _killed = PortRegistry(path=tmp_path / "absent.json").reap(verbose=False)
        assert _killed == []
