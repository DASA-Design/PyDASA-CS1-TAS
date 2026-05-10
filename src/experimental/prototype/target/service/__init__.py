"""Service-class hierarchy (Weyns & Calinescu 2015 Fig. 2).

- `AbstractService`: lifecycle + invocation contract.
- `AtomicService`: adds the K and c admission gate; concrete subclasses override `_handle`.
- `CompositeService`: orchestrates the workflow by dispatching through a `ServiceClient`.
- `ServiceClient`: invokes remote services over a `ServiceCache` (httpx-backed).
- QoS dataclasses: `QoSRequirement`, `PerformanceQoS`, `AvailabilityQoS`.
- `ServiceCatalogue` + `FailureModesCfg`: typed views over the JSON catalogue files.
"""

from src.experimental.prototype.target.service.abstract import AbstractService
from src.experimental.prototype.target.service.atomic import AtomicService
from src.experimental.prototype.target.service.catalogue import (
    DFLT_CATALOGUE_DIR,
    DFLT_CATALOGUE_FILE,
    DFLT_FAILURE_MODES_FILE,
    FailureModesCfg,
    ServiceCatalogue,
    ServiceCatalogueEntry,
    load_catalogue,
    load_failure_modes,
)
from src.experimental.prototype.target.service.client import (
    DFLT_TIMEOUT_S,
    ServiceClient,
)
from src.experimental.prototype.target.service.composite import CompositeService
from src.experimental.prototype.target.service.qos import (
    AvailabilityQoS,
    PerformanceQoS,
    QoSRequirement,
)

__all__ = [
    "AbstractService",
    "AtomicService",
    "AvailabilityQoS",
    "CompositeService",
    "DFLT_CATALOGUE_DIR",
    "DFLT_CATALOGUE_FILE",
    "DFLT_FAILURE_MODES_FILE",
    "DFLT_TIMEOUT_S",
    "FailureModesCfg",
    "PerformanceQoS",
    "QoSRequirement",
    "ServiceCatalogue",
    "ServiceCatalogueEntry",
    "ServiceClient",
    "load_catalogue",
    "load_failure_modes",
]
