from sympy import symbols, diff, lambdify
# import numpy as np
# sensitivity analysis using sympy and numpy


def sensitivity_analysis(func, params, param_values):
    """
    Perform sensitivity analysis on a custom function.

    Args:
        func (sympy.Expr): The custom function to analyze.
        params (list): List of sympy symbols representing the parameters.
        param_values (dict): Dictionary of parameter values for evaluation.

    Returns:
        dict: Sensitivities of the function with respect to each parameter.
    """
    sensitivities = {}
    for param in params:
        # Compute the partial derivative of the function with respect to the parameter
        partial_derivative = diff(func, param)

        # Convert the derivative to a callable function
        derivative_func = lambdify(params, partial_derivative, "numpy")

        # Evaluate the derivative at the given parameter values
        sensitivity_value = derivative_func(*[param_values[p] for p in params])
        sensitivities[param] = sensitivity_value

    return sensitivities


# Define the custom function and parameters
x, y, z = symbols('x y z')
custom_function = x**2 * y + y * z**3

# Define parameter values for evaluation
param_values = {x: 2, y: 3, z: 1}

# Perform sensitivity analysis
params = [x, y, z]
sensitivities = sensitivity_analysis(custom_function, params, param_values)

# Print results
print("Custom Function:", custom_function)
print("Parameter Values:", param_values)
print("Sensitivities:")
for param, sensitivity in sensitivities.items():
    print(f"  ∂f/∂{param} = {sensitivity}")
