"""Unittest fixture builders for the experimental method.

The on-disk JSON files under `data/config/method/prototype/` are the **experiment-time** configurations: they govern what `python -m src.methods.experimental` does on a real run. Tests must NOT rely on those files staying any particular shape over time -- if the experiment config changes, the unit tests should keep passing.

This package exposes `make_*_cfg(...)` builders that return dicts shaped like the on-disk files but with sensible test defaults baked in. Tests pass these dicts via the `cfg=` / `target_cfg=` overrides on `run_calibration()` / `run_experiment()` so no on-disk file is ever read.

Modules:

- `target.py`: `make_target_cfg(...)` builds a target.json-shaped dict.

Convention: keep the builders close to the dict shape on disk. If the JSON schema migrates, builders migrate alongside it (the migration is one place, not scattered across N test files).
"""

from tests.fixtures.target import make_target_cfg

__all__ = [
    "make_target_cfg",
]
