# python native modules
import re
from dataclasses import dataclass, field
from typing import Generic, List
# Optional, Callable,

# custom modules
from src.utils import FUND_DIM_UNIT_RE
from src.utils import DIGIT_POW_RE
from src.utils import BASIC_DIGIT_POW_RE
from src.utils import T
from src.utils import FDU
from src.utils import EXP_PATTERN_STR
from src.utils import FDU_PATTERN_STR


@dataclass
class Parameter(Generic[T]):
    """ _summary_

    Raises:
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    # TODO add docstring
    # name of the parameter
    name: str = ""
    # latex symbol for the parameter
    symbol: str = ""
    # parameter dimensions input by user
    dimensions: str = ""
    # optional string description of the parameter
    description: str = ""
    # flag for whether the parameter is inside the main dimensional matrix
    relevant: bool = False
    # flag for whether the parameter is the output of the phenomenon
    output: bool = False
    # parameter private index in the dimensional matrix
    _idx: int = -1
    # parameter dimensions as a latex expression
    _expr_dims: str = ""
    # parameter dimensions as a sympy expression
    _sym_dims: str = ""
    # list with the dimensions exponent coefficients as integers
    _exp_dim_lt: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        """__post_init__ _summary_

        Raises:
            ValueError: _description_
        """
        # TODO add docstring
        # check for valid dimensions
        if self.dimensions != "":
            if not self.validate(self.dimensions, FUND_DIM_UNIT_RE):
                err_msg = f"parameter {self.name} has invalid dimensions!!!"
                err_msg += f"\n\tcheck FDU in: {self.dimensions}"
                raise ValueError(err_msg)

            # prepare the parameter for dimensional analysis
            # set up dimensions in uppercase
            self._expr_dims = self._setup_exp_dims(self.dimensions)
            # sort dimensions in the dimensional precedence order
            self._expr_dims = self._sort_exp_dims(self._expr_dims)
            # set up expression for sympy
            self._sym_dims = self._setup_sym_dims(self._expr_dims)
            # setup dimension pow list for dimensional analysis
            self._exp_dim_lt = self._setup_pow_dim_lt(self._sym_dims)

        # if description is not empty, capitalize it
        if self.description != "":
            self.description = self.description.capitalize()

    def validate(self, dims: str, pattern: str) -> bool:
        """ validate Validates the dimensions against a regex pattern.

        Args:
            dims (str): Dimensional representation to validate.
            pattern (str): Regex pattern to validate against.

        Returns:
            bool: True if the dimensions match the pattern, False otherwise.
        """
        valid = bool(re.match(pattern, dims))
        return valid

    def _setup_exp_dims(self, dims: str) -> str:
        """ _setup_exp_dims Formats the dimensions by adding parentheses to exponents and defaulting missing exponents to 1.

        Args:
            dims (str): Dimensional representation to format.

        Returns:
            str: Formatted dimensional representation.
        """
        # add parentheses to powers in dimensions
        exp_pattern = re.compile(DIGIT_POW_RE)
        _expr_dims = exp_pattern.sub(lambda m: f"({m.group(0)})", dims)

        # add ^1 to * and / operations in dimensions
        exp_pattern = re.compile(BASIC_DIGIT_POW_RE)
        _expr_dims = exp_pattern.sub(lambda m: f"{m.group(0)}^(1)", _expr_dims)
        return _expr_dims

    def _sort_exp_dims(self, dims: str) -> str:
        """ _sort_exp_dims Sorts the dimensions in the order of the Fundamental Dimensional Units (FDUs).

        Args:
            dims (str): Dimensional representation to sort.

        Returns:
            str: Sorted dimensional representation.
        """
        dims_lt = dims.split("*")
        dims_lt.sort(key=lambda dim: FDU.index(dim[0]))
        _expr_dims = "*".join(dims_lt)
        return _expr_dims

    def _setup_sym_dims(self, expr_dims: str) -> str:
        """ _setup_sym_dims Converts the dimensions into a SymPy-compatible expression.

        Args:
            expr_dims (str): Formatted dimensional representation.

        Returns:
            str: SymPy-compatible dimensional representation.
        """
        _sym_dims = expr_dims.replace("*", "* ")
        _sym_dims = _sym_dims.replace("^", "**")
        return _sym_dims

    def _setup_pow_dim_lt(self, sym_dims: str) -> List[int]:
        """ _setup_pow_dim_lt Computes the list of dimension exponent coefficients for the dimensional matrix.

        Args:
            sym_dims (str): SymPy-compatible dimensional representation.

        Returns:
            List[int]: List of exponent coefficients for each FDU.
        """
        # split the sympy expression into a list of dimensions
        dims_lt = sym_dims.split("* ")
        # get the length of the list
        dims_lt_len = len(dims_lt)
        # create default list of zeros with the FDU length
        dim_pow_lt = len(FDU) * [0]
        # working vars
        i = 0
        digit_pattern = re.compile(EXP_PATTERN_STR)

        # iterate over the dimensions list of the expression
        while i < dims_lt_len:
            # get the dimension
            t_sym = dims_lt[i]
            # match the exponent of the dimension
            t_exp = digit_pattern.findall(t_sym)
            # update the exponent of the dimension with the t_exp value
            # find the fdu and its index
            t_dim = self._find_pattern(t_sym, FDU_PATTERN_STR)
            fdu_idx = FDU.index(t_dim[0])
            # update the exponent of the dimension
            dim_pow_lt[fdu_idx] = int(t_exp[0])
            i += 1
        # return the list of powers
        return dim_pow_lt

    def _find_pattern(self, sym: str, pattern: str) -> str:
        """ _find_pattern Finds a pattern in a given string.

        Args:
            sym (str): String to search in.
            pattern (str): Regex pattern to search for.

        Returns:
            str: Matched pattern or None if no match is found.
        """
        find = re.compile(pattern)
        matches = find.findall(sym)
        if matches:
            return matches
        else:
            return None
