"""Tests for `src.experimental.prototype.target.config`.

**TestTargetCfg**:

- `test_load_default_path`: the on-disk default loads with the populated keys.
- `test_load_explicit_path`: a tmp-path fixture loads through the same loader.
- `test_missing_path_raises`: a non-existent path raises `FileNotFoundError`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.experimental.prototype.target.config import load_target_cfg


class TestTargetCfg:
    """`load_target_cfg` shape + error handling."""

    def test_load_default_path(self) -> None:
        """*test_load_default_path()* the default-path load returns a dict with `catalogue_version`, `workflows`, `target_granularity`, `inject_internal_stage_mu`, `stage_routes`, `tas_base_port`, `trial`, and `atomic_admission`."""
        _cfg = load_target_cfg()
        _required = (
            "catalogue_version",
            "workflows",
            "target_granularity",
            "inject_internal_stage_mu",
            "stage_routes",
            "tas_base_port",
            "trial",
            "atomic_admission",
        )
        for _key in _required:
            assert _key in _cfg
        assert "collapsed" in _cfg["workflows"]
        assert "expanded" in _cfg["workflows"]
        assert _cfg["target_granularity"] == "collapsed"

    def test_load_explicit_path(self, tmp_path: Path) -> None:
        """*test_load_explicit_path()* an explicit `path` argument loads a fixture file."""
        _path = tmp_path / "tiny.json"
        _path.write_text(json.dumps({"catalogue_name": "x"}), encoding="utf-8")
        _cfg = load_target_cfg(_path)
        assert _cfg["catalogue_name"] == "x"

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        """*test_missing_path_raises()* a non-existent path raises `FileNotFoundError`."""
        with pytest.raises(FileNotFoundError):
            load_target_cfg(tmp_path / "nope.json")
