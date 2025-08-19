import re

# LATEX_RE = r"^(\\?[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9]+\})?(\*?[a-zA-Z0-9]*)*(\\frac\{[a-zA-Z0-9*+\-/]+\}\{[a-zA-Z0-9*+\-/]+\})?)$"

# LATEX_RE = r"^(\\[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9]+\})?(\*[a-zA-Z0-9]*)?(\{[a-zA-Z0-9*+\-/]+\})?(\{[a-zA-Z0-9*+\-/]+\})?|[a-zA-Z]+)$"

# LATEX_RE = r"^(\\[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9]+\})?(\*[a-zA-Z0-9]*)?(\{[a-zA-Z0-9*+\-/]+\})?(\{[a-zA-Z0-9*+\-/]+\})?|[a-zA-Z]+(\*[a-zA-Z0-9]+)?)$"

# LATEX_RE = r"^(\\[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9.+\-*/]+\})?(\*[a-zA-Z0-9]*)?(\{[a-zA-Z0-9*+\-/]+\})?(\{[a-zA-Z0-9*+\-/]+\})?|[a-zA-Z0-9]+(\([a-zA-Z0-9*+\-/]+\))?(\*[a-zA-Z0-9]+)?(/[a-zA-Z0-9*+\-/()]+)?)$"

# LATEX_RE = r"^(\\[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9.+\-*/]+\})?(\*[a-zA-Z0-9]*)?(\{[a-zA-Z0-9*+\-/^]+\})?(\{[a-zA-Z0-9*+\-/^]+\})?|[a-zA-Z0-9]+(\([a-zA-Z0-9*+\-/^]+\))?(\*[a-zA-Z0-9]+)?(/[a-zA-Z0-9*+\-/^()]+)?)$"

# LATEX_RE: str = r"^(\\?[a-zA-Z]+)(_\{[a-zA-Z0-9]+\})?$"

LATEX_RE = r"^(\\[a-zA-Z]+(_\{[a-zA-Z0-9]+\})?(\^\{[a-zA-Z0-9.+\-*/]+\})?(\*[a-zA-Z0-9]*)?(\{[a-zA-Z0-9*+\-/^]+\})?(\{[a-zA-Z0-9*+\-/^]+\})?|[a-zA-Z0-9]+(\([a-zA-Z0-9*+\-/^]+\))?(\*[a-zA-Z0-9]+)?(/[a-zA-Z0-9*+\-/^()]+)?|\\frac\{[a-zA-Z0-9*+\-/^]+\}\{[a-zA-Z0-9*+\-/^0-9.]+\})$"

# Test cases
test_cases = [
    r"\frac{d}{y}",       # Valid fraction
    r"\frac{u}{U}",       # Valid fraction
    r"d",                 # Valid alphanumeric
    r"\Pi_{0}",           # Valid LaTeX with subscript
    r"\rho",              # Valid LaTeX
    r"d*y",               # Valid multiplication
    # r"1.0",             # Valid decimal
    # r"1.0e-3",            # Valid scientific notation
    # r"1.0e+3",            # Valid scientific notation
    # r"1.0e3",             # Valid scientific notation
    r"1/(f*d)",       # Valid fraction with multiplication
    r"1/(f*d*e)",     # Valid fraction with multiplication
    r"\frac{y*P}{U^2.0}",  # Valid fraction with multiplication and exponent
    r"invalid$",          # Invalid
]

for test in test_cases:
    if re.match(LATEX_RE, test):
        print(f"'{test}' is valid.")
    else:
        print(f"'{test}' is invalid.")
