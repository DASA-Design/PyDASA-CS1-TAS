import re
from sympy import symbols
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application

# Example input string (can be user-provided)
expr_str = "alpha*beta^2/sigma"

# Find all variable names (alphanumeric and underscores, not numbers)
var_names = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', expr_str))

# Create symbols dynamically
local_dict = {name: symbols(name) for name in var_names}

# Use transformations (including implicit multiplication and ^ as power)
transformations = standard_transformations + \
    (implicit_multiplication_application,)

# Replace ^ with ** for power (Python syntax)
expr_str_py = expr_str.replace('^', '**')

# Parse the expression
expr = parse_expr(expr_str_py,
                  local_dict=local_dict,
                  transformations=transformations)

print("Parsed expression:", expr)
print("Python code:", repr(expr))
print("Variables detected:", var_names)

# Assign values and evaluate the expression
values = {'alpha': 2, 'beta': 3, 'sigma': 4}
result = expr.subs(values)
print("Result with values", values, ":", float(result))
