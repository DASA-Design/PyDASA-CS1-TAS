import numpy as np
from sympy import symbols, lambdify
from typing import Callable, List, Dict
# Sensitivity analysis using Fourier Amplitude Sensitivity Testing (FAST) with sympy and numpy


def generate_samples(num_samples: int, num_vars: int) -> np.ndarray:
    """
    Generate random samples for the FAST method.

    Args:
        num_samples (int): Number of samples to generate.
        num_vars (int): Number of variables.

    Returns:
        np.ndarray: Array of random samples.
    """
    return np.random.uniform(0, 2 * np.pi, (num_samples, num_vars))


def compute_fast_indices(
    func: Callable, params: List, num_samples: int = 1000
) -> Dict[str, float]:
    """
    Perform Fourier Amplitude Sensitivity Testing (FAST) on a custom function.

    Args:
        func (Callable): The custom function to analyze.
        params (List): List of sympy symbols representing the parameters.
        num_samples (int): Number of samples for the analysis.

    Returns:
        Dict[str, float]: Sensitivity indices for each parameter.
    """
    num_vars = len(params)
    samples = generate_samples(num_samples, num_vars)

    # Frequencies for each variable
    frequencies = np.arange(1, num_vars + 1)

    # Generate the sampling matrix
    omega = np.zeros((num_samples, num_vars))
    for i, freq in enumerate(frequencies):
        omega[:, i] = np.sin(freq * samples[:, i])

    # Evaluate the function for all samples
    func_lambdified = lambdify(params, func, "numpy")
    y = func_lambdified(*[omega[:, i] for i in range(num_vars)])

    # Perform Fourier Transform
    fft_values = np.fft.fft(y)
    amplitudes = np.abs(fft_values)

    # Compute sensitivity indices
    total_amplitude = np.sum(amplitudes)
    sensitivities = {}
    for i, param in enumerate(params):
        first_harmonic = amplitudes[frequencies[i]]
        sensitivities[str(param)] = first_harmonic / total_amplitude

    return sensitivities


# Define the custom function and parameters
x, y, z = symbols("x y z")
custom_function = x**2 * y + y * z**3

# Perform sensitivity analysis
num_samples = 1000
params = [x, y, z]
sensitivity_indices = compute_fast_indices(
    custom_function, params, num_samples)

# Print results
print("Custom Function:", custom_function)
print("Sensitivity Indices:")
for param, sensitivity in sensitivity_indices.items():
    print(f"  {param}: {sensitivity:.6f}")
