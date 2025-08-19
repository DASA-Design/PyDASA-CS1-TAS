from dataclasses import dataclass, field
from typing import Callable, List
import numpy as np
import random


@dataclass
class MonteCarloSimulation:
    iterations: int                          # Number of simulation runs
    model_function: Callable[..., float]     # Function to simulate
    # List of functions to sample inputs
    input_distributions: List[Callable[[], float]]
    # Store simulation results
    results: List[float] = field(default_factory=list)

    def run(self):
        self.results.clear()
        for _ in range(self.iterations):
            inputs = [dist() for dist in self.input_distributions]
            result = self.model_function(*inputs)
            self.results.append(result)

    def mean(self) -> float:
        return np.mean(self.results)

    def variance(self) -> float:
        return np.var(self.results)

    def summary(self) -> dict:
        return {
            "mean": self.mean(),
            "variance": self.variance(),
            "min": min(self.results),
            "max": max(self.results)
        }


# Define model function
def model(x, y):
    return x * y + 2


# Define input distributions
def dist1():
    return random.uniform(0, 1)


def dist2():
    return random.gauss(5, 1)


if __name__ == "__main__":
    # Run simulation
    sim = MonteCarloSimulation(
        iterations=1000,
        model_function=model,
        input_distributions=[dist1, dist2]
    )

    sim.run()
    print(sim.summary())
