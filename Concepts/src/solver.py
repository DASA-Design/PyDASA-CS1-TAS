# -*- coding: utf-8 -*-
"""
Module for solving Dimensional Analysis problems in *PyDASA*.

This module provides the **DASolver** class, which is responsible for:
1. Managing dimensional parameters and their relationships.
2. Constructing and solving the dimensional matrix.
3. Generating dimensionless coefficients (e.g., Pi groups) using the Buckingham Pi theorem.
4. Providing tools for analyzing and manipulating dimensional data.

Classes:
    - DASolver: Main solver class for dimensional analysis.

Dependencies:
    - Python native modules: `re`, `copy`
    - Third-party modules: `sympy`, `numpy`
    - Custom modules: `Parameter`, `PiCoefficient`, `FDU`, `T`

*IMPORTANT:* Based on the theory from:

    # H.Gorter, *Dimensionalanalyse: Eine Theoririe der physikalischen Dimensionen mit Anwendungen*
"""

# python natie modules
# import re
# import sys
# import os
import re
import copy
from dataclasses import dataclass, field
# import modules for defining the element"s type in the array
from typing import List, Dict, Optional, Generic
# Callable

# python third-party modules
import sympy as sp
import numpy as np

# from sympy.matrices import Matrix
from sympy import Matrix
from sympy import matrix2numpy

# from sympy.parsing.sympy_parser import parse_expr
# from sympy.core.mul import Mul, Pow
# from sympy.core.expr import Expr
# from itertools import combinations, permutations

# import costum modules
from src.parameters import Parameter
from src.coefficients import PiCoefficient
from src.utils import T
from src.utils import FDU


@dataclass
class DASolver(Generic[T]):
    """
    **DASolver** is the main class for performing Dimensional Analysis in *PyDASA*.

    This class provides methods to:
    - Manage dimensional parameters and their relationships.
    - Construct and solve the dimensional matrix.
    - Generate dimensionless coefficients (e.g., Pi groups) using the Buckingham Pi theorem.
    - Analyze and manipulate dimensional data.

    Attributes:
        phenomena (str): Description of the physical phenomenon being analyzed.
        description (str): Additional details about the analysis.
        dimensional_lt (List[Parameter]): List of dimensional parameters.
        output (Optional[Parameter]): The output parameter of the analysis.
        pi_coefficients (List[PiCoefficient]): List of dimensionless Pi coefficients.
        _work_param_dt (Dict[str, Parameter]): Dictionary of working parameters.
        _n_param (int): Total number of parameters.
        _relv_param_dt (Dict[str, Parameter]): Dictionary of relevant parameters.
        _n_relv_param (int): Number of relevant parameters.
        _used_fdu_lt (List[str]): List of used Fundamental Dimensional Units (FDUs).
        _n_used_fdu (int): Number of used FDUs.
        _cur_dim_matrix (Optional[np.ndarray]): Current dimensional matrix.
        _trans_dim_matrix (Optional[np.ndarray]): Transposed dimensional matrix.
    """
    phenomena: str = ""
    description: str = ""
    dimensional_lt: List[Parameter] = field(default_factory=list)
    output: Optional[Parameter] = None
    pi_coefficients: List[PiCoefficient] = field(default_factory=list)
    _work_param_dt: Dict[str, Parameter] = field(default_factory=dict)
    _n_param: int = 0
    _relv_param_dt: Dict[str, Parameter] = field(default_factory=dict)
    _n_relv_param: int = 0
    _used_fdu_lt: List[str] = field(default_factory=list)
    _n_used_fdu: int = 0
    _cur_dim_matrix: Optional[np.ndarray] = field(
        default_factory=lambda: np.array([]))
    _trans_dim_matrix: Optional[np.ndarray] = field(
        default_factory=lambda: np.array([]))

    def __post_init__(self) -> None:
        """__post_init__ Initializes the DASolver by:
            - Checking and sorting used FDUs.
            - Sorting dimensional parameters by relevance.
            - Setting up the output parameter.
            - Creating dictionaries for working and relevant parameters.
        """
        # casting input dimensional list to list
        self.dimensional_lt = list(self.dimensional_lt)

        # checking FDU for the first time
        self._check_used_fdu()
        # size of used fundamental dimensional units
        self._n_used_fdu = len(self._used_fdu_lt)

        # size of dimensional list
        self._n_param = len(self.dimensional_lt)

        # sorting the dimensional list by the relevant parameters
        self._sort_dim_lt_by_relv_param()

        # creating the reference to the output parameter attribute
        self.output = self._setup_output()
        # fixing the output index
        self._fix_output_idx()

        # creating the working parameter dictionary
        self._work_param_dt = self._setup_work_dict()

        # creating the relevant parameter dictionary
        self._relv_param_dt = self._setup_relv_dict()
        self._n_relv_param = len(self._relv_param_dt)

    def __str__(self) -> str:
        """__str__ Returns a string representation of the DASolver instance.

        Returns:
            str: String representation of the DASolver.
        """
        class_str = f"{self.__class__.__name__}(\n"
        for attr, value in vars(self).items():
            if isinstance(value, str):
                class_str += f"\t{attr}='{value}',\n"
            else:
                class_str += f"\t{attr}={value},\n"
        class_str += ")"
        return class_str

    def _check_used_fdu(self) -> None:
        """_check_used_fdu Identifies and stores the list of used Fundamental Dimensional Units (FDUs) from the dimensional parameters.
        """
        for param in self.dimensional_lt:
            matches = re.findall(r"[A-Z]", param.dimensions)
            # print(matches)
            for match in matches:
                if match not in self._used_fdu_lt:
                    self._used_fdu_lt.append(match)
        # sorting according to FDU precedence
        self._sort_used_fdu()

    def _sort_used_fdu(self) -> None:
        """_sort_used_fdu Sorts the list of used FDUs based on their precedence.
        """
        self._used_fdu_lt.sort(key=lambda x: FDU.index(x))

    def _sort_dim_lt_by_relv_param(self):
        """_sort_dim_lt_by_relv_param Sorts the dimensional parameters by relevance and updates their indices.
        """
        # sort the dimensional list by the relevant parameters
        self.dimensional_lt.sort(key=lambda x: x.relevant, reverse=True)
        i = 0
        # fill the index of the parameters
        for param in self.dimensional_lt:
            param._idx = i
            i += 1

    def _fix_output_idx(self):
        """_fix_output_idx Ensures the output parameter is placed at the correct index in the dimensional list.
        """
        tgt_idx = self._n_used_fdu
        src_idx = self.output._idx
        self.dimensional_lt[src_idx]._idx = tgt_idx
        self.dimensional_lt[tgt_idx]._idx = src_idx
        self.dimensional_lt = self._exchange_param(self.dimensional_lt,
                                                   src_idx,
                                                   tgt_idx)

    def _exchange_param(self,
                        lst: List[Parameter],
                        pos1: int,
                        pos2: int) -> List[Parameter]:
        """ _exchange_param Swaps two parameters in the dimensional list.

        Args:
            lst (List[Parameter]): List of parameters.
            pos1 (int): Index of the first parameter.
            pos2 (int): Index of the second parameter.

        Returns:
            List[Parameter]: Updated list with swapped parameters.
        """
        lst[pos1], lst[pos2] = lst[pos2], lst[pos1]
        return lst

    def _setup_work_dict(self) -> Dict[str, Parameter]:
        """_setup_work_dict Creates a dictionary of working parameters.

        Returns:
            Dict[str, Parameter]: Dictionary of working parameters.
        """
        _work_dt = dict()
        for param in self.dimensional_lt:
            param = copy.copy(param)
            td = {param.symbol: param}
            _work_dt.update(td)
        return _work_dt

    def _setup_relv_dict(self) -> Dict[str, Parameter]:
        """_setup_relv_dict Creates a dictionary of relevant parameters.

        Returns:
            Dict[str, Parameter]: Dictionary of relevant parameters.
        """
        _relv_dt = dict()
        for param in self.dimensional_lt:
            if param.relevant:
                param = copy.copy(param)
                td = {param.symbol: param}
                _relv_dt.update(td)
        return _relv_dt

    def _setup_output(self) -> Optional[Parameter]:
        """_setup_output Identifies and sets the output parameter.

        Returns:
            Optional[Parameter]: The output parameter.
        """
        output = None
        if self.output is None:
            i = 0
            found = False
            while i < self._n_param and not found:
                if self.dimensional_lt[i].output:
                    output = copy.copy(self.dimensional_lt[i])
                    found = True
                i += 1
        return output

    def _start_dim_matrix(self) -> np.ndarray:
        """_start_dim_matrix Initializes an empty dimensional matrix.

        Returns:
            np.ndarray: Zero-filled dimensional matrix.
        """
        dim_matrix = np.zeros((self._n_used_fdu, self._n_param))
        return dim_matrix

    def _extract_param_exp(self, param: Parameter) -> List[int]:
        """_extract_param_exp Extracts the exponents of a parameter's dimensions.

        Args:
            param (Parameter): The parameter to extract exponents from.

        Returns:
            List[int]: List of exponents for the parameter's dimensions.
        """
        exponents = list()
        fdu_pow_lt = param._exp_dim_lt
        for tfdu, tpow in zip(FDU, fdu_pow_lt):
            if tfdu in self._used_fdu_lt:
                exponents.append(tpow)
        exponents = np.array(exponents)
        return exponents

    def _fill_dim_matrix(self) -> None:  # np.ndarray:
        """_fill_dim_matrix Fills the dimensional matrix with exponents from the parameters.
        """
        for param in self.dimensional_lt:
            t_exp_vec = self._extract_param_exp(param)
            i = self.dimensional_lt.index(param)
            # print(i, t_exp_vec)
            self._cur_dim_matrix[:, i] = t_exp_vec
        # print(self._cur_dim_matrix)
        # return self._cur_dim_matrix

    def _transpose_dim_matrix(self) -> None:
        """_transpose_dim_matrix Transposes the dimensional matrix.
        """
        self._trans_dim_matrix = self._cur_dim_matrix.transpose()

    def config_dim_matrix(self) -> None:
        """config_dim_matrix Configures the dimensional matrix by:
            - Initializing the matrix.
            - Filling it with parameter exponents.
            - Transposing the matrix.
        """
        # creating the zero filled dimensional matrix
        self._cur_dim_matrix = self._start_dim_matrix()
        # filling the dimensional matrix
        self._fill_dim_matrix()
        # creating the transpose dimensional matrix
        self._transpose_dim_matrix()

    def get_pi_coefficients(self,
                            symbol_lt: List[str],
                            dim_matrix: np.ndarray
                            ) -> Optional[List[PiCoefficient]]:
        """get_pi_coefficients Computes the dimensionless Pi coefficients using the null space of the dimensional matrix.

        Args:
            symbol_lt (List[str]): List of parameter symbols.
            dim_matrix (np.ndarray): Dimensional matrix.

        Returns:
            Optional[List[PiCoefficient]]: List of computed Pi coefficients.
        """
        coefficient_lt = list()
        dim_matrix = Matrix(dim_matrix)
        pi_rref = dim_matrix.rref()
        pi_matrix = matrix2numpy(pi_rref[0])
        pi_pivot_col_lt = pi_rref[1]
        pi_lin_ind_lt = dim_matrix.nullspace()
        for tpi_exp in pi_lin_ind_lt:
            tpi_exp = matrix2numpy(tpi_exp).T
            tpi_coeff = PiCoefficient(_pi_param_lt=symbol_lt,
                                      _pi_exp_lt=tpi_exp,
                                      _rref_dim_matrix=pi_matrix,
                                      _pivot_lt=pi_pivot_col_lt)
            coefficient_lt.append(tpi_coeff)
        return coefficient_lt

    def solve_dim_matrix(self):
        """solve_dim_matrix Solves the dimensional matrix to compute the Pi coefficients.
        """
        symbol_lt = [param.symbol for param in self.dimensional_lt]
        self.pi_coefficients = self.get_pi_coefficients(symbol_lt,
                                                        self._cur_dim_matrix)
