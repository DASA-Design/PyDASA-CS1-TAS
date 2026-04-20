"""TAS dimensional-method adapters around PyDASA.

This subpackage is intentionally thin: PyDASA does the math, these modules
provide the case-study glue (config-driven FDU schema, per-artifact engine
construction, coefficient derivation from spec, sensitivity reshaping).
"""

from src.dimensional.coefficients import derive_coefficients
from src.dimensional.engine import build_engine
from src.dimensional.networks import (sweep_architecture,
                                      sweep_artifact,
                                      sweep_artifacts)
from src.dimensional.reshape import (aggregate_architecture_coefficients,
                                     aggregate_sweep_to_arch,
                                     coefficients_delta,
                                     coefficients_to_network,
                                     coefficients_to_nodes,
                                     network_delta)
from src.dimensional.schema import build_schema
from src.dimensional.sensitivity import analyse_symbolic

__all__ = [
    "aggregate_architecture_coefficients",
    "aggregate_sweep_to_arch",
    "analyse_symbolic",
    "build_engine",
    "build_schema",
    "coefficients_delta",
    "coefficients_to_network",
    "coefficients_to_nodes",
    "derive_coefficients",
    "network_delta",
    "sweep_architecture",
    "sweep_artifact",
    "sweep_artifacts",
]
