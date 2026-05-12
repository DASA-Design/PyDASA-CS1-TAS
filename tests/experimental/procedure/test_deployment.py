"""Tests for `src.experimental.procedure.deployment`.

**TestDeployment**: port resolution + `bring_up` / `bring_up_mesh` orchestration via a fake adapter factory; real spawns happen in `00-calibration.ipynb` and `tests/demo/vernier.py`.

- *test_localhost_one_port()*: localhost mode resolves to a single-entry port list at the requested base port.
- *test_multiprocess_n_ports()*: multiprocess mode resolves to N consecutive ports starting at `base_port`.
- *test_unknown_dpl_raises()*: an unknown deployment mode is rejected immediately.
- *test_remote_not_yet_supported()*: remote mode raises `NotImplementedError` so callers know to wait.
- *test_bring_up_localhost()*: localhost mounts one adapter on the base port; on exit the adapter's `shutdown` runs.
- *test_bring_up_multiprocess()*: multiprocess mounts N adapters on consecutive ports; each shuts down on exit.
- *test_bring_up_mesh_assigns_consecutive_ports()*: mesh mode mounts one adapter per spec and yields a `svc_id -> [URL]` mapping (single-worker specs return a one-element list).
- *test_bring_up_mesh_workers_spawns_n_per_spec()*: `MeshSpec(workers=N)` mounts N adapters on consecutive ports; offsets accumulate across specs.
- *test_bring_up_mesh_empty_specs_raises()*: an empty `MeshSpec` list raises `ValueError` immediately.
- *test_bring_up_mesh_shuts_down_on_exception()*: if the body raises, every mounted mesh adapter still shuts down (in reverse order).
- *test_bring_up_shuts_down_on_exception()*: if the body raises inside `bring_up`, every started adapter still gets shutdown.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.experimental.procedure.deployment import (
    MeshSpec,
    _resolve_ports,
    bring_up,
    bring_up_mesh,
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
        """*test_localhost_one_port()* localhost mode resolves to a single-entry port list at the requested base port."""
        _ports = _resolve_ports("localhost", base_port=8001, workers=4)
        assert _ports == [8001]

    def test_multiprocess_n_ports(self) -> None:
        """*test_multiprocess_n_ports()* multiprocess mode resolves to N consecutive ports starting at `base_port`."""
        _ports = _resolve_ports("multiprocess", base_port=8001, workers=4)
        assert _ports == [8001, 8002, 8003, 8004]

    def test_unknown_dpl_raises(self) -> None:
        """*test_unknown_dpl_raises()* an unknown deployment-mode name is rejected immediately."""
        with pytest.raises(ValueError, match="unknown dpl"):
            _resolve_ports("not_a_mode", base_port=8001, workers=4)  # type: ignore[arg-type]

    def test_remote_not_yet_supported(self) -> None:
        """*test_remote_not_yet_supported()* remote mode is not yet wired; resolving it raises so callers know to wait."""
        with pytest.raises(NotImplementedError):
            _resolve_ports("remote", base_port=8001, workers=4)

    def test_bring_up_localhost(self) -> None:
        """*test_bring_up_localhost()* bringing up localhost mounts one adapter on the base port and yields its URL; on exit the adapter's shutdown runs."""
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
        """*test_bring_up_multiprocess()* bringing up multiprocess mounts N adapters on consecutive ports, yields all their URLs, and shuts each one down on exit."""
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

    def test_bring_up_mesh_assigns_consecutive_ports(self) -> None:
        """*test_bring_up_mesh_assigns_consecutive_ports()* `bring_up_mesh` mounts one adapter per spec on consecutive ports and yields a `svc_id -> [URL]` mapping (single-worker specs return a one-element list)."""
        _factory = _AdapterFactory()
        _specs = [
            MeshSpec(svc_id="TAS", app_factory=_noop_app),
            MeshSpec(svc_id="MAS_{1}", app_factory=_noop_app),
            MeshSpec(svc_id="AS_{1}", app_factory=_noop_app),
        ]
        with bring_up_mesh(_specs,
                           base_port=9400,
                           adapter_factory=_factory) as _urls:
            assert _urls == {
                "TAS": ["http://127.0.0.1:9400"],
                "MAS_{1}": ["http://127.0.0.1:9401"],
                "AS_{1}": ["http://127.0.0.1:9402"],
            }
            assert len(_factory.adapters) == 3
            for _adp in _factory.adapters:
                _adp.mount.assert_called_once()
                _adp.wait_ready.assert_called_once()
        for _adp in _factory.adapters:
            _adp.shutdown.assert_called_once()

    def test_bring_up_mesh_workers_spawns_n_per_spec(self) -> None:
        """*test_bring_up_mesh_workers_spawns_n_per_spec()* `MeshSpec(workers=N)` mounts N adapters on consecutive ports and the URL list has N entries; offsets accumulate across specs."""
        _factory = _AdapterFactory()
        _specs = [
            MeshSpec(svc_id="TAS", app_factory=_noop_app, workers=3),
            MeshSpec(svc_id="MAS_{1}", app_factory=_noop_app, workers=2),
        ]
        with bring_up_mesh(_specs,
                           base_port=9600,
                           adapter_factory=_factory) as _urls:
            assert _urls == {
                "TAS": ["http://127.0.0.1:9600",
                        "http://127.0.0.1:9601",
                        "http://127.0.0.1:9602"],
                "MAS_{1}": ["http://127.0.0.1:9603",
                            "http://127.0.0.1:9604"],
            }
            assert len(_factory.adapters) == 5
        for _adp in _factory.adapters:
            _adp.shutdown.assert_called_once()

    def test_bring_up_mesh_empty_specs_raises(self) -> None:
        """*test_bring_up_mesh_empty_specs_raises()* an empty `MeshSpec` list raises `ValueError` immediately (no spawners come up)."""
        with pytest.raises(ValueError, match="at least one MeshSpec"):
            with bring_up_mesh([], base_port=9500):
                pass

    def test_bring_up_mesh_shuts_down_on_exception(self) -> None:
        """*test_bring_up_mesh_shuts_down_on_exception()* if the calling block raises, every mounted mesh adapter is still shut down (in reverse order)."""
        _factory = _AdapterFactory()
        _specs = [
            MeshSpec(svc_id="TAS", app_factory=_noop_app),
            MeshSpec(svc_id="MAS_{1}", app_factory=_noop_app),
        ]
        with pytest.raises(RuntimeError, match="boom"):
            with bring_up_mesh(_specs,
                               base_port=9600,
                               adapter_factory=_factory):
                _msg = "boom"
                raise RuntimeError(_msg)
        for _adp in _factory.adapters:
            _adp.shutdown.assert_called_once()

    def test_bring_up_shuts_down_on_exception(self) -> None:
        """*test_bring_up_shuts_down_on_exception()* if the calling block raises inside the context, every started adapter still gets shutdown so the apparatus does not leak."""
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
