"""Request schema + generated blob payload.

The blob generator takes an optional `seed`: pass an int for a reproducible byte sequence (the experiment's default), or `None` to let the component generate a fresh seed at instantiation (useful for ad-hoc dev runs).
"""

from src.experimental.common.payload.blob import make_blob
from src.experimental.common.payload.request import (
    KIND_ALARM,
    KIND_MED_ANSYS,
    FailureMechanism,
    Request,
)

__all__ = [
    "KIND_ALARM",
    "KIND_MED_ANSYS",
    "FailureMechanism",
    "Request",
    "make_blob",
]
