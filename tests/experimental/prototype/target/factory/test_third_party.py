"""Tests for `src.experimental.prototype.target.factory.third_party`.

**TestThirdPartyFactory**:

- `test_round_trip`: building an alarm app and POSTing through an in-memory ASGI transport returns 200 + the expected body shape (no per-pid CSV when `csv_dir` is None).
- `test_mas_result`: an MAS-shaped app attaches a `result` key from the deterministic picker.
- `test_inject_5xx`: a request with `inject_failure="5xx"` returns 502 without touching the handler.
- `test_csv_row`: when `csv_dir` is set, one POST writes one row to `<svc>__pid<PID>.csv`.
- `test_picker_buckets`: the deterministic picker partitions a thousand req_ids into `~33%/33%/34%`.
- `test_safe_filename`: `_safe_filename` removes `{}` and commas so Windows accepts the path.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

import httpx
import pytest

from src.experimental.common.transport.mock import make_test_transport
from src.experimental.prototype.target.factory import third_party
from src.experimental.prototype.target.factory.third_party import (
    _pick_analysis_result,
    _safe_filename,
    build_atomic_fastapi_app,
)


class TestThirdPartyFactory:
    """Atomic-service factory + per-pid CSV side-effect."""

    @pytest.mark.asyncio
    async def test_round_trip(self) -> None:
        """*test_round_trip()* a one-shot POST to an alarm app returns 200 with `service_name` echoed back."""
        _app = build_atomic_fastapi_app(svc_name="AS_{1}",
                                        kind="alarm",
                                        mu=0.0)
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _http:
            _resp = await _http.post("/", json={"req_id": "r0",
                                                "kind": "alarm",
                                                "operation": "triggerAlarm"})
        assert _resp.status_code == 200
        _body = _resp.json()
        assert _body["service_name"] == "AS_{1}"
        assert _body["kind"] == "alarm"

    @pytest.mark.asyncio
    async def test_mas_result(self) -> None:
        """*test_mas_result()* an MAS-shaped app attaches a `result` key drawn from the deterministic picker."""
        _app = build_atomic_fastapi_app(svc_name="MAS_{1}",
                                        kind="medical_analysis",
                                        mu=0.0)
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _http:
            _resp = await _http.post("/", json={"req_id": "r0",
                                                "kind": "medical_analysis",
                                                "operation": "analyseData"})
        _body = _resp.json()
        assert _body["result"] in {"changeDrug", "changeDose", "sendAlarm"}

    @pytest.mark.asyncio
    async def test_inject_5xx(self) -> None:
        """*test_inject_5xx()* `inject_failure="5xx"` returns 502 without touching the handler."""
        _app = build_atomic_fastapi_app(svc_name="AS_{1}",
                                        kind="alarm",
                                        mu=0.0)
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _http:
            _resp = await _http.post("/", json={"req_id": "r0",
                                                "inject_failure": "5xx"})
        assert _resp.status_code == 502

    @pytest.mark.asyncio
    async def test_csv_row(self,
                                          tmp_path: Path) -> None:
        """*test_csv_row()* a single POST writes one row to `<csv_dir>/<svc>__pid<PID>.csv` when `csv_dir` + `run_id` are supplied."""
        # Reset the module-level writer cache so this test starts clean across runs.
        third_party._CSV_WRITERS.clear()
        _app = build_atomic_fastapi_app(svc_name="AS_{1}",
                                        kind="alarm",
                                        mu=0.0,
                                        csv_dir=str(tmp_path),
                                        run_id="rid-test")
        _transport = make_test_transport(_app, "fastapi")
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _http:
            await _http.post("/", json={"req_id": "rA",
                                        "kind": "alarm",
                                        "operation": "triggerAlarm"})
        # Close any writer the test opened so the file flushes before reading.
        for _w in list(third_party._CSV_WRITERS.values()):
            _w.close()
        third_party._CSV_WRITERS.clear()
        _files = sorted(tmp_path.glob("*.csv"))
        assert len(_files) == 1
        _content = _files[0].read_text(encoding="utf-8")
        assert "rA" in _content
        assert "AS_{1}".replace("{", "").replace("}", "") in _files[0].name
        assert "rid-test" in _content

    def test_picker_buckets(self) -> None:
        """*test_picker_buckets()* hashing 1000 req_ids partitions into ~33 %/33 %/34 % across the three buckets."""
        _counts: Counter[str] = Counter()
        for _i in range(1000):
            _counts[_pick_analysis_result(f"req-{_i}")] += 1
        for _label in ("changeDrug", "changeDose", "sendAlarm"):
            # Allow a generous +/- window since hash distribution is not uniform on small samples.
            assert 200 < _counts[_label] < 450

    def test_safe_filename(self) -> None:
        """*test_safe_filename()* `{`, `}`, `,`, and space are removed so Windows file systems accept the path."""
        assert _safe_filename("MAS_{1, 2}", 99) == "MAS_12__pid99.csv"
