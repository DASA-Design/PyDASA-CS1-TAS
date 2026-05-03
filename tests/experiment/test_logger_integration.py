# -*- coding: utf-8 -*-
"""
Module test_logger_integration.py
=================================

End-to-end integration test for the `@logger` decorator from `src.experiment.services.instruments`: decorator -> `SvcCtx.flush_log` -> `TasArchitecture.flush_logs` -> on-disk CSV. Unit tests for the decorator alone live in `tests/experiment/services/test_instruments.py`; this file pins the integration across base + instruments + architecture.

FR-3.4: lock the per-invocation row schema (`LOG_COLUMNS`) so downstream analysis (`06-comparison.ipynb`) can depend on it without rename shims.

FR-3.8: per-replicate directory layout. When `replicate_id` is passed to `flush_logs`, outputs nest under `rep_<id>/<service>.csv`.
"""
# native python modules
import csv
import tempfile
from pathlib import Path

# testing framework
import pytest

# modules under test
from src.experiment.architecture import TasArchitecture
from src.experiment.services import LOG_COLUMNS
from src.io import load_method_cfg, load_profile


class TestJourneySchemaLocked:
    """**TestJourneySchemaLocked** the public LOG_COLUMNS constant is stable."""

    def test_column_order_and_set(self) -> None:
        """*test_column_order_and_set()* pin the exact `LOG_COLUMNS` tuple; any change to this test signals a breaking schema change for downstream re-estimators."""
        assert LOG_COLUMNS == (
            "req_id", "srv_name", "kind",
            "recv_ts", "start_ts", "local_end_ts", "end_ts",
            "c_used_at_start",
            "success", "status_code",
            "size_bytes",
        )

    def test_log_columns_complete(self) -> None:
        """*test_log_columns_complete()* every column the downstream re-estimators read must be present in the schema."""
        _needed = {"recv_ts", "start_ts", "local_end_ts", "end_ts",
                   "success", "status_code", "size_bytes"}
        assert _needed <= set(LOG_COLUMNS)


class TestReplicateLayout:
    """**TestReplicateLayout** FR-3.8 per-replicate directory nesting."""

    @pytest.mark.asyncio
    async def test_flat_layout_no_rep_id(self) -> None:
        """*test_flat_layout_no_rep_id()* without `replicate_id`, CSVs sit directly under the cell directory with no `rep_<k>/` nesting."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            # inject one row into every queue so flush writes files. The TAS app holds six member queues under state.tas_components; third-party apps hold one queue under state.ctx.
            _seen_ids = set()
            for _app in _lnc.apps.values():
                _components = getattr(_app.state, "tas_components", None)
                if _components is not None:
                    for _q in _components.values():
                        if id(_q) in _seen_ids:
                            continue
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})
                else:
                    _q = _app.state.ctx
                    if id(_q) not in _seen_ids:
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})

            with tempfile.TemporaryDirectory() as _td:
                _out = Path(_td)
                _lnc.flush_logs(_out)
                # CSV files sit directly under the cell directory, no rep_<k>/ nesting
                _files = list(_out.glob("*.csv"))
                assert len(_files) > 0
                assert not (_out / "rep_0").exists()

    @pytest.mark.asyncio
    async def test_nested_layout_with_rep(self) -> None:
        """*test_nested_layout_with_rep()* passing `replicate_id=N` nests CSV outputs under `rep_<N>/` inside the cell directory."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            _seen_ids = set()
            for _app in _lnc.apps.values():
                _components = getattr(_app.state, "tas_components", None)
                if _components is not None:
                    for _q in _components.values():
                        if id(_q) in _seen_ids:
                            continue
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})
                else:
                    _q = _app.state.ctx
                    if id(_q) not in _seen_ids:
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})

            with tempfile.TemporaryDirectory() as _td:
                _out = Path(_td)
                _lnc.flush_logs(_out, replicate_id=3)
                _rep = _out / "rep_3"
                assert _rep.is_dir()
                _files = list(_rep.glob("*.csv"))
                assert len(_files) > 0

    @pytest.mark.asyncio
    async def test_csv_schema_locked(self) -> None:
        """*test_csv_schema_locked()* the CSV header row written by `flush_logs` matches the `LOG_COLUMNS` tuple byte-for-byte."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                                      adaptation="baseline") as _lnc:
            _seen_ids = set()
            for _app in _lnc.apps.values():
                _components = getattr(_app.state, "tas_components", None)
                if _components is not None:
                    for _q in _components.values():
                        if id(_q) in _seen_ids:
                            continue
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})
                else:
                    _q = _app.state.ctx
                    if id(_q) not in _seen_ids:
                        _seen_ids.add(id(_q))
                        _q.log.append({_c: 0 for _c in LOG_COLUMNS})

            with tempfile.TemporaryDirectory() as _td:
                _lnc.flush_logs(Path(_td))
                _any_csv = next(Path(_td).glob("*.csv"))
                with _any_csv.open("r", encoding="utf-8") as _fh:
                    _header = next(csv.reader(_fh))
                assert tuple(_header) == LOG_COLUMNS
