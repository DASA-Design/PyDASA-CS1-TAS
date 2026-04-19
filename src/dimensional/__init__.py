"""TAS dimensional-method adapters around PyDASA.

This subpackage is intentionally thin: PyDASA does the math, these modules
provide the case-study glue (config-driven FDU schema, per-artifact engine
construction, coefficient derivation from spec, sensitivity reshaping).
"""

from src.dimensional.coefficients import derive_coefficients
from src.dimensional.engine import build_engine
from src.dimensional.schema import build_schema
from src.dimensional.sensitivity import analyse_symbolic

__all__ = [
    "analyse_symbolic",
    "build_engine",
    "build_schema",
    "derive_coefficients",
]
