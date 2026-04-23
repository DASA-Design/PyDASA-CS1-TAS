# -*- coding: utf-8 -*-
"""CS-01 TAS architectural experiment.

Tech-agnostic FastAPI replication of the TAS topology. Purpose: validate DASA's analytic / dimensional predictions transfer across technology stacks. See `notes/experiment.md` for the full design doc.
"""

from src.experiment.networks import sweep_arch_exp

__all__ = [
    "sweep_arch_exp",
]
