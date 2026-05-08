"""Tests for `src.experimental.prototype.client.config`.

**TestClientConfig**:

- `test_load_default`: confirms the loader reads the default `data/config/method/prototype/client.json` and returns a populated dict so the orchestrator can thread values into the client constructors.
- `test_top_level_keys`: confirms every section the orchestrator threads (`users`, `ramp`, `sender`, `guard`, `stats`) is present, so a missing section is caught here rather than at run start.
- `test_load_custom_path`: confirms the loader honours an explicit path argument so tests can point it at fixtures without monkeying with the working directory.
- `test_default_path_constant`: confirms the exported `DFLT_CLIENT_CFG_PATH` matches the canonical client.json location so callers and tests share one default.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.experimental.prototype.client.config import (
    DFLT_CLIENT_CFG_PATH,
    load_client_cfg,
)


class TestClientConfig:
    """Loader for `data/config/method/prototype/client.json`."""

    def test_load_default(self) -> None:
        """Loading the default path returns a non-empty dict, demonstrating the JSON file exists and parses cleanly so the orchestrator can rely on it being present."""
        _cfg = load_client_cfg()
        assert isinstance(_cfg, dict)
        assert len(_cfg) > 0

    def test_top_level_keys(self) -> None:
        """The loaded config carries every section the orchestrator threads into client constructors (`users`, `ramp`, `sender`, `guard`, `stats`); any missing section is a load-time failure rather than a run-time surprise."""
        _cfg = load_client_cfg()
        for _key in ("users", "ramp", "sender", "guard", "stats"):
            assert _key in _cfg, f"missing client.json section: {_key}"

    def test_load_custom_path(self, tmp_path: Path) -> None:
        """Loading from an explicit path returns whatever JSON the path holds, demonstrating the loader respects its argument so tests can point at fixtures without changing the working directory.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
        """
        _path = tmp_path / "client.json"
        _payload = {"sender": {"payload_size_bytes": 64}}
        _path.write_text(json.dumps(_payload), encoding="utf-8")
        _cfg = load_client_cfg(_path)
        assert _cfg == _payload

    def test_default_path_constant(self) -> None:
        """The exported `DFLT_CLIENT_CFG_PATH` constant points at `data/config/method/prototype/client.json` so callers and tests share one canonical default."""
        _expected = Path("data") / "config" / "method" / "prototype" / "client.json"
        assert DFLT_CLIENT_CFG_PATH == _expected
