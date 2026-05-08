"""Demo: JSONL flow record + per-service CSV row formats.

Runnable script (not a pytest test): writes the canonical artefacts to a temp directory, prints them to stdout, and exits. Purpose is to give a reviewer a one-shot view of what each artefact layer looks like before they read the writers' code.

Run from the project root:

    python -m tests.demo.log_format

The `-m` form is required so `from src.experimental...` imports resolve (the project root must be on `sys.path`). All artefacts go to a `tempfile.TemporaryDirectory()` that disappears when the script exits, so nothing is persisted.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from src.experimental.common.io.csv import CsvWriter
from src.experimental.common.io.jsonl import JsonlWriter

# demo flow record data with explicit fields
DEMO_FLOW_RECORD: dict[str, Any] = {
    "req_id": "u47-r0312",
    "kind": "medical_analysis",
    "client_id": "user-47",
    "submitted_ts": 1736282400.123456,
    "completed_ts": 1736282400.139201,
    "outcome": "success",
    "total_latency_s": 0.015745,
    "hops": [
        {
            "service": "TAS_{1}",
            "recv_ts": 1736282400.124,
            "start_ts": 1736282400.125,
            "end_ts": 1736282400.139,
            "status": 200,
            "c_used_at_start": 3,
        },
        {
            "service": "MAS_{2}",
            "recv_ts": 1736282400.126,
            "start_ts": 1736282400.127,
            "end_ts": 1736282400.137,
            "status": 200,
            "c_used_at_start": 5,
        },
    ],
}

# demo per-service CSV schema with explicit fields
DEMO_SVC_COLUMNS: list[str] = [
    "req_id",
    "srv_name",
    "kind",
    "recv_ts",
    "start_ts",
    "local_end_ts",
    "end_ts",
    "c_used_at_start",
    "success",
    "status_code",
    "size_bytes",
]

# demo per-service CSV row data with explicit fields
DEMO_SVC_ROW: dict[str, Any] = {
    "req_id": "u47-r0312",
    "srv_name": "TAS_{1}",
    "kind": "medical_analysis",
    "recv_ts": 1736282400.124,
    "start_ts": 1736282400.125,
    "local_end_ts": 1736282400.138,
    "end_ts": 1736282400.139,
    "c_used_at_start": 3,
    "success": True,
    "status_code": 200,
    "size_bytes": 1024,
}


def _show_jsonl_record(tmp: Path, record: dict[str, Any]) -> None:
    """Write one JSONL flow record to a temp file and print the file content.

    Args:
        tmp (Path): caller-managed temporary directory.
        record (dict[str, Any]): canonical per-request flow record.
    """
    _path = tmp / "demo.jsonl"
    with JsonlWriter(_path) as _w:
        _w.write(record)
    print("\n=== JSONL flow record (one line per end-to-end request) ===")
    print(_path.read_text(encoding="utf-8"))


def _show_csv_rows(tmp: Path, columns: list[str], row: dict[str, Any]) -> None:
    """Write two per-service CSV rows to a temp file and print the file content.

    Args:
        tmp (Path): caller-managed temporary directory.
        columns (list[str]): per-service CSV column schema.
        row (dict[str, Any]): canonical per-service invocation row.
    """
    _path = tmp / "TAS__pid12345.csv"
    _alarm_row = {**row, "req_id": "u48-r0001", "kind": "alarm"}
    with CsvWriter(_path, columns) as _w:
        _w.write_row(row)
        _w.write_row(_alarm_row)
    print("\n=== Per-service CSV (one row per invocation, one file per service-pid) ===")
    print(_path.read_text(encoding="utf-8"))


def main() -> None:
    """Print the canonical JSONL flow record and per-service CSV row to stdout.

    The temp directory is created and torn down by `tempfile.TemporaryDirectory`,
    so nothing persists between invocations.
    """
    with tempfile.TemporaryDirectory() as _tmp_str:
        _tmp = Path(_tmp_str)
        _show_jsonl_record(_tmp, DEMO_FLOW_RECORD)
        _show_csv_rows(_tmp, DEMO_SVC_COLUMNS, DEMO_SVC_ROW)


if __name__ == "__main__":
    main()
