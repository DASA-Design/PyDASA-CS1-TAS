"""Sweep-stage orchestrator (reserved placeholder).

The `sweep` slot drives a method across a grid of operating points: the
dimensional `(mu_factor, c, K)` sweep and the experimental 16-cell
`adaptation x framework x granularity` grid.

Today both sweeps live in notebooks (`04-yoly.ipynb` for the dimensional
method, the 16-grid loop in `05-experimental.ipynb` for the experimental
method); the apparatus-characterisation benchmark grid lives in
`src.experimental.procedure.bench`. This module is the reserved home for a
future programmatic sweep orchestrator that lifts that loop out of the
notebook, mirroring how `experiment.py` lifted the single-trial driver out
of `src.methods.experimental`.

Intentionally code-free until that work lands; see
`src.experimental.procedure.__init__` for the slot's role in the control
plane.
"""

from __future__ import annotations
