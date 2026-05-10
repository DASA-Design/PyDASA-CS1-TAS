"""QoS requirement hierarchy attached to service descriptions.

Typed bag of QoS hints carried alongside each catalogue entry. Adaptation strategies read these to pick reliable or fast alternatives; verdict computation reads R1 and R2 from the profile, not from here.

Fig. 2 names a generic QoS slot; this module specialises it into `PerformanceQoS` (R2) and `AvailabilityQoS` (R1). `CostQoS` is intentionally omitted: cost (R3) is monetary, not a dimensional unit DASA reasons about.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class QoSRequirement(ABC):
    """Root of the QoS-requirement hierarchy. Subclasses carry one numeric bound."""


@dataclass(frozen=True)
class PerformanceQoS(QoSRequirement):
    """Response-time requirement in seconds.

    Attributes:
        response_time_s_max (float): upper bound on the per-invocation response time. Cámara 2023 R2 is `0.026` (26 ms).
    """

    response_time_s_max: float


@dataclass(frozen=True)
class AvailabilityQoS(QoSRequirement):
    """Failure-rate requirement as a fraction of failed invocations.

    Attributes:
        failure_rate_max (float): upper bound on the per-invocation failure rate. Cámara 2023 R1 is `3e-4` (0.03 %).
    """

    failure_rate_max: float


__all__ = [
    "AvailabilityQoS",
    "PerformanceQoS",
    "QoSRequirement",
]
