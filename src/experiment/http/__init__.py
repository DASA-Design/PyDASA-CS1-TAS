"""HTTP adapters over the generic queueing primitives in `core/`.

Thin glue: each helper attaches a FastAPI route to an existing app and
dispatches inbound requests through an `AtomicQueue` or `CompositeQueue`
via `run_instrumented`. No queueing logic lives here.
"""

from src.experiment.http.base_app import make_base_app
from src.experiment.http.forward import HttpForward
from src.experiment.http.mount import mount_atomic, mount_composite

__all__ = [
    "make_base_app",
    "HttpForward",
    "mount_atomic",
    "mount_composite",
]
