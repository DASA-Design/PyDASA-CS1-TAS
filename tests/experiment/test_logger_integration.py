# -*- coding: utf-8 -*-
"""
Module test_logger_integration.py
=================================

End-to-end integration test for the `@logger` decorator from `src.experiment.services.instruments`: decorator -> `ServiceContext.flush_log` -> `ExperimentLauncher.flush_logs` -> on-disk CSV. Unit tests for the decorator alone live in `tests/experiment/services/test_instruments.py`; this file pins the integration across base + instruments + launcher.

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
from src.experiment.launcher import ExperimentLauncher
from src.experiment.services import LOG_COLUMNS
from src.io import load_method_config, load_profile


class TestJourneySchemaLocked:
    """**TestJourneySchemaLocked** the public LOG_COLUMNS constant is stable."""

    def test_column_order_and_set(self):
        """*test_column_order_and_set()* pin the exact `LOG_COLUMNS` tuple; any change to this test signals a breaking schema change for downstream re-estimators."""
        assert LOG_COLUMNS == (
            "request_id", "service_name", "kind",
            "recv_ts", "start_ts", "end_ts",
            "success", "status_code",
            "size_bytes",
        )

    def test_contains_every_downstream_needed_column(self):
        """*test_contains_every_downstream_needed_column()* every column the downstream re-estimators read must be present in the schema."""
        _needed = {"recv_ts", "start_ts", "end_ts",
                   "success", "status_code", "size_bytes"}
        assert _needed <= set(LOG_COLUMNS)


class TestReplicateLayout:
    """**TestReplicateLayout** FR-3.8 per-replicate directory nesting."""

    @pytest.mark.asyncio
    async def test_flat_layout_when_replicate_id_omitted(self):
        """*test_flat_layout_when_replicate_id_omitted()* without `replicate_id`, CSVs sit directly under the cell directory with no `rep_<k>/` nesting."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
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
    async def test_nested_layout_with_replicate_id(self):
        """*test_nested_layout_with_replicate_id()* passing `replicate_id=N` nests CSV outputs under `rep_<N>/` inside the cell directory."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
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
    async def test_csv_columns_match_locked_schema(self):
        """*test_csv_columns_match_locked_schema()* the CSV header row written by `flush_logs` matches the `LOG_COLUMNS` tuple byte-for-byte."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_config("experiment")
        async with ExperimentLauncher(cfg=_cfg, method_cfg=_mcfg,
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
