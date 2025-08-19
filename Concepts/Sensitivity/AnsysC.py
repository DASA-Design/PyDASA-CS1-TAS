import numpy as np
from SALib.sample.fast_sampler import sample
from SALib.analyze.fast import analyze
from sympy.parsing.latex import parse_latex
from sympy import lambdify, diff    # , symbols
# import numpy as np
# import re
# Beware pip install should be: pip install antlr4-python3-runtime==4.11


def generate_function_from_latex(latex_expr: str) -> tuple:
    """
    Generate a custom function from a LaTeX expression.

    Args:
        latex_expr (str): The LaTeX expression to convert.

    Returns:
        function: A Python function that evaluates the expression.
        variables: List of variables in the function.
    """
    # Parse the LaTeX expression into a sympy expression
    sympy_expr = parse_latex(latex_expr)

    # Extract variables from the sympy expression
    variables = sorted(sympy_expr.free_symbols, key=lambda s: s.name)

    # Generate a callable function using lambdify
    custom_function = lambdify(variables, sympy_expr, "numpy")
    return custom_function, [str(v) for v in variables]


def numeric_sensitivity_analysis(function: callable,
                                 bounds: dict,
                                 num_samples: int = 1000) -> dict:
    """numeric_sensitivity_analysis _summary_

    Args:
        function (callable): _description_
        variables (list): _description_
        bounds (dict): _description_
        num_samples (int, optional): _description_. Defaults to 1000.

    Returns:
        dict: _description_
    """
    # Generate samples using the FAST method
    param_values = sample(bounds, num_samples)

    # Reshape the samples to match the expected input format for the custom function
    param_values = param_values.reshape(-1, bounds["num_vars"])

    # Evaluate the custom function for all samples
    print(function)
    Y = np.apply_along_axis(lambda row: function(*row), 1, param_values)

    # Perform sensitivity analysis using FAST
    n_ansys = analyze(bounds, Y)

    return n_ansys


def symbolic_sensitivity_analysis(function: callable,
                                  variables: list,
                                  param_values: dict) -> dict:
    """
    Perform symbolic sensitivity analysis on a custom function.

    Args:
        function (callable): The custom function to analyze.
        variables (list): List of sympy symbols representing the parameters.
        param_values (dict): Dictionary of parameter values for evaluation.

    Returns:
        dict: Sensitivities of the function with respect to each parameter.
    """
    exec_function = parse_latex(function)
    sensitivities = {}
    for param in variables:
        # Compute the partial derivative of the function with respect to the parameter
        partial_derivative = diff(exec_function, param)

        # Convert the derivative to a callable function
        derivative_func = lambdify(variables, partial_derivative, "numpy")

        # Evaluate the derivative at the given parameter values
        sensitivity_value = derivative_func(*[param_values[p] for p in variables])
        sensitivities[param] = sensitivity_value

    return sensitivities


def setup_parameters(params: list, bounds: list) -> dict:
    """
    Setup parameters for the sensitivity analysis.

    Args:
        params (list): List of parameter names.
        bounds (list): List of bounds for each parameter.

    Returns:
        dict: Dictionary of parameter names and their bounds.
    """
    specs = {}
    for k, v in zip(params, bounds):
        v = sum([float(min(v)), float(max(v))]) / 2
        specs[k] = v
    return specs


# Define LaTeX expressions
latex_expressions = [
    r"\frac{u}{U}",
    r"\frac{y*P}{U^2.0}",
    r"\frac{v}{y*U}"
]

# Process each LaTeX expression to generate functions
functions = []
problems = []

for latex_expr in latex_expressions:
    custom_function, variables = generate_function_from_latex(latex_expr)

    # Define the problem for SALib
    print("variables", variables)
    problem = {
        "num_vars": len(variables),  # Number of variables
        "names": variables,  # Names of the variables
        "bounds": [[0.1, 10]] * len(variables),  # Bounds for each variable
    }

    functions.append((custom_function, problem))
    problems.append(problem)

# Perform sensitivity analysis for each function
num_samples = 1000

for i, (custom_function, problem) in enumerate(functions):
    print(f"\nAnalyzing Function {i + 1}: {latex_expressions[i]}")

    # the problem contiains the variables and their bounds
    n_ansys = numeric_sensitivity_analysis(custom_function,
                                           problem,
                                           num_samples)

    param_values = setup_parameters(problem["names"],
                                    problem["bounds"])
    print(f"Parameter values: {param_values}")
    s_ansys = symbolic_sensitivity_analysis(latex_expressions[i],
                                            problem["names"],
                                            param_values)

    # Print results
    print("Numeric Sensitivity Indices:")
    for name, S1 in zip(problem["names"], n_ansys["S1"]):
        print(f"  {name}: {S1:.6f}")
    print("Symbolic Sensitivity Indices:")
    for name, S1 in zip(problem["names"], s_ansys.values()):
        print(f"  {name}: {S1:.6f}")
