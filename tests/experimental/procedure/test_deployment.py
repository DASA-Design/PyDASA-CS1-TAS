"""Tests for `src.experimental.procedure.deployment`.

Logic-only checks: port resolution, mount/wait/shutdown orchestration via a fake adapter factory. Real spawns happen in `00-calibration.ipynb` and `tests/demo/vernier.py`.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.experimental.procedure.deployment import (
    _resolve_ports,
    bring_up,
)
from src.experimental.prototype.runtime.server import ServerAdapter


def _noop_app() -> Any:
    """Stand-in `AppFactory` for tests that never actually start a server."""
    return None


class _AdapterFactory:
    """Module-level fake adapter factory; records every adapter it produced.

    Each `__call__` returns a fresh `MagicMock(spec=ServerAdapter)` and appends it to `adapters`, so tests can later assert on per-adapter `mount` / `wait_ready` / `shutdown` call counts.

    Attributes:
        adapters (list[Any]): one entry per `__call__`, in order.
    """

    def __init__(self) -> None:
        """Initialise an empty adapter log."""
        self.adapters: list[Any] = []

    def __call__(self) -> Any:
        """Return a fresh mocked adapter and remember it."""
        _adp = MagicMock(spec=ServerAdapter)
        self.adapters.append(_adp)
        return _adp


class TestDeployment:
    """Port resolution + bring_up orchestration."""

    def test_localhost_one_port(self) -> None:
        """Localhost mode resolves to a single-entry port list at the requested base port."""
        _ports = _resolve_ports("localhost", base_port=8001, workers=4)
        assert _ports == [8001]

    def test_multiprocess_n_ports(self) -> None:
        """Multiprocess mode resolves to N consecutive ports starting at base_port."""
        _ports = _resolve_ports("multiprocess", base_port=8001, workers=4)
        assert _ports == [8001, 8002, 8003, 8004]

    def test_unknown_dpl_raises(self) -> None:
        """An unknown deployment-mode name is rejected immediately."""
        with pytest.raises(ValueError, match="unknown dpl"):
            _resolve_ports("not_a_mode", base_port=8001, workers=4)  # type: ignore[arg-type]

    def test_remote_not_yet_supported(self) -> None:
        """Remote mode is not yet wired; resolving it raises so callers know to wait."""
        with pytest.raises(NotImplementedError):
            _resolve_ports("remote", base_port=8001, workers=4)

    def test_bring_up_localhost(self) -> None:
        """Bringing up localhost mounts one adapter on the base port and yields its URL; on exit, the adapter's shutdown runs."""
        _factory = _AdapterFactory()
        with bring_up("localhost",
                      app_factory=_noop_app,
                      base_port=9100,
                      adapter_factory=_factory) as _urls:
            assert _urls == ["http://127.0.0.1:9100"]
            assert len(_factory.adapters) == 1
            _factory.adapters[0].mount.assert_called_once()
            _factory.adapters[0].wait_ready.assert_called_once()
        _factory.adapters[0].shutdown.assert_called_once()

    def test_bring_up_multiprocess(self) -> None:
        """Bringing up multiprocess mounts N adapters on consecutive ports, yields all their URLs, and shuts each one down on exit."""
        _factory = _AdapterFactory()
        with bring_up("multiprocess",
                      app_factory=_noop_app,
                      base_port=9200,
                      workers=3,
                      adapter_factory=_factory) as _urls:
            assert _urls == ["http://127.0.0.1:9200",
                             "http://127.0.0.1:9201",
                             "http://127.0.0.1:9202"]
            assert len(_factory.adapters) == 3
            for _adp in _factory.adapters:
                _adp.mount.assert_called_once()
                _adp.wait_ready.assert_called_once()
        for _adp in _factory.adapters:
            _adp.shutdown.assert_called_once()

    def test_bring_up_shuts_down_on_exception(self) -> None:
        """If the calling block raises inside the context, every started adapter still gets shutdown so the apparatus does not leak."""
        _factory = _AdapterFactory()
        with pytest.raises(RuntimeError, match="boom"):
            with bring_up("multiprocess",
                          app_factory=_noop_app,
                          base_port=9300,
                          workers=2,
                          adapter_factory=_factory):
                _msg = "boom"
                raise RuntimeError(_msg)
        for _adp in _factory.adapters:
            _adp.shutdown.assert_called_once()
