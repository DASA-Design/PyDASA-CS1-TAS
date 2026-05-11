"""Thin MAPE-K controller for the target system.

Holds the Monitor and Execute phases of the autonomic loop. Monitor pulls samples from TAS_1 and maintains rolling-window estimates of R1 and R2. Execute applies a one-shot configuration change to TAS_1 at trial start (picker, retry knobs).

Submodules:

- `strategies.py`: picker policies for `baseline`, `s1`, `s2`, `aggregate` plus `make_picker(adp, ...)` and `extract_op_weights(...)` for the routing weight table.
- `verdict.py`: post-trial operational-analysis verdict over the flow JSONL.
- `app.py`: FastAPI app for the controller process (`/aggregates`, `/history`, `/healthz`).
- `poller.py`: `SamplePoller` asyncio task that pulls `/samples` from TAS_1.
- `process.py`: `bring_up_controller` context manager that spawns the controller and fires the one-shot `/config` to TAS_1.
"""

from src.experimental.prototype.controller.app import (
    build_controller_app,
    ingest_samples,
)
from src.experimental.prototype.controller.poller import SamplePoller
from src.experimental.prototype.controller.process import bring_up_controller
from src.experimental.prototype.controller.strategies import (
    FirstOfKindPicker,
    PreferReliablePicker,
    RetryAndPreferReliablePicker,
    RetryOnFailurePicker,
    StrategyPicker,
    extract_op_weights,
    make_picker,
    picker_from_wire,
    picker_name_for,
)
from src.experimental.prototype.controller.verdict import (
    compute_verdict,
    write_verdict_json,
    write_window_parquet,
)

__all__ = [
    "FirstOfKindPicker",
    "PreferReliablePicker",
    "RetryAndPreferReliablePicker",
    "RetryOnFailurePicker",
    "SamplePoller",
    "StrategyPicker",
    "bring_up_controller",
    "build_controller_app",
    "compute_verdict",
    "extract_op_weights",
    "ingest_samples",
    "make_picker",
    "picker_from_wire",
    "picker_name_for",
    "write_verdict_json",
    "write_window_parquet",
]
