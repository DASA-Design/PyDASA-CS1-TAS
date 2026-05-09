"""Tests for `src.experimental.prototype.runtime.config`.

**TestConfig**:

- `test_top_level_keys`: parse the on-disk JSON and check the documented top-level keys.
- `test_uvicorn_block`: the uvicorn block carries the four shared runtime-tuning keys plus `backlog`.
- `test_waitress_block`: the waitress block adds `threads` on top of the shared shape.
- `test_gunicorn_block`: the gunicorn block adds `workers` on top of the shared shape.
- `test_unknown_raises`: an unknown spawner name raises `KeyError`.
- `test_explicit_path`: a caller-supplied path overrides the default.
- `test_dflt_path`: the default path constant points at the on-disk JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experimental.prototype.runtime.config import (
    DFLT_EXPERIMENTAL_CFG_PATH,
    load_experimental_cfg,
    load_server_cfg,
)


class TestConfig:
    """Loader for the orchestrator-level experimental config."""

    def test_top_level_keys(self) -> None:
        """Reading `data/config/method/experimental.json` returns a dict with the documented top-level keys."""
        _cfg = load_experimental_cfg()
        assert "framework" in _cfg
        assert "server" in _cfg
        assert "dpl" in _cfg
        assert "run_label" in _cfg

    def test_uvicorn_block(self) -> None:
        """The uvicorn sub-block carries the four shared runtime-tuning keys plus the engine-specific `backlog`."""
        _cfg = load_server_cfg("uvicorn")
        assert _cfg["backlog"] >= 1
        assert _cfg["ready_timeout_s"] > 0
        assert _cfg["terminate_grace_s"] > 0
        assert _cfg["kill_grace_s"] > 0

    def test_waitress_block(self) -> None:
        """The waitress sub-block carries `threads` on top of the shared shape."""
        _cfg = load_server_cfg("waitress")
        assert _cfg["threads"] >= 1
        assert _cfg["backlog"] >= 1

    def test_gunicorn_block(self) -> None:
        """The gunicorn sub-block carries `workers` on top of the shared shape."""
        _cfg = load_server_cfg("gunicorn")
        assert _cfg["workers"] >= 1
        assert _cfg["ready_timeout_s"] > 0

    def test_unknown_raises(self) -> None:
        """An unknown spawner name raises `KeyError` so config typos surface immediately, not three layers deep."""
        with pytest.raises(KeyError):
            load_server_cfg("nonexistent_engine")

    def test_explicit_path(self, tmp_path: Path) -> None:
        """A caller-supplied path overrides the default. Writing a fixture JSON under `tmp_path` and reading it back returns the fixture's contents."""
        _fixture = tmp_path / "experimental.json"
        _payload = {
            "seed": 7,
            "framework": "flask",
            "server": {
                "wsgi_server": "waitress",
                "uvicorn": {"backlog": 1, "ready_timeout_s": 0.5,
                            "terminate_grace_s": 0.1, "kill_grace_s": 0.1},
                "waitress": {"backlog": 1, "threads": 1, "ready_timeout_s": 0.5,
                             "terminate_grace_s": 0.1, "kill_grace_s": 0.1},
                "gunicorn": {"workers": 1, "ready_timeout_s": 0.5,
                             "terminate_grace_s": 0.1, "kill_grace_s": 0.1},
            },
            "dpl": "localhost",
            "run_label": "test-run",
        }
        _fixture.write_text(json.dumps(_payload), encoding="utf-8")
        _cfg = load_experimental_cfg(_fixture)
        assert _cfg["seed"] == 7
        assert _cfg["framework"] == "flask"
        _waitress = load_server_cfg("waitress", _fixture)
        assert _waitress["threads"] == 1

    def test_dflt_path(self) -> None:
        """The exported default path points at `data/config/method/experimental.json` and exists on disk."""
        assert DFLT_EXPERIMENTAL_CFG_PATH.name == "experimental.json"
        assert DFLT_EXPERIMENTAL_CFG_PATH.is_file()
