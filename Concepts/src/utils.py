# python native modules
# from dataclasses import dataclass
from typing import TypeVar

# generic type for all types
T = TypeVar("T")    # T can be any type

# Fundamental Dimensional Units (FDU)
# PHYSICAL + SOFTWARE
# mass [M], length [L], time [T],
# temperature [θ], electric current [I],
# amount of substance [N], luminous intensity [J],
# data [D], software abstractions [A]
FUND_DIM_UNIT_RE = r"^[LMTθINJDA](\^-?\d+)?(\*[LMTθINJDA](?:\^-?\d+)?)*$"

# PATTERN TO ADD PARENTHESES TO POWERS
DIGIT_POW_RE = r"\-?\d+"   # r'\^(-?\d+)'

# PATTERN TO ADD POW ^1 TO * AND / OPERATIONS
BASIC_DIGIT_POW_RE = r"[LMTθINJDA](?!\^)"
# r"^[LMTθINJDA]?|([^\*]?([LMTθINJDA][^\^]))|[LMTθINJDA][^\^]$"
# r"([LMTθINJDA])\*{1}"
# ^[LMTθINJDA][^\^]|([^\*]?([LMTθINJDA][^\^]))|[LMTθINJDA][^\^]$

# ARRAY OF FUNDAMENTAL DIMENSIONAL UNITS PRECEDENCE
FDU = ["L", "M", "A", "D", "T", "θ", "I", "N", "J",]

# RE PATTERN FOR DEFINING DIGITS IN POWERS
EXP_PATTERN_STR = r"\-?\d+"

# RE PATTERN FOR DEFINING FUNDAMENTAL DIMENSIONAL UNITS
FDU_PATTERN_STR = r"[LMTθINJDA]"
