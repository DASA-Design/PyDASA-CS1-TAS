# python native modules
# import re
from dataclasses import dataclass, field
from typing import Generic, List, Optional
# , Callable,

# python third-party modules
# import sympy as sp
import numpy as np

# custom modules
# from src.utils import FUND_DIM_UNIT_RE
# from src.utils import DIGIT_POW_RE
# from src.utils import BASIC_DIGIT_POW_RE
from src.utils import T
# from src.utils import FDU
# from src.utils import EXP_PATTERN_STR
# from src.utils import FDU_PATTERN_STR


@dataclass
class PiCoefficient(Generic[T]):
    """*PiCoefficient* class for creating a *Dimensionless Coefficient* in *PyDASA*. PiCoefficients are used to define the dimensionless coefficients of a system.

    Args:
        Generic (T): Generic type for a Python data structure.

    Returns:
        PiCoefficient: A Dimensionless Coefficient (DC) object with the following attributes:
            - `name`: The name of the DC.
            - `symbol`: The symbol of the DC.
            - `description`: The description of the DC.
            - `pi_expr`: The expression for the dimensionless coefficient.
            - `_idx`: The index in the dimensional matrix.
            - `_pi_param_lt`: The list of parameters used in the dimensionless coefficient.
            - `_pi_exp_lt`: The list of exponents used in the dimensionless coefficient.
            - `_rref_dim_matrix`: The diagonal solved dimensional matrix.
            - `_pivot_lt`: The list of pivots in the dimensional matrix.
    """
    # name of the parameter
    name: str = ""
    # latex symbol for the parameter
    symbol: str = ""
    # optional string description of the parameter
    description: str = ""
    # expression for the dimensionless coefficient
    pi_expr: str = ""
    # private index in the dimensional matrix
    _idx: int = -1
    # list of parameters used in the dimensionless coefficient
    _pi_param_lt: List[str] = field(default_factory=list)
    # list of exponents used in the dimensionless coefficient
    _pi_exp_lt: List[int] = field(default_factory=list)
    # diagonal solved dimensional matrix
    _rref_dim_matrix: Optional[np.ndarray] = field(
        default_factory=lambda: np.array([]))
    _pivot_lt: Optional[List[int]] = field(default_factory=list)
