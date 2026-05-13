"""Experiment control plane: deployment + tuning + experiment.

- `deployment`: bring up the apparatus under `localhost` / `multiprocess` / `remote`.
- `tuning`: `run_calibration` orchestrator + envelope discovery.
- `experiment`: `run_experiment` orchestrator + mesh-spec builders + open-loop trial driver.

The `adaptation` slot is filled by `src.experimental.prototype.controller.strategies` (per-adp pickers + verdict computation); the `sweep` slot is filled by the `04-yoly.ipynb` notebook for the dimensional method and by the 16-grid loop in `05-experimental.ipynb` for the experimental method.
"""

from src.experimental.procedure.deployment import (
    AdapterFactory,
    AppFactory,
    Dpl,
    Framework,
    WsgiServer,
    bring_up,
)
from src.experimental.procedure.experiment import run_experiment
from src.experimental.procedure.tuning import (
    find_latest_envelope,
    run_calibration,
)

__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "WsgiServer",
    "bring_up",
    "find_latest_envelope",
    "run_calibration",
    "run_experiment",
]
