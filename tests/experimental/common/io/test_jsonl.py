"""Tests for `src.experimental.common.io.jsonl`.

**TestJsonlWriter**:

- `test_write_one`: confirms a single record produces exactly one parseable JSON line so the file is grep-friendly from the very first write.
- `test_write_many`: confirms N records produce N lines in submission order so flow logs preserve causality across requests.
- `test_context_manager_closes`: confirms `__exit__` flushes and closes the handle, and that a follow-up `close()` is a safe no-op.
- `test_append_mode`: confirms a second writer instance opens in append mode rather than truncating, so a crashing process leaves complete prefix data on disk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.experimental.common.io.jsonl import JsonlWriter


class TestJsonlWriter:
    """Append-only JSONL writer."""

    def test_write_one(self,
                       tmp_path: Path,
                       sample_jsonl_record: dict[str, Any],) -> None:
        """Writing one record yields exactly one newline-terminated JSON line, demonstrating the writer respects the JSONL contract on its first write.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_jsonl_record (dict[str, Any]): canonical flow record from conftest.
        """
        _path = tmp_path / "flows.jsonl"
        with JsonlWriter(_path) as _w:
            _w.write(sample_jsonl_record)
        _lines = _path.read_text(encoding="utf-8").splitlines()
        assert len(_lines) == 1
        assert json.loads(_lines[0]) == sample_jsonl_record

    def test_write_many(self,
                        tmp_path: Path,
                        sample_jsonl_record: dict[str, Any]) -> None:
        """Writing N records produces N parseable lines preserving submission order, so downstream readers can replay the request stream as recorded.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_jsonl_record (dict[str, Any]): base record; cloned with distinct `req_id` per write.
        """
        _path = tmp_path / "flows.jsonl"
        _records = [{**sample_jsonl_record, "req_id": f"r{_i}"} for _i in range(5)]
        with JsonlWriter(_path) as _w:
            for _record in _records:
                _w.write(_record)
        _lines = _path.read_text(encoding="utf-8").splitlines()
        _parsed = [json.loads(_line) for _line in _lines]
        assert _parsed == _records

    def test_context_manager_closes(self,
                                    tmp_path: Path,
                                    sample_jsonl_record: dict[str, Any]) -> None:
        """Exiting the context manager flushes and closes the handle; a subsequent `close()` is idempotent (no double-close error), so cleanup is safe to call defensively.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_jsonl_record (dict[str, Any]): canonical flow record from conftest.
        """
        _path = tmp_path / "flows.jsonl"
        _w = JsonlWriter(_path)
        with _w:
            _w.write(sample_jsonl_record)
        _w.close()
        _content = _path.read_text(encoding="utf-8")
        assert _content.endswith("\n")
        assert json.loads(_content.strip()) == sample_jsonl_record

    def test_append_mode(self,
                         tmp_path: Path,
                         sample_jsonl_record: dict[str, Any]) -> None:
        """A second writer instance against the same path appends rather than truncates, so writes from a crashed-and-restarted process accumulate instead of overwriting earlier records.

        Args:
            tmp_path (Path): pytest's per-test temporary directory.
            sample_jsonl_record (dict[str, Any]): base record cloned for two distinct writes.
        """
        _path = tmp_path / "flows.jsonl"
        with JsonlWriter(_path) as _w:
            _w.write({**sample_jsonl_record, "req_id": "first"})
        with JsonlWriter(_path) as _w:
            _w.write({**sample_jsonl_record, "req_id": "second"})
        _lines = _path.read_text(encoding="utf-8").splitlines()
        assert len(_lines) == 2
