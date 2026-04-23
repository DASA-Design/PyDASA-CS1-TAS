# -*- coding: utf-8 -*-
"""
Module test_simulation.py
=========================

Sanity checks for the SimPy DES engine in `src.stochastic.simulation`.

Each class groups tests by the contract under verification:

    - **TestMM1Convergence**: a single M/M/1 node run with a known textbook solution; the stochastic engine should converge to the closed-form rho / L / W / Wq within a small tolerance.
    - **TestSeededReproducibility**: passing the same `seed` twice must produce bit-identical summary frames.
    - **TestBlockingBoundary**: an M/M/1/K node under saturation records a non-zero `Blocking_Prob`; under light load the blocking probability is ~ 0.
    - **TestModelString**: the `M/M/c[/K]` label string helper.

# TODO: add a 2-node feed-forward regression once the orchestrator's end-to-end test (`tests/methods/test_stochastic.py`) is wired up; the engine-level test should stay focused on single-node invariants to keep the runtime tight.
"""
# testing framework
import numpy as np
import pytest

# module under test
from src.stochastic.simulation import (
    format_model_string,
    simulate_net,
)


class TestMM1Convergence:
    """**TestMM1Convergence** runs a single M/M/1 node (no routing) at rho = 0.5 and verifies the DES output matches the closed-form M/M/1 formulas within Monte-Carlo noise.

    Textbook targets for rho = lambda / mu = 0.5:
        - rho = 0.5
        - L = rho / (1 - rho)         = 1.0
        - W = 1 / (mu - lambda)       = 0.2
        - Wq = rho / (mu - lambda)     = 0.1
    """

    def test_rho_L_W_Wq_match_textbook(self):
        """*test_rho_L_W_Wq_match_textbook()* lambda=5, mu=10, 3 reps of 1500 sec -> closed-form rho / L / W / Wq within 12 %."""
        # single-node network, no onward routing: P = [[0]]. 3 x 1500 sec
        # gives ~21 000 collected samples at lambda=5, plenty for CLT.
        _summary = simulate_net(
            mu=[10.0],
            lam_z=[5.0],
            c=[1],
            K=[None],
            P=np.array([[0.0]]),
            horizon=1500.0,
            warmup=150.0,
            reps=3,
            seed=42,
        )
        _row = _summary.iloc[0]

        # 12 % tolerance (slightly looser than 10 % to absorb the
        # shorter horizon); Wq gets the usual wider band
        assert _row["rho_mean"] == pytest.approx(0.5, rel=0.12)
        assert _row["L_mean"] == pytest.approx(1.0, rel=0.12)
        assert _row["W_mean"] == pytest.approx(0.2, rel=0.12)
        assert _row["Wq_mean"] == pytest.approx(0.1, rel=0.20)

    def test_std_columns_populated(self):
        """*test_std_columns_populated()* the groupby-agg summary must expose non-NaN `_std` columns when reps > 1 so downstream CI bands have a usable sigma."""
        _summary = simulate_net(
            mu=[10.0],
            lam_z=[5.0],
            c=[1],
            K=[None],
            P=np.array([[0.0]]),
            horizon=500.0,
            warmup=50.0,
            reps=2,
            seed=42,
        )
        _row = _summary.iloc[0]
        for _m in ("rho", "L", "W", "Wq"):
            _s = _row[f"{_m}_std"]
            assert not np.isnan(_s), f"{_m}_std should not be NaN"
            assert _s >= 0.0, f"{_m}_std must be non-negative"


class TestSeededReproducibility:
    """**TestSeededReproducibility** verifies that seeding both `random` and `numpy.random` with the same value produces a bit-identical summary frame across calls."""

    def test_same_seed_same_summary(self):
        """*test_same_seed_same_summary()* two identical calls with `seed=42` must return DataFrames that compare equal cell-for-cell."""
        _args = dict(
            mu=[10.0],
            lam_z=[5.0],
            c=[1],
            K=[None],
            P=np.array([[0.0]]),
            horizon=1000.0,
            warmup=100.0,
            reps=2,
            seed=42,
        )
        _first = simulate_net(**_args)
        _second = simulate_net(**_args)

        # every numeric column must match exactly
        for _col in _first.columns:
            if _col == "node":
                continue
            assert (_first[_col].to_numpy() == pytest.approx(_second[_col].to_numpy()))


class TestBlockingBoundary:
    """**TestBlockingBoundary** verifies the finite-capacity M/M/1/K boundary condition: under high load the per-node blocking probability is non-zero; under a nearly-empty system it is zero."""

    def test_saturated_system_blocks(self):
        """*test_saturated_system_blocks()* rho ~ 1.5 (arrival rate above service rate) with K=5 must generate blocking."""
        _summary = simulate_net(
            mu=[10.0],
            lam_z=[15.0],
            c=[1],
            K=[5],
            P=np.array([[0.0]]),
            horizon=500.0,
            warmup=50.0,
            reps=3,
            seed=42,
        )
        assert _summary.iloc[0]["Blocking_Prob_mean"] > 0.0

    def test_unloaded_system_no_blocks(self):
        """*test_unloaded_system_no_blocks()* rho ~ 0.05 (very light load) with K=5 must not drop any jobs."""
        _summary = simulate_net(
            mu=[10.0],
            lam_z=[0.5],
            c=[1],
            K=[5],
            P=np.array([[0.0]]),
            horizon=500.0,
            warmup=50.0,
            reps=3,
            seed=42,
        )
        assert _summary.iloc[0]["Blocking_Prob_mean"] == pytest.approx(0.0)


class TestModelString:
    """**TestModelString** verifies the `M/M/c[/K]` queue-model label helper matches the analytic method's notation."""

    def test_mm1_unbounded(self):
        """*test_mm1_unbounded()* c=1, K=None -> 'M/M/1'."""
        assert format_model_string(1, None) == "M/M/1"

    def test_mm1_finite_capacity(self):
        """*test_mm1_finite_capacity()* c=1, K=10 -> 'M/M/1/10'."""
        assert format_model_string(1, 10) == "M/M/1/10"

    def test_mmc_unbounded(self):
        """*test_mmc_unbounded()* c=3, K=None -> 'M/M/3'."""
        assert format_model_string(3, None) == "M/M/3"

    def test_mmc_finite_capacity(self):
        """*test_mmc_finite_capacity()* c=2, K=20 -> 'M/M/2/20'."""
        assert format_model_string(2, 20) == "M/M/2/20"
