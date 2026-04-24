# -*- coding: utf-8 -*-
"""
Module tests/io/test_calibration.py
===================================

Contract tests for the calibration-envelope loader and derivation helpers in `src.io.calibration`.

**TestCalibrationLoader**
    - `test_returns_none_when_no_envelope_present()` find / load return `None` when the host has no calibration file on disk.
    - `test_picks_newest_envelope_for_host()` the loader returns the newest matching file and filters out other hosts.
    - `test_floor_and_band_accessors_parse_envelope()` floor / band helpers read `loopback.median_us` and `jitter.p99_us`.
    - `test_age_hours_reads_timestamp()` age helper reads `timestamp` and returns hours since.
"""
# native python modules
from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from pathlib import Path

# test stack
import pytest

# target under test
from src.io import calibration as cal


def _make_envelope(*, loopback_median_us: float = 2048.1,
                   jitter_p99_us: float = 1274.5,
                   when: datetime | None = None,
                   hostname: str | None = None) -> dict:
    """*_make_envelope()* build a minimal calibration envelope for tests."""
    if when is None:
        when = datetime.now()
    if hostname is None:
        hostname = socket.gethostname()
    return {
        "host_profile": {"hostname": hostname},
        "timer": {"min_ns": 100},
        "jitter": {"p99_us": jitter_p99_us},
        "loopback": {"median_us": loopback_median_us},
        "handler_scaling": {},
        "timestamp": when.isoformat(timespec="seconds"),
    }


@pytest.fixture
def _isolated_calib_dir(monkeypatch, tmp_path: Path) -> Path:
    """*_isolated_calib_dir()* redirect the module's `_CALIB_DIR` to a tmp path so every test starts with a clean slate."""
    _dir = tmp_path / "calibration"
    _dir.mkdir()
    monkeypatch.setattr(cal, "_CALIB_DIR", _dir)
    return _dir


class TestCalibrationLoader:
    """**TestCalibrationLoader** contract for the find / load / accessor trio."""

    def test_returns_none_when_no_envelope_present(self,
                                                   _isolated_calib_dir: Path) -> None:
        """*test_returns_none_when_no_envelope_present()* loader returns `None` with an empty directory."""
        assert cal.find_latest_calibration() is None
        assert cal.load_latest_calibration() is None

    def test_picks_newest_envelope_for_host(self,
                                            _isolated_calib_dir: Path) -> None:
        """*test_picks_newest_envelope_for_host()* loader returns the most-recently-written file and ignores other-host files."""
        _host = socket.gethostname().replace(" ", "-")

        _old_env = _make_envelope(loopback_median_us=1000.0,
                                  when=datetime.now() - timedelta(hours=12))
        _new_env = _make_envelope(loopback_median_us=2000.0,
                                  when=datetime.now())
        _other_env = _make_envelope(loopback_median_us=9999.0,
                                    hostname="OTHER-HOST")

        _old_path = _isolated_calib_dir / f"{_host}_20260420_010203.json"
        _new_path = _isolated_calib_dir / f"{_host}_20260423_181646.json"
        _other_path = _isolated_calib_dir / "OTHER-HOST_20260423_181646.json"

        for _p, _env in [(_old_path, _old_env),
                         (_new_path, _new_env),
                         (_other_path, _other_env)]:
            with _p.open("w", encoding="utf-8") as _fh:
                json.dump(_env, _fh)

        # nudge mtimes so ordering is unambiguous regardless of fs resolution
        import os
        _now = datetime.now().timestamp()
        os.utime(_old_path, (_now - 3600, _now - 3600))
        os.utime(_new_path, (_now, _now))
        os.utime(_other_path, (_now + 10, _now + 10))  # newer, but wrong host

        _latest = cal.find_latest_calibration()
        assert _latest is not None
        assert _latest.name == _new_path.name

        _loaded = cal.load_latest_calibration()
        assert _loaded is not None
        assert _loaded["loopback"]["median_us"] == 2000.0
        assert _loaded["output_path"].endswith(_new_path.name)

    def test_floor_and_band_accessors_parse_envelope(self) -> None:
        """*test_floor_and_band_accessors_parse_envelope()* floor reads `loopback.median_us`; band reads `jitter.p99_us`."""
        _env = _make_envelope(loopback_median_us=2345.6, jitter_p99_us=1275.0)
        assert cal.calibration_floor_us(_env) == pytest.approx(2345.6)
        assert cal.calibration_band_us(_env) == pytest.approx(1275.0)

        # graceful defaults when blocks are missing
        assert cal.calibration_floor_us({}) == 0.0
        assert cal.calibration_band_us({}) == 0.0

    def test_age_hours_reads_timestamp(self) -> None:
        """*test_age_hours_reads_timestamp()* age helper returns hours since the envelope was written; infinity when timestamp is missing or unparseable."""
        _fresh = _make_envelope(when=datetime.now() - timedelta(minutes=30))
        _age = cal.calibration_age_hours(_fresh)
        assert 0.4 < _age < 0.7  # ~0.5 h

        _stale = _make_envelope(when=datetime.now() - timedelta(hours=48))
        assert cal.calibration_age_hours(_stale) > 40.0

        assert cal.calibration_age_hours({}) == float("inf")
        assert cal.calibration_age_hours({"timestamp": "not-a-date"}) == float("inf")
