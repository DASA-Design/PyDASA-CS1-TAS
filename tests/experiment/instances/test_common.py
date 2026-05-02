# -*- coding: utf-8 -*-
"""
Module test_common.py
=====================

Pin the `HealthzPayload` shared building block used by both `build_tas` and `build_third_party`. The class wraps a `(role, ctxs)` pair and renders a uniform `/healthz` JSON body for both single-service and multi-service apps.

    - **TestHealthzPayload** rendered body shape across empty / single / multi-entry maps; the captured `ctxs` map is held by reference so late inserts surface on the next call.
"""
# native python modules
from typing import Dict

# testing framework
import pytest

# modules under test
from src.experiment.instances.common import HealthzPayload
from src.experiment.services import SvcCtx

# helper modules
from tests.utils.helpers import _SpecBuilder


# ------------------------------------------------------------- fixtures


@pytest.fixture
def specs() -> _SpecBuilder:
    """*specs()* yield a callable that builds a `SvcSpec`; override defaults via kwargs at the call site."""
    return _SpecBuilder()


# --------------------------------------------------------------- classes


class TestHealthzPayload:
    """**TestHealthzPayload** the rendered body matches `{"role": <role>, "components": [{"name", "c", "K"}, ...]}` across empty / single / multi-entry maps, and reflects late inserts since the `ctxs` map is held by reference."""

    def test_empty_ctxs(self) -> None:
        """*test_empty_ctxs()* `HealthzPayload("tas", {})()` returns `{"role": "tas", "components": []}`."""
        _body = HealthzPayload("tas", {})()
        assert _body == {"role": "tas", "components": []}

    def test_single_ctx(self, specs: _SpecBuilder) -> None:
        """*test_single_ctx()* `HealthzPayload("third_party", {"MAS_{1}": SvcCtx(spec)})()` returns `{"role": "third_party", "components": [{"name": "MAS_{1}", "c": 2, "K": 20}]}`."""
        _spec = specs(name="MAS_{1}", c=2, K=20)
        _ctxs: Dict[str, SvcCtx] = {_spec.name: SvcCtx(spec=_spec)}
        _body = HealthzPayload("third_party", _ctxs)()
        assert _body == {"role": "third_party",
                         "components": [{"name": "MAS_{1}",
                                         "c": 2,
                                         "K": 20}]}

    def test_multi_ctx_order(self, specs: _SpecBuilder) -> None:
        """*test_multi_ctx_order()* with insertion order TAS_{1}, TAS_{2}, TAS_{3}, the rendered `components` names equal `["TAS_{1}", "TAS_{2}", "TAS_{3}"]` and `body["components"][1] == {"name": "TAS_{2}", "c": 4, "K": 40}`."""
        _s1 = specs(name="TAS_{1}", c=1, K=10)
        _s2 = specs(name="TAS_{2}", c=4, K=40)
        _s3 = specs(name="TAS_{3}", c=8, K=80)
        _ctxs: Dict[str, SvcCtx] = {
            _s1.name: SvcCtx(spec=_s1),
            _s2.name: SvcCtx(spec=_s2),
            _s3.name: SvcCtx(spec=_s3),
        }
        _body = HealthzPayload("tas", _ctxs)()
        assert _body["role"] == "tas"
        _names = [_c["name"] for _c in _body["components"]]
        assert _names == ["TAS_{1}", "TAS_{2}", "TAS_{3}"]
        assert _body["components"][1] == {"name": "TAS_{2}", "c": 4, "K": 40}

    def test_late_insert(self, specs: _SpecBuilder) -> None:
        """*test_late_insert()* a single `HealthzPayload` instance returns `len(body["components"]) == 1` after the first insert and `== 2` after the second; insertion order is preserved on the second call."""
        _ctxs: Dict[str, SvcCtx] = {}
        _payload = HealthzPayload("tas", _ctxs)

        _s1 = specs(name="TAS_{1}", c=1, K=10)
        _ctxs[_s1.name] = SvcCtx(spec=_s1)
        _body_first = _payload()
        assert len(_body_first["components"]) == 1

        _s2 = specs(name="TAS_{2}", c=4, K=40)
        _ctxs[_s2.name] = SvcCtx(spec=_s2)
        _body_second = _payload()
        assert len(_body_second["components"]) == 2
        _names = [_c["name"] for _c in _body_second["components"]]
        assert _names == ["TAS_{1}", "TAS_{2}"]
