from sympy.parsing.latex import parse_latex
from sympy import symbols, lambdify
import re


def extract_latex_vars(expr):
    """Extract variable names and convert to Python style"""
    # Matches names like l_{1}, W_{2}, L_{1}, N_{2}, u, l, x, \alpha, \beta_{1}
    pattern = r'\\?[a-zA-Z]+(?:_\{\d+\})?'
    matches = re.findall(pattern, expr)
    # Convert LaTeX subscript to Python style, e.g., l_{1} -> l_1, \alpha -> alpha
    py_vars = []
    for m in matches:
        py_var = m.lstrip('\\').replace('_{', '_').replace('}', '')
        py_vars.append(py_var)
    return py_vars


def create_symbol_mapping(latex_expr):
    """Create mapping between LaTeX symbols and Python symbols"""
    # Parse to get LaTeX symbols
    expr = parse_latex(latex_expr)
    latex_symbols = expr.free_symbols

    # Get Python variable names
    py_vars = extract_latex_vars(latex_expr)

    # Create mapping
    symbol_map = {}
    py_symbol_map = {}

    for latex_sym in latex_symbols:
        latex_name = str(latex_sym)
        # Find corresponding Python name
        for py_var in py_vars:
            # Check if this Python var corresponds to the LaTeX symbol
            if (latex_name == py_var or  # Direct match
                latex_name.replace('_{', '_').replace('}', '') == py_var or  # Subscript conversion
                latex_name.replace('\\', '') == py_var):  # Remove backslash
                symbol_map[latex_sym] = symbols(py_var)
                py_symbol_map[py_var] = symbols(py_var)
                break

    return symbol_map, py_symbol_map


# Test LaTeX expressions
latex_exprs = [
    "l_{1} W_{2}",
    "\\frac{u}{l}",
    "\\frac{x}{l}",
    "\\frac{L_{1}^{2}}{N_{2}^{2}}",
    "\\alpha*\\beta_{1}",
]

# Example values for variables
values = {
    'l_1': 2, 'W_2': 3,
    'u': 8, 'l': 2,
    'x': 10, 'L_1': 4, 'N_2': 2,
    'alpha': 1.5, 'beta_1': 0.5
}

for idx, latex_expr in enumerate(latex_exprs):
    print(f"\n--- Expression {idx}: {latex_expr} ---")

    # Parse the LaTeX expression
    expr = parse_latex(latex_expr)
    print(f"Original parsed: {expr}")
    print(f"LaTeX symbols: {expr.free_symbols}")

    # Create symbol mapping
    latex_to_py_map, py_symbol_map = create_symbol_mapping(latex_expr)
    print(f"Symbol mapping: {latex_to_py_map}")
    print(f"Python symbols: {py_symbol_map}")

    # Substitute LaTeX symbols with Python symbols
    for latex_sym, py_sym in latex_to_py_map.items():
        expr = expr.subs(latex_sym, py_sym)

    print(f"After substitution: {expr}")

    # Get Python variable names
    expr_vars = sorted([str(s) for s in expr.free_symbols])
    print(f"Python variables: {expr_vars}")

    if expr_vars:
        # Create lambdify function using Python symbols
        f = lambdify([py_symbol_map[v] for v in expr_vars], expr, "numpy")
        val_args = [values[v] for v in expr_vars]
        result = f(*val_args)
        print(f"With {dict(zip(expr_vars, val_args))} => {result}")
