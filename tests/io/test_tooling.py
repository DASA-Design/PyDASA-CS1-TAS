# -*- coding: utf-8 -*-
"""
Module test_tooling.py
======================

Contract tests for the calibration-envelope loader and derivation helpers in `src.io.tooling`.

    - **TestCalibrationLoader**: `find_latest_calibration` / `load_latest_calibration` resolve the newest per-host JSON; floor / band / age accessors parse the loopback / jitter / timestamp blocks.
    - **TestRateSweepAccessors**: `rate_sweep_calibrated_rate` and `rate_sweep_loss_at` read the optional `rate_sweep` block and tolerate missing keys / int-vs-float key form.
    - **TestLoadDimCard**: `load_dim_card` returns a pre-baked `dimensional_card` verbatim or lazy-derives via `src.methods.calibration.derive_calib_coefs`.
"""
# native python modules
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# test stack
import pytest

# target under test
from src.io import tooling as cal


def _make_envelope(*, loopback_median_us: float = 2048.1,
                   jitter_p99_us: float = 1274.5,
                   when: Optional[datetime] = None,
                   hostname: Optional[str] = None) -> dict:
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
def _isolated_calib_dir(monkeypatch: pytest.MonkeyPatch,  # pyright: ignore[reportUnusedFunction]
                        tmp_path: Path) -> Path:
    """*_isolated_calib_dir()* redirect `tooling._CALIB_ROOT` (and the legacy `_CALIB_DIR` alias) to a tmp path so every test starts with a clean slate. Returns the per-`dpl` subdirectory matching the default deployment so existing tests that drop files at the returned path keep working."""
    _root = tmp_path / "calibration"
    _root.mkdir()
    _dir = _root / cal._DEFAULT_CALIB_DPL
    _dir.mkdir()
    monkeypatch.setattr(cal, "_CALIB_ROOT", _root)
    monkeypatch.setattr(cal, "_CALIB_DIR", _dir)
    return _dir


class TestCalibrationLoader:
    """**TestCalibrationLoader** the find / load / accessor trio resolves the newest per-host envelope and parses its loopback / jitter / timestamp blocks into floats."""

    def test_none_on_empty_dir(self,
                               _isolated_calib_dir: Path) -> None:
        """*test_none_on_empty_dir()* `find_latest_calibration() is None` and `load_latest_calibration() is None` for an empty `_CALIB_DIR`."""
        assert cal.find_latest_calibration() is None
        assert cal.load_latest_calibration() is None

    def test_picks_newest_for_host(self,
                                   _isolated_calib_dir: Path) -> None:
        """*test_picks_newest_for_host()* the highest-mtime file with a matching `<hostname>_` prefix wins; an `OTHER-HOST_` file with a strictly larger mtime is skipped."""
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
        # set OTHER-HOST mtime strictly above the local _new file so the host filter, not recency, decides the winner
        _now = datetime.now().timestamp()
        os.utime(_old_path, (_now - 3600, _now - 3600))
        os.utime(_new_path, (_now, _now))
        os.utime(_other_path, (_now + 10, _now + 10))
        _latest = cal.find_latest_calibration()
        assert _latest is not None
        assert _latest.name == _new_path.name
        _loaded = cal.load_latest_calibration()
        assert _loaded is not None
        assert _loaded["loopback"]["median_us"] == 2000.0
        assert _loaded["output_path"].endswith(_new_path.name)

    def test_floor_band_parse_envelope(self) -> None:
        """*test_floor_band_parse_envelope()* `calibration_floor_us` returns `loopback.median_us`; `calibration_band_us` returns `jitter.p99_us`; both fall back to 0.0 when the block is missing."""
        _env = _make_envelope(loopback_median_us=2345.6, jitter_p99_us=1275.0)
        assert cal.calibration_floor_us(_env) == pytest.approx(2345.6)
        assert cal.calibration_band_us(_env) == pytest.approx(1275.0)
        assert cal.calibration_floor_us({}) == 0.0
        assert cal.calibration_band_us({}) == 0.0

    def test_age_hours_from_timestamp(self) -> None:
        """*test_age_hours_from_timestamp()* `calibration_age_hours` returns hours since the envelope's `timestamp`; `float("inf")` when missing or unparseable."""
        # 0.4-0.7 h band on a 30 min envelope absorbs scheduler jitter on slow CI
        _fresh = _make_envelope(when=datetime.now() - timedelta(minutes=30))
        _age = cal.calibration_age_hours(_fresh)
        assert 0.4 < _age < 0.7
        _stale = _make_envelope(when=datetime.now() - timedelta(hours=48))
        assert cal.calibration_age_hours(_stale) > 40.0
        assert cal.calibration_age_hours({}) == float("inf")
        assert cal.calibration_age_hours({"timestamp": "not-a-date"}) == float("inf")


class TestRateSweepAccessors:
    """**TestRateSweepAccessors** the two rate-sweep helpers tolerate a missing `rate_sweep` block (opted-out runs) and accept either `"100.0"` or `"100"` aggregate keys."""

    def test_rate_none_without_block(self) -> None:
        """*test_rate_none_without_block()* `rate_sweep_calibrated_rate({}) is None` and `rate_sweep_calibrated_rate({"rate_sweep": None}) is None`."""
        assert cal.rate_sweep_calibrated_rate({}) is None
        assert cal.rate_sweep_calibrated_rate({"rate_sweep": None}) is None

    def test_rate_returns_float(self) -> None:
        """*test_rate_returns_float()* `rate_sweep_calibrated_rate` returns `calibrated_rate` as a float, or `None` when the field is `None`."""
        _env = {"rate_sweep": {"calibrated_rate": 275.0,
                               "target_loss_pct": 2.0}}
        assert cal.rate_sweep_calibrated_rate(_env) == pytest.approx(275.0)
        _env_empty = {"rate_sweep": {"calibrated_rate": None,
                                     "target_loss_pct": 2.0}}
        assert cal.rate_sweep_calibrated_rate(_env_empty) is None

    def test_loss_at_rate_reads_agg(self) -> None:
        """*test_loss_at_rate_reads_agg()* `rate_sweep_loss_at(env, r)` returns `aggregates[str(r)]["mean_loss_pct"]`; falls back to `aggregates[str(int(r))]`; returns `None` when unmatched or block missing."""
        _env = {"rate_sweep": {
            "aggregates": {
                "100.0": {"mean_loss_pct": 0.8},
                "200.0": {"mean_loss_pct": 1.2},
                "300.0": {"mean_loss_pct": 4.4},
            },
        }}
        assert cal.rate_sweep_loss_at(_env, 100.0) == pytest.approx(0.8)
        assert cal.rate_sweep_loss_at(_env, 200.0) == pytest.approx(1.2)
        assert cal.rate_sweep_loss_at(_env, 999.0) is None
        _env_int = {"rate_sweep": {"aggregates": {
            "100": {"mean_loss_pct": 0.5},
        }}}
        assert cal.rate_sweep_loss_at(_env_int, 100.0) == pytest.approx(0.5)
        assert cal.rate_sweep_loss_at({}, 100.0) is None
        assert cal.rate_sweep_loss_at({"rate_sweep": {}}, 100.0) is None


class TestLoadDimCard:
    """**TestLoadDimCard** `load_dim_card` returns a pre-baked `dimensional_card` block verbatim, otherwise lazy-derives via `src.methods.calibration.derive_calib_coefs`."""

    def test_none_without_envelope(self,
                                    _isolated_calib_dir: Path) -> None:
        """*test_none_without_envelope()* `load_dim_card() is None` when no calibration JSON exists for the host."""
        assert cal.load_dim_card() is None

    def test_returns_prebaked_block(self,
                                    _isolated_calib_dir: Path) -> None:
        """*test_returns_prebaked_block()* an envelope carrying `dimensional_card` is returned verbatim (`meta.marker == "prebaked"` round-trips)."""
        _env = _make_envelope()
        _env["dimensional_card"] = {"\\theta_{CALIB}": [1.0, 2.0],
                                    "meta": {"tag": "CALIB", "marker": "prebaked"}}
        _path = _isolated_calib_dir / f"{socket.gethostname()}_20260424_010101.json"
        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_env, _fh)
        _card = cal.load_dim_card()
        assert _card is not None
        assert _card["meta"]["marker"] == "prebaked"

    def test_lazy_derives_without_block(self,
                                        _isolated_calib_dir: Path) -> None:
        """*test_lazy_derives_without_block()* an envelope without `dimensional_card` but with `handler_scaling` + `loopback` lazy-derives a card via `derive_calib_coefs`; `meta.pipeline` starts with `"pydasa"`."""
        _env = _make_envelope(loopback_median_us=1000.0)
        _env["handler_scaling"] = {
            "1": {"median_us": 1500.0},
            "10": {"median_us": 6000.0},
        }
        _env["args"] = {"uvicorn_backlog": 16384}
        _path = _isolated_calib_dir / f"{socket.gethostname()}_20260424_020202.json"
        with _path.open("w", encoding="utf-8") as _fh:
            json.dump(_env, _fh)
        _card = cal.load_dim_card()
        assert _card is not None
        assert "\\theta_{CALIB}" in _card
        assert _card["meta"]["pipeline"].lower().startswith("pydasa")
