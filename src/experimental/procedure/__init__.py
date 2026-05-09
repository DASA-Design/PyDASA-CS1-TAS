"""Experiment control plane: deployment + adaptation + sweep.

- `deployment`: bring up the apparatus under `localhost` / `multiprocess` / `remote`.
- `adaptation`: dispatch over the four adaptation strategies.
- `sweep`: fan out runs across the artifact axis for the yoly chart.
"""

from src.experimental.procedure.deployment import (
    AdapterFactory,
    AppFactory,
    Dpl,
    Framework,
    WsgiServer,
    bring_up,
)

__all__ = [
    "AdapterFactory",
    "AppFactory",
    "Dpl",
    "Framework",
    "WsgiServer",
    "bring_up",
]
