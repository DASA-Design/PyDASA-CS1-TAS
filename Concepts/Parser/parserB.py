from sympy import symbols, lambdify
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication_application
import re

# Example input string (programming style, not LaTeX)
expr_str = "5*alpha1*beta_2"

# Extract variable names
var_names = set(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', expr_str))

# Create symbols dynamically
local_dict = {name: symbols(name) for name in var_names}

# Use transformations to allow implicit multiplication (optional)
transformations = standard_transformations + \
    (implicit_multiplication_application,)

# Parse the expression
expr = parse_expr(expr_str, local_dict=local_dict,
                  transformations=transformations)

print("Parsed expression:", expr)
print("Python code:", repr(expr))
print("Variables detected:", var_names)

# Assign values and evaluate using lambdify
ordered_vars = [local_dict[name] for name in sorted(var_names)]
f = lambdify(ordered_vars, expr, "numpy")
result = f(2, 3)  # alpha1=2, beta_2=3

print("Result with alpha1=2, beta_2=3:", result)
