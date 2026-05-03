# -*- coding: utf-8 -*-
"""
Module test_client_loader.py
============================

Pin the `load_ramp_cfg` / `load_client_cfg` loaders in `src.io.tooling`: validation rejects bad inputs, valid inputs build the typed `RampCfg` / `ClientCfg` faithfully.

    - **TestLoadRampCfg** validation gates + happy-path build.
    - **TestLoadClientCfg** full client spec assembly with arch-injected `kind_prob`.
"""
# native python modules
from typing import Any, Dict

# test stack
import pytest

# target under test
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg
from src.io import load_client_cfg, load_ramp_cfg


def _good_ramp() -> Dict[str, Any]:
    """*_good_ramp()* canonical valid `ramp` block."""
    return {
        "min_samples_per_kind": 32,
        "max_probe_window_s": 30.0,
        "rates": [1.0, 2.0, 5.0],
        "cascade": {"mode": "rolling", "threshold": 0.10, "window": 50},
    }


class TestLoadRampCfg:
    """**TestLoadRampCfg** validation + materialisation of the `ramp` sub-dict."""

    def test_happy_path(self) -> None:
        """*test_happy_path()* `load_ramp_cfg(good_ramp)` returns `RampCfg(rates=[1.0, 2.0, 5.0], cascade=CascadeCfg(window=50))`."""
        _r = load_ramp_cfg(_good_ramp())
        assert isinstance(_r, RampCfg)
        assert _r.rates == [1.0, 2.0, 5.0]
        assert _r.min_n_per_kind == 32
        assert isinstance(_r.cascade, CascadeCfg)
        assert _r.cascade.window == 50

    @pytest.mark.parametrize(
        "_mutation,_msg_substr",
        [
            ({"min_samples_per_kind": 8}, "CLT validity"),
            ({"rho_grid": [0.1, 0.5, 0.9]}, "exactly one of 'rates' / 'rho_grid' / 'anchor'"),
            ({"rates": []}, "must specify 'rates'"),
            ({"rates": [5.0, 1.0, 2.0]}, "monotonically increasing"),
            ({"rates": [-1.0, 2.0]}, "positive floats"),
            ({"cascade": {"mode": "weird"}}, "cascade.mode"),
            ({"cascade": {"mode": "rolling", "window": 5}}, "window"),
            ({"cascade": {"mode": "rolling", "threshold": 1.5}}, "threshold"),
        ],
    )
    def test_invalid_inputs_raise(self, _mutation: Dict[str, Any], _msg_substr: str) -> None:
        """*test_invalid_inputs_raise()* every bad-shape variant raises `ValueError`; the message names the offending field."""
        _ramp = _good_ramp()
        for _k, _v in _mutation.items():
            _ramp[_k] = _v
        with pytest.raises(ValueError, match=_msg_substr):
            load_ramp_cfg(_ramp)

    def test_rho_grid_accepted(self) -> None:
        """*test_rho_grid_accepted()* `rho_grid` (instead of `rates`) passes validation; `rates` stays empty."""
        _ramp = _good_ramp()
        _ramp.pop("rates")
        _ramp["rho_grid"] = [0.2, 0.5, 0.8]
        _r = load_ramp_cfg(_ramp)
        assert _r.rates == []

    def test_anchor_accepted(self) -> None:
        """*test_anchor_accepted()* `anchor: "lambda_z"` (instead of `rates`) passes validation; `rates` stays empty (the executor materialises it via `_resolve_rates`)."""
        _ramp = _good_ramp()
        _ramp.pop("rates")
        _ramp["anchor"] = "lambda_z"
        _ramp["entry_artifact"] = "TAS_{1}"
        _r = load_ramp_cfg(_ramp)
        assert _r.rates == []


class TestLoadClientCfg:
    """**TestLoadClientCfg** full `ClientCfg` assembly from a method-config dict."""

    def test_happy_path(self) -> None:
        """*test_happy_path()* `load_client_cfg(method_cfg, kind_prob={...})` returns `ClientCfg` with `seed`, request sizes, kind probabilities, and a populated `RampCfg`."""
        _method_cfg: Dict[str, Any] = {
            "seed": 7,
            "request_size_bytes": {"analyse_request": 512, "TAS_{2}": 1024},
            "ramp": _good_ramp(),
        }
        _kp = {"TAS_{2}": 0.5, "TAS_{3}": 0.5}
        _c = load_client_cfg(_method_cfg, kind_prob=_kp)
        assert isinstance(_c, ClientCfg)
        assert _c.seed == 7
        assert _c.entry_service == "TAS_{1}"
        assert _c.req_size_b == 512
        assert _c.req_sizes_by_kind == {"analyse_request": 512, "TAS_{2}": 1024}
        assert _c.kind_prob == _kp
        assert _c.ramp.rates == [1.0, 2.0, 5.0]

    def test_missing_seed_raises(self) -> None:
        """*test_missing_seed_raises()* a method_cfg without `seed` raises `KeyError`."""
        with pytest.raises(KeyError):
            load_client_cfg({"ramp": _good_ramp()}, kind_prob={"k": 1.0})
