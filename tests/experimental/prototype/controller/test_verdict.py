"""Tests for `src.experimental.prototype.controller.verdict`.

**TestComputeVerdict**:

- `test_clean_run`: 10 successes yield A=C=10, F=0, R1=0, R2=mean(latency); both pass.
- `test_with_failures`: 8 success + 2 fail yield R1=0.2; R2 averages over successes only.
- `test_empty_flows`: missing JSONL yields A=0, R1=R2=0; both pass (degenerate).
- `test_thresholds`: same data, different thresholds flip the pass flags.
- `test_residual`: `client_n_requests > A_server` reports the positive flow-balance residual.

**TestWriters**:

- `test_verdict_round_trip`: `write_verdict_json` writes JSON that reads back identically.
- `test_window_round_trip`: `write_window_parquet` writes a DataFrame readable via pandas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.experimental.prototype.controller.verdict import (
    compute_verdict,
    write_verdict_json,
    write_window_parquet,
)

_THRESHOLDS = {"r1_max": 0.0003, "r2_max": 0.026}


def _write_flows(tmp_path: Path, records: list[dict]) -> Path:
    """Write `records` to a JSONL file in `tmp_path`.

    Args:
        tmp_path (Path): test directory.
        records (list[dict]): one record per line.

    Returns:
        Path: written JSONL file.
    """
    _path = tmp_path / "flows.jsonl"
    with _path.open("w", encoding="utf-8") as _fh:
        for _r in records:
            _fh.write(json.dumps(_r) + "\n")
    return _path


def _ok(req_id: str,
        latency_s: float,
        recv_ts: float = 0.0,
        send_ts: float | None = None) -> dict:
    """Build a successful (`status=200`) flow record.

    Args:
        req_id (str): request identifier.
        latency_s (float): total latency in seconds.
        recv_ts (float, optional): server-side receive timestamp. Defaults to 0.0.
        send_ts (float | None, optional): server-side send timestamp. Defaults to `recv_ts + latency_s`.

    Returns:
        dict: flow record.
    """
    if send_ts is None:
        send_ts = recv_ts + latency_s
    return {
        "req_id": req_id,
        "status": 200,
        "tas_recv_ts": recv_ts,
        "tas_send_ts": send_ts,
        "total_latency_s": latency_s,
    }


def _fail(req_id: str,
          recv_ts: float = 0.0,
          send_ts: float = 0.005) -> dict:
    """Build a failed (`status=502`) flow record.

    Args:
        req_id (str): request identifier.
        recv_ts (float, optional): server-side receive timestamp. Defaults to 0.0.
        send_ts (float, optional): server-side send timestamp. Defaults to 0.005.

    Returns:
        dict: flow record.
    """
    return {
        "req_id": req_id,
        "status": 502,
        "tas_recv_ts": recv_ts,
        "tas_send_ts": send_ts,
        "total_latency_s": send_ts - recv_ts,
    }


class TestComputeVerdict:
    """`compute_verdict` over synthetic flow JSONL.

    Covers the operational identities (A, C, F, T, X_0, R), the R1 / R2 pass / fail logic against the thresholds, the degenerate empty-flows case, and the optional flow-balance residual.
    """

    def test_clean_run(self, tmp_path: Path) -> None:
        """*test_clean_run()* 10 successes yield A=C=10, F=0, R1=0, R2=mean(latency)."""
        _records = [
            _ok(f"r{_i}", 0.005, recv_ts=float(_i), send_ts=float(_i) + 0.005)
            for _i in range(10)
        ]
        _flows = _write_flows(tmp_path, _records)
        _v = compute_verdict(
            flows_path=_flows,
            adp="baseline",
            run_id="rid",
            stop_reason="n_reached",
            n_planned=10,
            thresholds=_THRESHOLDS,
        )
        assert _v["operational"]["A"] == 10
        assert _v["operational"]["C"] == 10
        assert _v["operational"]["F"] == 0
        assert _v["r1"]["value"] == 0.0
        assert _v["r1"]["pass"] is True
        assert _v["r2"]["value"] == 0.005
        assert _v["r2"]["pass"] is True

    def test_with_failures(self, tmp_path: Path) -> None:
        """*test_with_failures()* 8 success + 2 fail yield R1=0.2; R2 averages over successes only."""
        _records = (
            [_ok(f"r{_i}", 0.01) for _i in range(8)]
            + [_fail(f"f{_i}") for _i in range(2)]
        )
        _flows = _write_flows(tmp_path, _records)
        _v = compute_verdict(
            flows_path=_flows,
            adp="s1",
            run_id="rid",
            stop_reason="r1_breach",
            n_planned=10,
            thresholds=_THRESHOLDS,
        )
        assert _v["operational"]["A"] == 10
        assert _v["operational"]["C"] == 8
        assert _v["operational"]["F"] == 2
        assert _v["r1"]["value"] == 0.2
        assert _v["r1"]["pass"] is False
        assert _v["r2"]["value"] == 0.01

    def test_empty_flows(self, tmp_path: Path) -> None:
        """*test_empty_flows()* missing JSONL yields A=0, R1/R2=0; both pass (degenerate)."""
        _v = compute_verdict(
            flows_path=tmp_path / "missing.jsonl",
            adp="baseline",
            run_id="rid",
            stop_reason="n_reached",
            n_planned=0,
            thresholds=_THRESHOLDS,
        )
        assert _v["operational"]["A"] == 0
        assert _v["r1"]["value"] == 0.0
        assert _v["r2"]["value"] == 0.0
        assert _v["r1"]["pass"] is True
        assert _v["r2"]["pass"] is True

    def test_thresholds(self, tmp_path: Path) -> None:
        """*test_thresholds()* same data, different thresholds flip the pass flags."""
        _records = [_ok(f"r{_i}", 0.02) for _i in range(10)]
        _flows = _write_flows(tmp_path, _records)
        _lax = compute_verdict(
            flows_path=_flows,
            adp="baseline",
            run_id="rid",
            stop_reason="n_reached",
            n_planned=10,
            thresholds={"r1_max": 0.5, "r2_max": 0.1},
        )
        assert _lax["r2"]["pass"] is True
        _strict = compute_verdict(
            flows_path=_flows,
            adp="baseline",
            run_id="rid",
            stop_reason="n_reached",
            n_planned=10,
            thresholds={"r1_max": 0.5, "r2_max": 0.001},
        )
        assert _strict["r2"]["pass"] is False

    def test_residual(self, tmp_path: Path) -> None:
        """*test_residual()* `client_n_requests > A_server` reports the positive flow-balance residual."""
        _records = [_ok(f"r{_i}", 0.005) for _i in range(8)]
        _flows = _write_flows(tmp_path, _records)
        _v = compute_verdict(
            flows_path=_flows,
            adp="baseline",
            run_id="rid",
            stop_reason="n_reached",
            n_planned=10,
            thresholds=_THRESHOLDS,
            client_n_requests=10,
        )
        assert _v["flow_balance_residual"] == 0.2


class TestWriters:
    """`write_verdict_json` + `write_window_parquet` round-trips.

    Covers that the JSON writer produces a file readable back identically and that the parquet writer produces a DataFrame pandas can read.
    """

    def test_verdict_round_trip(self, tmp_path: Path) -> None:
        """*test_verdict_round_trip()* `write_verdict_json` writes JSON that reads back identically."""
        _verdict = {
            "adp": "s2",
            "r1": {"value": 0.001, "pass": False},
        }
        _out = tmp_path / "verdict.json"
        write_verdict_json(_verdict, _out)
        with _out.open(encoding="utf-8") as _fh:
            _back = json.load(_fh)
        assert _back == _verdict

    def test_window_round_trip(self, tmp_path: Path) -> None:
        """*test_window_round_trip()* `write_window_parquet` writes a DataFrame pandas can read back."""
        _history = [
            {
                "req_id": "r0",
                "ts": 1.0,
                "status": 200,
                "latency_s": 0.01,
                "n_in_window": 1,
                "r1_running": 0.0,
                "r2_running": 0.01,
                "r1_breach": False,
                "r2_breach": False,
            },
            {
                "req_id": "r1",
                "ts": 2.0,
                "status": 502,
                "latency_s": 0.005,
                "n_in_window": 2,
                "r1_running": 0.5,
                "r2_running": 0.01,
                "r1_breach": True,
                "r2_breach": False,
            },
        ]
        _out = tmp_path / "w" / "h.parquet"
        write_window_parquet(_history, _out)
        _df = pd.read_parquet(_out)
        assert len(_df) == 2
        assert _df.iloc[0]["req_id"] == "r0"
        assert bool(_df.iloc[1]["r1_breach"]) is True
