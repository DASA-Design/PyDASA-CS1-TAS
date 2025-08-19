from sympy.parsing.latex import parse_latex
from sympy import symbols, lambdify
import re


# Function to extract variable names from LaTeX expressions
def extract_latex_vars(expr):
    # Matches names like l_{1}, W_{2}, L_{1}, N_{2}, u, l, x
    pattern = r'[a-zA-Z]+(?:_\{\d+\})?'
    matches = re.findall(pattern, expr)
    # Convert LaTeX subscript to Python style, e.g., l_{1} -> l_1
    py_vars = [m.replace('_{', '_').replace('}', '') for m in matches]
    return py_vars


# Test LaTeX expressions with multi-character variable names (using _ for subscripts)
latex_exprs = [
    "l_{1} W_{2}",                   # \Pi_{0} = l_{1}*W_{2}
    "\\frac{u}{l}",                   # \Pi_{1} = u/l
    "\\frac{x}{l}",                   # \Pi_{2} = x/l
    "\\frac{L_{1}^{2}}{N_{2}^{2}}",   # \Pi_{3} = L_{1}^2/N_{2}^2
    # "\\alpha*\\beta_{1}",            # \Pi_{4} = \alpha*\beta_{1}
]

# Collect all variable names from all expressions
all_vars = set()
for latex_expr in latex_exprs:
    all_vars.update(extract_latex_vars(latex_expr))

# Create sympy symbols for all variables
local_dict = {name: symbols(name) for name in all_vars}

# Example values for variables
values = {
    'l_1': 2, 'W_2': 3,
    'u': 8, 'l': 2,
    'x': 10, 'L_1': 4, 'N_2': 2,
    # 'alpha': 1.5, 'beta_1': 0.5
}

for idx, latex_expr in enumerate(latex_exprs):
    # Parse the LaTeX expression
    # Parse using provided symbols
    expr = parse_latex(latex_expr)
    print(f"expr: {expr}")
    # Replace LaTeX subscripted symbols with Python variable names
    for latex_var in extract_latex_vars(latex_expr):
        # Convert Python var back to LaTeX for matching
        if '_' in latex_var:
            base, sub = latex_var.split('_')
            latex_sym = symbols(f"{base}_{{{sub}}}")
        else:
            latex_sym = symbols(latex_var)
        expr = expr.subs(latex_sym, symbols(latex_var))
    # Substitute all variables with our symbols (ensures correct mapping)
    expr = expr.subs(local_dict)
    print(f"Expression {idx}: {latex_expr}")
    print("Parsed:", expr)
    # Find which variables are in the expression
    expr_vars = sorted([str(s) for s in expr.free_symbols])
    # Prepare lambdify
    f = lambdify([local_dict[v] for v in expr_vars], expr, "numpy")
    # Prepare values in the correct order
    val_args = [values[v] for v in expr_vars]
    result = f(*val_args)
    print(f"With {dict(zip(expr_vars, val_args))} => {result}\n")

# for idx, latex_expr in enumerate(latex_exprs):
#     expr = parse_latex(latex_expr)
#     print(f"Expression {idx}: {latex_expr}")
#     print("Parsed:", expr)
#     expr_vars = sorted([str(s) for s in expr.free_symbols])
#     f = lambdify([local_dict[v] for v in expr_vars], expr, "numpy")
#     val_args = [values[v] for v in expr_vars]
#     result = f(*val_args)
#     print(f"With {dict(zip(expr_vars, val_args))} => {result}\n")
