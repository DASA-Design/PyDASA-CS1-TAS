# -*- coding: utf-8 -*-
"""
Module test_envelope.py
=======================

Pin the boundary contract of `output_path`, `write_envelope`, `find_latest`, and `load_latest`. Path shape is `data/results/calibration/<dpl>/<host>_<stamp>.json`; `dpl` validation rejects unknown values; the writer creates the per-dpl directory and stamps `output_path` + `dpl` onto the envelope; the loader returns None when nothing matches and otherwise attaches `output_path` to the parsed dict.

`tmp_path` (pytest builtin) + `monkeypatch.setattr` redirect `_CALIB_ROOT` per test so the on-disk `data/results/calibration/` tree never gets touched by the suite.

    - **TestEnvelopeIO** path validation, host normalisation, stamp default, write -> find -> load round-trip, multi-file mtime ordering, host-prefix filter, missing-dir + missing-host return None.
"""
# native python modules
import json
import socket
from pathlib import Path

# testing framework
import pytest

# module under test
from src.calibration import (find_latest,
                             load_latest,
                             output_path,
                             write_envelope)
from src.calibration import envelope as _env_mod


@pytest.fixture
def calib_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """*calib_root()* redirect `_CALIB_ROOT` at the envelope module to `tmp_path / "calibration"` so writes stay inside the pytest sandbox.

    Args:
        tmp_path: per-test pytest tmp dir.
        monkeypatch: pytest's attribute monkeypatcher.

    Returns:
        Path: the redirected root.
    """
    _root = tmp_path / "calibration"
    monkeypatch.setattr(_env_mod, "_CALIB_ROOT", _root)
    return _root


class TestEnvelopeIO:
    """**TestEnvelopeIO** path-shape + I/O round-trip contract: `output_path` returns `<root>/<dpl>/<host>_<stamp>.json`; unknown `dpl` raises; `write_envelope` creates the per-dpl dir, writes valid JSON, stamps `output_path` + `dpl` onto the envelope; `find_latest` returns the newest mtime match (or None); `load_latest` parses the file and attaches `output_path`."""

    def test_invalid_dpl_raises(self) -> None:
        """*test_invalid_dpl_raises()* `output_path("not-a-dpl")` raises `ValueError` with `"not recognised"` in the message."""
        with pytest.raises(ValueError, match="not recognised"):
            output_path("not-a-dpl")

    def test_valid_dpls(self, calib_root: Path) -> None:
        """*test_valid_dpls()* `output_path` accepts `"localhost"` and `"multiprocess"`; both produce paths under the corresponding `<root>/<dpl>/` subdir."""
        _p_local = output_path("localhost", host="HOST", stamp="20260101_000000")
        _p_multi = output_path("multiprocess", host="HOST", stamp="20260101_000000")
        assert _p_local == calib_root / "localhost" / "HOST_20260101_000000.json"
        assert _p_multi == calib_root / "multiprocess" / "HOST_20260101_000000.json"

    def test_default_host_is_socket_hostname(self, calib_root: Path) -> None:
        """*test_default_host_is_socket_hostname()* with no `host` arg, `output_path` uses `socket.gethostname()` (with spaces normalised to hyphens)."""
        _expected = socket.gethostname().replace(" ", "-")
        _p = output_path("localhost", stamp="20260101_000000")
        assert _p.name == f"{_expected}_20260101_000000.json"

    def test_host_space_normalisation(self, calib_root: Path) -> None:
        """*test_host_space_normalisation()* a host containing spaces becomes hyphen-joined in the filename."""
        _p = output_path("localhost", host="MY HOST NAME", stamp="20260101_000000")
        assert _p.name == "MY-HOST-NAME_20260101_000000.json"

    def test_default_stamp_is_iso_like(self, calib_root: Path) -> None:
        """*test_default_stamp_is_iso_like()* with no `stamp` arg, the filename ends in a `_YYYYMMDD_HHMMSS.json` 15-char timestamp pattern (length check; the exact value depends on wall clock)."""
        _p = output_path("localhost", host="HOST")
        # name = "HOST_<15 chars>.json" -> total len 5 + 15 + 5 = 25
        assert _p.name.startswith("HOST_")
        assert _p.name.endswith(".json")
        _stamp = _p.name[len("HOST_"):-len(".json")]
        assert len(_stamp) == 15  # YYYYMMDD_HHMMSS
        assert _stamp[8] == "_"

    def test_write_creates_dir(self, calib_root: Path) -> None:
        """*test_write_creates_dir()* `write_envelope` creates `<root>/<dpl>/` if absent and writes the file there."""
        assert not (calib_root / "localhost").exists()
        _p = write_envelope({"a": 1}, "localhost", host="HOST", stamp="20260101_000000")
        assert (calib_root / "localhost").is_dir()
        assert _p.is_file()

    def test_write_stamps_envelope(self, calib_root: Path) -> None:
        """*test_write_stamps_envelope()* `write_envelope` mutates the input envelope by adding `dpl` and `output_path` keys."""
        _env = {"a": 1}
        _p = write_envelope(_env, "multiprocess", host="HOST", stamp="20260101_000000")
        assert _env["dpl"] == "multiprocess"
        assert _env["output_path"] == str(_p)

    def test_write_produces_valid_json(self, calib_root: Path) -> None:
        """*test_write_produces_valid_json()* the written file parses as JSON and contains the original keys plus `dpl` and `output_path`."""
        write_envelope({"a": 1, "b": "x"}, "localhost",
                       host="HOST", stamp="20260101_000000")
        _p = calib_root / "localhost" / "HOST_20260101_000000.json"
        with _p.open() as _fh:
            _doc = json.load(_fh)
        assert _doc["a"] == 1
        assert _doc["b"] == "x"
        assert _doc["dpl"] == "localhost"
        assert "output_path" in _doc

    def test_write_atomic_rename_no_tmp_left(self, calib_root: Path) -> None:
        """*test_write_atomic_rename_no_tmp_left()* a successful write leaves no `*.tmp` file in the per-dpl dir (the rename completed)."""
        write_envelope({"a": 1}, "localhost",
                       host="HOST", stamp="20260101_000000")
        _tmps = list((calib_root / "localhost").glob("*.tmp"))
        assert _tmps == []

    def test_find_latest_missing_dir(self, calib_root: Path) -> None:
        """*test_find_latest_missing_dir()* `find_latest("localhost")` returns None when `<root>/localhost/` does not exist."""
        assert find_latest("localhost", host="HOST") is None

    def test_find_latest_no_match(self, calib_root: Path) -> None:
        """*test_find_latest_no_match()* with files present but none matching the host prefix, `find_latest` returns None."""
        write_envelope({}, "localhost", host="OTHER", stamp="20260101_000000")
        assert find_latest("localhost", host="HOST") is None

    def test_find_latest_single(self, calib_root: Path) -> None:
        """*test_find_latest_single()* with one matching file, `find_latest` returns its path."""
        _p = write_envelope({}, "localhost", host="HOST", stamp="20260101_000000")
        assert find_latest("localhost", host="HOST") == _p

    def test_find_latest_picks_newest_mtime(self, calib_root: Path) -> None:
        """*test_find_latest_picks_newest_mtime()* with two matching files, `find_latest` returns the one with the larger mtime."""
        _p1 = write_envelope({}, "localhost", host="HOST", stamp="20260101_000000")
        _p2 = write_envelope({}, "localhost", host="HOST", stamp="20260101_120000")
        # bump _p2 mtime so it is unambiguously newer
        _p2.touch()
        assert find_latest("localhost", host="HOST") == _p2

    def test_find_latest_filters_by_dpl(self, calib_root: Path) -> None:
        """*test_find_latest_filters_by_dpl()* a file under `multiprocess/` is invisible to `find_latest("localhost")`."""
        write_envelope({}, "multiprocess", host="HOST", stamp="20260101_000000")
        assert find_latest("localhost", host="HOST") is None

    def test_load_latest_none_when_missing(self, calib_root: Path) -> None:
        """*test_load_latest_none_when_missing()* `load_latest` returns None when no file matches."""
        assert load_latest("localhost", host="HOST") is None

    def test_load_latest_round_trip(self, calib_root: Path) -> None:
        """*test_load_latest_round_trip()* writing then loading returns a dict containing the original keys and `output_path` set to the on-disk path."""
        _written = write_envelope({"a": 1, "b": "x"}, "localhost",
                                  host="HOST", stamp="20260101_000000")
        _loaded = load_latest("localhost", host="HOST")
        assert _loaded is not None
        assert _loaded["a"] == 1
        assert _loaded["b"] == "x"
        assert _loaded["dpl"] == "localhost"
        assert _loaded["output_path"] == str(_written)

    def test_invalid_dpl_to_find_raises(self, calib_root: Path) -> None:
        """*test_invalid_dpl_to_find_raises()* `find_latest("not-a-dpl")` raises `ValueError`."""
        with pytest.raises(ValueError, match="not recognised"):
            find_latest("not-a-dpl")

    def test_invalid_dpl_to_write_raises(self, calib_root: Path) -> None:
        """*test_invalid_dpl_to_write_raises()* `write_envelope({}, "not-a-dpl")` raises `ValueError`."""
        with pytest.raises(ValueError, match="not recognised"):
            write_envelope({}, "not-a-dpl")
