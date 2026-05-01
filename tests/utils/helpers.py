"""
Module test_helpers.py
======================

Usable fixtures, builders, and helper callables for service tests. These are not test-specific but are only used in tests, so they live here instead of `src/experiment/services`.
"""

# modules for tests
from src.experiment.services.base import SvcSpec

class _SpecBuilder:
    """*_SpecBuilder* callable that builds a `SvcSpec` with sensible defaults; tests call it like `spec_builder(name=...)`."""

    def __call__(self, *,
                 name: str = "MAS_{1}",
                 role: str = "atomic",
                 port: int = 8006,
                 mu: float = 1000.0,
                 epsilon: float = 0.0,
                 c: int = 1,
                 K: int = 10,
                 seed: int = 42) -> SvcSpec:
        specs = SvcSpec(name=name,
                        role=role,
                        port=port,
                        mu=mu,
                        epsilon=epsilon,
                        c=c,
                        K=K,
                        seed=seed)
        return specs
