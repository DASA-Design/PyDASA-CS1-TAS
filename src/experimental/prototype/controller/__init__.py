"""Thin MAPE-K controller for the target system.

Holds the Monitor and Execute phases of the autonomic loop. Monitor pulls samples from TAS_1 and maintains rolling-window estimates of R1 and R2. Execute applies a one-shot configuration change to TAS_1 at trial start (picker, retry knobs).

Submodules:

- `strategies.py`: picker policies for `baseline`, `s1`, `s2`, `aggregate` plus `make_picker(adp, ...)` and `extract_op_weights(...)` for the routing weight table.
- `verdict.py`: post-trial operational-analysis verdict over the flow JSONL.
"""

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
    "StrategyPicker",
    "compute_verdict",
    "extract_op_weights",
    "make_picker",
    "picker_from_wire",
    "picker_name_for",
    "write_verdict_json",
    "write_window_parquet",
]
