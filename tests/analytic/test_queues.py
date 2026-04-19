# -*- coding: utf-8 -*-
"""
Module test_queues.py
=====================

Sanity checks for the closed-form queue models in `src.analytic.queues`
and the helper `gfactorial()` in `src.utils.mathx`.

Each class groups tests by the contract under verification:

    - **TestGFactorial**: numerical correctness of the generalised factorial across integers and halves.
    - **TestMM1**: M/M/1 closed-form formulas and guard-rails.
    - **TestMMcK**: M/M/c/K formulas, M/M/s/K alias, and capacity-vs- server-count invariants.
    - **TestFactoryErrors**: registry-level errors from the `Queue()` factory when the model string is not supported.

# TODO: extend with M/M/s and M/M/1/K coverage as those paths get used.
"""
# native python modules
import math

# testing framework
import pytest

# modules under test
from src.analytic.queues import Queue
from src.utils.mathx import gfactorial


class TestGFactorial:
    """**TestGFactorial** covers `gfactorial()` across integers, zero, and the half-integer case (which dispatches to the gamma branch)."""

    def test_zero(self):
        """*test_zero()* 0! must equal 1 by convention."""
        assert gfactorial(0) == 1

    def test_small_int(self):
        """*test_small_int()* 5! = 120 (standard integer branch)."""
        assert gfactorial(5) == 120

    def test_half(self):
        """*test_half()* gfactorial(0.5) = Γ(1.5) = 0.5 * sqrt(π)."""
        _expected = 0.5 * math.sqrt(math.pi)
        assert gfactorial(0.5) == pytest.approx(_expected)


class TestMM1:
    """**TestMM1** verifies the M/M/1 closed-form against the textbook worked example: lamb=1, mu=2 => rho=0.5, L=1, Lq=0.5, W=1, Wq=0.5."""

    def test_textbook(self):
        """*test_textbook()* all five M/M/1 metrics match the closed-form solution at rho = 0.5."""
        # build the M/M/1 instance with textbook parameters
        _q = Queue("M/M/1", lamb=1.0, mu=2.0)
        _q.calculate_metrics()

        # Utilization and performance metrics
        assert _q.rho == pytest.approx(0.5)
        assert _q.avg_len == pytest.approx(1.0)
        assert _q.avg_len_q == pytest.approx(0.5)
        assert _q.avg_wait == pytest.approx(1.0)
        assert _q.avg_wait_q == pytest.approx(0.5)

    def test_unstable_raises(self):
        """*test_unstable_raises()* lamb > mu (rho >= 1) must be rejected by the model's `_validate_params` hook."""
        with pytest.raises(ValueError, match="unstable"):
            Queue("M/M/1", lamb=2.0, mu=1.0)

    def test_rejects_finite_capacity(self):
        """*test_rejects_finite_capacity()* M/M/1 rule is 'infinite' capacity; passing K_max must be rejected by the factory."""
        with pytest.raises(ValueError, match="infinite"):
            Queue("M/M/1", lamb=1.0, mu=2.0, K_max=10)


class TestMMcK:
    """**TestMMcK** verifies the M/M/c/K closed-form and the shared shape invariants (K >= c, factory aliasing, probability mass)."""

    def test_basic_rho(self):
        """*test_basic_rho()* c=1, K=2, lamb=1, mu=2 => rho=0.5, and the mean length stays bounded within [0, K]."""
        _q = Queue("M/M/c/K", lamb=1.0, mu=2.0, c_max=1, K_max=2)
        _q.calculate_metrics()

        # Utilization
        assert _q.rho == pytest.approx(0.5)
        # L should be strictly positive and bounded above by K
        assert 0 < _q.avg_len < 2

    def test_slash_s_slash_k_alias(self):
        """*test_slash_s_slash_k_alias()* 'M/M/s/K' (as declared in the config) resolves to the same class as 'M/M/c/K'."""
        # both model strings must point at the same concrete class
        _q_alias = Queue("M/M/s/K", lamb=1.0, mu=2.0, c_max=1, K_max=2)
        _q_canon = Queue("M/M/c/K", lamb=1.0, mu=2.0, c_max=1, K_max=2)
        assert type(_q_alias).__name__ == type(_q_canon).__name__

    def test_rejects_k_below_c(self):
        """*test_rejects_k_below_c()* K < c is impossible (cannot hold more servers than slots); the factory must reject it."""
        with pytest.raises(ValueError, match="K >= c"):
            Queue("M/M/c/K", lamb=1.0, mu=2.0, c_max=3, K_max=2)

    def test_probs_sum_to_one(self):
        """*test_probs_sum_to_one()* the state distribution P(n) must integrate to 1 over the reachable range [0, K_max]."""
        _q = Queue("M/M/c/K", lamb=1.0, mu=2.0, c_max=2, K_max=5)
        _q.calculate_metrics()

        # Sum P(n) over the full reachable state space
        _total = sum(_q.calculate_prob_n(n) for n in range(_q.K_max + 1))
        assert _total == pytest.approx(1.0, abs=1e-9)


class TestFactoryErrors:
    """**TestFactoryErrors** covers registry-level errors that the `Queue()` factory raises before any class is instantiated."""

    def test_unknown_model(self):
        """*test_unknown_model()* a model string that is not in the `_QUEUE_MODELS` registry must raise `NotImplementedError`."""
        with pytest.raises(NotImplementedError,
                           match="Unsupported queue model"):
            Queue("G/G/1", lamb=1.0, mu=2.0)
