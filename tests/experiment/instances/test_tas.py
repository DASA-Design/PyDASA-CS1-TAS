# -*- coding: utf-8 -*-
"""
Module test_tas.py
==================

Pin the `build_tas` contract: one FastAPI app hosting six TAS members (TAS_{1..6}) with their own `SvcCtx`. TAS-to-TAS hops stay in-process; non-TAS targets use `ext_fwd`.

    - **TestTasInstance** per-member `SvcCtx` isolation, internal kind+Jackson routing, external forwarding, per-member CSV flush.
"""
# native python modules
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

# testing framework
import pytest

# web stack
import httpx
from fastapi import FastAPI

# modules under test
from src.experiment.instances import build_tas
from src.experiment.architecture import TasArchitecture
from src.experiment.services import LOG_COLUMNS, SvcReq, SvcSpec
from src.io import load_method_cfg, load_profile

# helper modules
from tests.utils.helpers import (_RecordedForward,
                                 _SpecBuilder,
                                 _no_forward,
                                 _seed_one_row_per_tas_member)


# ------------------------------------------------------------- fixtures


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`."""
    return _SpecBuilder()


@pytest.fixture
def _app_internal_only(specs: _SpecBuilder) -> Tuple[FastAPI, Dict[str, SvcSpec]]:
    """*_app_internal_only()* 3-member TAS where TAS_{1} kind-routes to TAS_{2} and TAS_{2} Jackson-routes to TAS_{3}."""
    _specs: Dict[str, SvcSpec] = {
        "TAS_{1}": specs(name="TAS_{1}",
                         role="composite",
                         port=8001,
                         seed=1),
        "TAS_{2}": specs(name="TAS_{2}",
                         role="composite",
                         port=8001,
                         seed=2),
        "TAS_{3}": specs(name="TAS_{3}",
                         role="composite",
                         port=8001,
                         seed=3),
    }
    _rows: Dict[str, List[Tuple[str, float]]] = {
        "TAS_{1}": [],
        "TAS_{2}": [("TAS_{3}", 1.0)],
        "TAS_{3}": [],
    }
    _k2t: Dict[str, str] = {"TAS_{2}": "TAS_{2}"}
    return build_tas(_specs, _rows, _k2t, _no_forward), _specs


@pytest.fixture
def _app_with_external(specs: _SpecBuilder) -> Tuple[FastAPI,
                                                     Dict[str, SvcSpec],
                                                     List[Tuple[str, str]]]:
    """*_app_with_external()* 2-member TAS where TAS_{2} forwards to MAS_{1} via `_RecordedForward(calls)`."""
    _specs: Dict[str, SvcSpec] = {
        "TAS_{1}": specs(name="TAS_{1}",
                         role="composite",
                         port=8001,
                         seed=1),
        "TAS_{2}": specs(name="TAS_{2}",
                         role="composite",
                         port=8001,
                         seed=2),
    }
    _rows: Dict[str, List[Tuple[str, float]]] = {
        "TAS_{1}": [],
        "TAS_{2}": [("MAS_{1}", 1.0)],
    }
    _k2t: Dict[str, str] = {"TAS_{2}": "TAS_{2}"}
    _calls: List[Tuple[str, str]] = []
    _fwd = _RecordedForward(_calls)
    return build_tas(_specs, _rows, _k2t, _fwd), _specs, _calls


# --------------------------------------------------------------- classes


class TestTasInstance:
    """**TestTasInstance** isolation, routing, forwarding, and per-member flush."""

    def test_distinct_ctxs(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_distinct_ctxs()* `set(app.state.tas_components.keys()) == set(specs.keys())` and `len({id(s) for s in tas_components.values()}) == len(specs)`."""
        _app, _specs = _app_internal_only
        _states = _app.state.tas_components
        assert set(_states.keys()) == set(_specs.keys())
        _ids = {id(_s) for _s in _states.values()}
        assert len(_ids) == len(_specs)

    def test_distinct_rngs(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_distinct_rngs()* TAS_{1} and TAS_{2} draw different `draw_svc_time()` sequences (different seeds)."""
        _app, _ = _app_internal_only
        _s1 = _app.state.tas_components["TAS_{1}"]
        _s2 = _app.state.tas_components["TAS_{2}"]
        _draws_1 = [_s1.draw_svc_time() for _ in range(10)]
        _draws_2 = [_s2.draw_svc_time() for _ in range(10)]
        assert _draws_1 != _draws_2

    @pytest.mark.asyncio
    async def test_three_hop_chain(self, _app_internal_only: Tuple[FastAPI, Dict[str, SvcSpec]]) -> None:
        """*test_three_hop_chain()* one POST at `/TAS_1/invoke` with `kind="TAS_{2}"` produces `len(ctx[name].log) == 1` for TAS_{1..3} and every row's keys are a superset of `LOG_COLUMNS`."""
        _app, _ = _app_internal_only
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _client:
            _req = SvcReq(kind="TAS_{2}", size_bytes=64)
            _r = await _client.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
            assert _r.json()["success"] is True
        _states = _app.state.tas_components
        for _name in ("TAS_{1}", "TAS_{2}", "TAS_{3}"):
            _log = _states[_name].log
            assert len(_log) == 1, f"{_name} log has {len(_log)} rows"
            assert _log[0]["req_id"] == _req.req_id
            assert set(LOG_COLUMNS).issubset(set(_log[0].keys()))

    @pytest.mark.asyncio
    async def test_forwards_to_external(self, _app_with_external: Tuple[FastAPI, Dict[str, SvcSpec], List[Tuple[str, str]]]) -> None:
        """*test_forwards_to_external()* one POST routing TAS_{1} -> TAS_{2} -> MAS_{1} produces `len(calls) == 1` and `calls[0][0] == "MAS_{1}"`."""
        _app, _, _calls = _app_with_external
        _transport = httpx.ASGITransport(app=_app)
        async with httpx.AsyncClient(transport=_transport,
                                     base_url="http://test") as _client:
            _req = SvcReq(kind="TAS_{2}", size_bytes=64)
            _r = await _client.post("/TAS_1/invoke", json=_req.model_dump())
            assert _r.status_code == 200
        assert len(_calls) == 1
        assert _calls[0][0] == "MAS_{1}"

    @pytest.mark.asyncio
    async def test_per_member_flush(self) -> None:
        """*test_per_member_flush()* after seeding one log row per TAS member, `arch.flush_logs(out_dir)` writes `out_dir/TAS__{i}_.csv` and `counts[f"TAS_{{{i}}}"] >= 1` for i in 1..6."""
        _cfg = load_profile(adaptation="baseline")
        _mcfg = load_method_cfg("experiment")
        async with TasArchitecture(cfg=_cfg, method_cfg=_mcfg,
                                   adaptation="baseline") as _arch:
            _seed_one_row_per_tas_member(_arch)
            with tempfile.TemporaryDirectory() as _td:
                _out = Path(_td)
                _counts = _arch.flush_logs(_out)
                for _i in range(1, 7):
                    _path = _out / f"TAS__{_i}_.csv"
                    assert _path.exists(), f"missing {_path}"
                for _i in range(1, 7):
                    _key = f"TAS_{{{_i}}}"
                    assert _counts.get(_key, 0) >= 1, f"no rows flushed for {_key}"
