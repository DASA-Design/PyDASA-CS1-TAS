"""Tests for `src.experimental.prototype.calibration.config`.

Logic-only checks: shape on disk, override path, default-path resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.experimental.prototype.calibration.config import (
    DFLT_CALIBRATION_CFG_PATH,
    load_calibration_cfg,
)


class TestCalibrationConfig:
    """Loader for the calibration JSON."""

    def test_top_level_keys(self) -> None:
        """Parsing the on-disk JSON exposes the documented top-level keys."""
        _cfg = load_calibration_cfg()
        assert "hoststats" in _cfg
        assert "rate" in _cfg
        assert "gate" in _cfg

    def test_hoststats_sub_blocks(self) -> None:
        """The hoststats block carries one sub-block per probe (timer / jitter / loopback / handler_scaling)."""
        _hs = load_calibration_cfg()["hoststats"]
        for _key in ("timer", "jitter", "loopback", "handler_scaling"):
            assert _key in _hs

    def test_explicit_path(self, tmp_path: Path) -> None:
        """A caller-supplied path overrides the default; useful for tests and alternate runs."""
        _fixture = tmp_path / "calibration.json"
        _payload = {"hoststats": {}, "rate": {}, "gate": {"noise_floor_pct": 2.5}}
        _fixture.write_text(json.dumps(_payload), encoding="utf-8")
        _cfg = load_calibration_cfg(_fixture)
        assert _cfg["gate"]["noise_floor_pct"] == 2.5

    def test_dflt_path(self) -> None:
        """The default path constant points at the on-disk JSON file."""
        assert DFLT_CALIBRATION_CFG_PATH.name == "calibration.json"
        assert DFLT_CALIBRATION_CFG_PATH.is_file()
