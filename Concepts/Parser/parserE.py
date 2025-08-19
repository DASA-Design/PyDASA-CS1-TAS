from sympy.parsing.latex import parse_latex
from sympy import symbols, lambdify
import re


def extract_latex_vars(expr):
    """Extract variable names in LaTeX format with their Python equivalents"""
    # Matches names like l_{1}, W_{2}, L_{1}, N_{2}, u, l, x, \alpha, \beta_{1}
    pattern = r"\\?[a-zA-Z]+(?:_\{\d+\})?"
    matches = re.findall(pattern, expr)

    # Create mappings both ways
    latex_to_py = {}
    py_to_latex = {}

    for m in matches:
        # Convert to Python style for internal use
        py_var = m.lstrip("\\").replace("_{", "_").replace("}", "")
        # Keep original LaTeX notation for external reference
        latex_var = m

        latex_to_py[latex_var] = py_var
        py_to_latex[py_var] = latex_var

    return latex_to_py, py_to_latex


def create_symbol_mapping(latex_expr):
    """Create mapping between LaTeX symbols and Python symbols while preserving original notation"""
    # Get LaTeX<->Python variable mappings
    latex_to_py, py_to_latex = extract_latex_vars(latex_expr)

    # Parse to get LaTeX symbols
    expr = parse_latex(latex_expr)
    # latex_symbols = expr.free_symbols

    # Create mapping for sympy substitution
    symbol_map = {}         # For internal substitution
    py_symbol_map = {}      # For lambdify
    # latex_symbol_map = {}   # For result keys

    for latex_sym in expr.free_symbols:
        # latex_name = str(latex_sym)
        latex_name = str(latex_sym)

        # Find corresponding Python name
        for latex_var, py_var in latex_to_py.items():
            # Check for various forms of equivalence
            con1 = (latex_name == latex_var)
            con2 = (latex_name == py_var)
            con3 = (latex_name.replace("_{", "_").replace("}", "") == py_var)
            if con1 or con2 or con3:
                # Create symbol for this variable
                sym = symbols(py_var)
                # Store mappings
                symbol_map[latex_sym] = sym  # For substitution
                py_symbol_map[py_var] = sym  # For lambdify args
                # latex_symbol_map[latex_var] = sym  # For original notation
                break
    return symbol_map, py_symbol_map, latex_to_py, py_to_latex


# Test LaTeX expressions
latex_exprs = [
    "l_{1} W_{2}",
    "\\frac{u}{l}",
    "\\frac{x}{l}",
    "\\frac{L_{1}^{2}}{N_{2}^{2}}",
    "\\alpha*\\beta_{1}",
    "\\frac{\\alpha}{\\lambda_{1}}",
]

# Example values using original LaTeX notation
examples = {
    "l_{1}": 2, "W_{2}": 3,
    "u": 8, "l": 2,
    "x": 10, "L_{1}": 4, "N_{2}": 2,
    "\\alpha": 1.5, "\\beta_{1}": 0.5,
    "\\lambda_{1}": 2.0
}

for idx, latex_expr in enumerate(latex_exprs):
    print(f"\n--- Expression {idx}: {latex_expr} ---")

    # Parse the LaTeX expression
    expr = parse_latex(latex_expr)
    print(f"Original parsed: {expr}")

    # Create mappings
    symbol_map, py_symbol_map, latex_to_py, py_to_latex = create_symbol_mapping(latex_expr)
    print(f"LaTeX to Python mapping: {latex_to_py}")

    # Substitute LaTeX symbols with Python symbols
    for latex_sym, py_sym in symbol_map.items():
        expr = expr.subs(latex_sym, py_sym)
    print(f"Substituted parsed: {expr}")

    # Get Python variable names
    py_vars = sorted([str(s) for s in expr.free_symbols])
    print(f"Python variables: {py_vars}")

    # Convert back to LaTeX variables for result keys
    latex_vars = [py_to_latex.get(v, v) for v in py_vars]
    print(f"LaTeX variables: {latex_vars}")

    if py_vars:
        # Create lambdify function using Python symbols
        f = lambdify([py_symbol_map[v] for v in py_vars], expr, "numpy")

        # Get values using LaTeX variable names
        val_args = [examples[py_to_latex[v]] for v in py_vars]
        result = f(*val_args)

        # Create result dict with LaTeX keys
        latex_results = {py_to_latex[v]: val for v, val in zip(py_vars, val_args)}
        print(f"With {latex_results} => {result}")
