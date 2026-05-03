# -*- coding: utf-8 -*-
"""CS-01 TAS architectural experiment.

Tech-agnostic FastAPI replication of the TAS topology. Purpose: validate DASA's analytic / dimensional predictions transfer across technology stacks. See `notes/experiment.md` for the full design doc.

Submodules are imported directly from their module path: `from src.experiment.scanner import scan_one, scan_sweep`, `from src.experiment.client import ClientCfg`, etc. The package does not re-export anything so loading a sibling does not pull in `scanner` (which would create a circular load with `src.methods.experiment`).

Two top-level context managers compose the prototype: `from src.experiment.architecture import TasArchitecture` (server-side mesh) and `from src.experiment.users import TasUser` (client-side ramp); the user nests inside the architecture.
"""
