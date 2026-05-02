# -*- coding: utf-8 -*-
"""
Module test_config.py
=====================

Pin the dataclass defaults of `CascadeCfg` / `RampCfg` / `ClientCfg`. The JSON loader is tested under `tests/io/test_client_loader.py`.

    - **TestClientCfgDefaults** field defaults.
"""
# modules under test
from src.experiment.client.config import CascadeCfg, ClientCfg, RampCfg


class TestClientCfgDefaults:
    """**TestClientCfgDefaults** field defaults for the three typed specs."""

    def test_cascade(self) -> None:
        """*test_cascade()* `mode='rolling'`, `threshold=0.10`, `window=50`."""
        _c = CascadeCfg()
        assert _c.mode == "rolling"
        assert _c.threshold == 0.10
        assert _c.window == 50

    def test_ramp(self) -> None:
        """*test_ramp()* `min_n_per_kind=32`, `max_probe_s=60.0`, `rates=[1, 2, 5, 10, 20, 50, 100, 200, 500]`, `isinstance(cascade, CascadeCfg)`."""
        _r = RampCfg()
        assert _r.min_n_per_kind == 32
        assert _r.max_probe_s == 60.0
        assert _r.rates == [1.0, 2.0, 5.0, 10.0, 20.0, 50.0,
                            100.0, 200.0, 500.0]
        assert isinstance(_r.cascade, CascadeCfg)

    def test_client(self) -> None:
        """*test_client()* `entry_service='TAS_{1}'`, `seed=42`, `req_size_b=256`, both maps empty, `isinstance(ramp, RampCfg)`."""
        _c = ClientCfg()
        assert _c.entry_service == "TAS_{1}"
        assert _c.seed == 42
        assert _c.req_size_b == 256
        assert _c.req_sizes_by_kind == {}
        assert _c.kind_prob == {}
        assert isinstance(_c.ramp, RampCfg)
