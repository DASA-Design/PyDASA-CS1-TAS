"""Target system: the managed subsystem from Weyns & Calinescu 2015 Fig. 2.

Subpackages:

- `service/`: the service-class hierarchy (`AbstractService`, `AtomicService`, `CompositeService`), the `ServiceClient` dispatch wrapper, the QoS dataclasses, and the catalogue loader.
- `workflow/`: `WorkflowSpec` loader + `WorkflowEngine` driver for composite TAS.
- `factory/`: FastAPI app factories for TAS, internal stages, and third-party atomics, plus the failure dispatcher and `/healthz` helper.
- `config.py`: loader for `data/config/method/prototype/target.json`.
"""

from src.experimental.prototype.target.config import (
    DFLT_TGT_CFG_DIR,
    DFLT_TGT_CFG_FILE,
    load_target_cfg,
)

__all__ = [
    "DFLT_TGT_CFG_DIR",
    "DFLT_TGT_CFG_FILE",
    "load_target_cfg",
]
