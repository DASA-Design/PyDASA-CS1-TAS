"""Tests for `src.experimental.prototype.calibration.envelope`.

Logic-only checks: skeleton shape, path resolution, round-trip via the underlying writer.
"""

from __future__ import annotations

import socket
from pathlib import Path

from src.experimental.prototype.calibration.envelope import (
    DFLT_RESULTS_BASE,
    PROBE_SECTIONS,
    envelope_path,
    make_envelope,
    read_envelope,
    write_envelope,
)


class TestEnvelope:
    """Skeleton builder + path resolution + round-trip."""

    def test_make_top_level_keys(self) -> None:
        """The skeleton carries `version`, `run_id`, `host`, `dpl`, `framework`, `wsgi_server`, `started_ts`, `finished_ts`, plus one entry per probe section (including `workers_scaling`)."""
        _env = make_envelope(run_id="r-1",
                             dpl="localhost",
                             framework="fastapi")
        assert _env["version"] == "1.0"
        assert _env["run_id"] == "r-1"
        assert _env["dpl"] == "localhost"
        assert _env["framework"] == "fastapi"
        assert _env["wsgi_server"] is None
        assert _env["finished_ts"] is None
        assert "workers_scaling" in PROBE_SECTIONS
        for _section in PROBE_SECTIONS:
            assert _section in _env

    def test_make_sections_empty(self) -> None:
        """Every section in `PROBE_SECTIONS` begins as `{}` so probe modules can mutate them in place."""
        _env = make_envelope(run_id="r-1",
                             dpl="localhost",
                             framework="fastapi")
        for _section in PROBE_SECTIONS:
            assert _env[_section] == {}

    def test_make_default_host(self) -> None:
        """When `host=None`, the skeleton uses `socket.gethostname()` so cross-host runs are distinguishable on disk."""
        _env = make_envelope(run_id="r-1", dpl="localhost", framework="fastapi")
        assert _env["host"] == socket.gethostname()

    def test_make_explicit_host(self) -> None:
        """An explicit `host` kwarg overrides the default; useful for tests and runs that need a deterministic envelope filename."""
        _env = make_envelope(run_id="r-1",
                             dpl="localhost",
                             framework="fastapi",
                             host="test-host")
        assert _env["host"] == "test-host"

    def test_make_started_ts_set(self) -> None:
        """`started_ts` is stamped at construction (positive float); `finished_ts` is `None` until the caller updates it."""
        _env = make_envelope(run_id="r-1",
                             dpl="localhost",
                             framework="fastapi")
        assert isinstance(_env["started_ts"], float)
        assert _env["started_ts"] > 0
        assert _env["finished_ts"] is None

    def test_path_layout(self) -> None:
        """Path resolution stitches deployment mode, host, and run id under the configured base directory."""
        _base = Path("/tmp/calib")
        _path = envelope_path(dpl="localhost",
                              host="hX",
                              run_id="r-1",
                              base=_base)
        assert _path == _base / "localhost" / "hX_r-1.json"

    def test_path_default_base(self) -> None:
        """Omitting the base directory resolves under the canonical results tree."""
        _path = envelope_path(dpl="localhost",
                              host="hX",
                              run_id="r-1")
        assert _path == DFLT_RESULTS_BASE / "localhost" / "hX_r-1.json"

    def test_round_trip(self, tmp_path: Path) -> None:
        """A freshly-built envelope written to `tmp_path` and read back equals the input, with the probe sections still mutable as dicts."""
        _env = make_envelope(run_id="r-1",
                             dpl="localhost",
                             framework="fastapi",
                             host="hX")
        # populate one section so a probe edit round-trips
        _env["timer"]["median_ns"] = 100
        _path = tmp_path / "envelope.json"
        write_envelope(_path, _env)
        _back = read_envelope(_path)
        assert _back == _env
