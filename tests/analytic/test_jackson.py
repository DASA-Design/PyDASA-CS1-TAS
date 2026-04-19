# -*- coding: utf-8 -*-
"""
Module test_jackson.py
======================

Sanity checks for the Jackson traffic-equation solver in
`src.analytic.jackson`. Covers the linear-algebra core in isolation; the `solve_network()` wrapper is exercised end-to-end by the analytic method test suite.

    - **TestJacksonSolver**: small worked examples where the expected per-node arrival rates are obvious from flow conservation.

# TODO: add a regression case for a 3-node cycle with external arrivals at multiple nodes, once that topology is actually used.
"""
# native python modules
# (none)

# scientific stack
import numpy as np

# testing framework
import pytest

# module under test
from src.analytic.jackson import solve_jackson_lambdas


class TestJacksonSolver:
    """**TestJacksonSolver** verifies that `solve_jackson_lambdas()`
    returns the per-node arrival rates expected from flow conservation
    on small, hand-checkable topologies."""

    def test_two_node_feedforward(self):
        """*test_two_node_feedforward()* node 0 routes everything to node 1 (p=1). External arrivals enter node 0 only. Expected: lamb_0 = lamb_ext, lamb_1 = p * lamb_0.
        """
        # Routing matrix: row = source, col = dest. All flow 0 -> 1.
        _P = np.array([[0.0, 1.0],
                       [0.0, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [10.0, 0.0])

        # node 0 sees the full external rate; node 1 inherits all of it
        assert _lambdas[0] == pytest.approx(10.0)
        assert _lambdas[1] == pytest.approx(10.0)

    def test_two_node_split(self):
        """*test_two_node_split()* node 0 routes 70 % of its flow to node 1 and 30 % to the exit. External arrivals only at node 0."""
        _P = np.array([[0.0, 0.7],
                       [0.0, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [100.0, 0.0])

        # node 0 carries the full 100; node 1 receives 70 % of it
        assert _lambdas[0] == pytest.approx(100.0)
        assert _lambdas[1] == pytest.approx(70.0)

    def test_no_external_no_flow(self):
        """*test_no_external_no_flow()* with zero external arrivals, every node's effective arrival rate must be zero regardless of the routing matrix."""
        _P = np.array([[0.0, 0.5],
                       [0.5, 0.0]])
        _lambdas = solve_jackson_lambdas(_P, [0.0, 0.0])

        # no arrivals anywhere => the whole system is idle
        assert np.allclose(_lambdas, 0.0)

    def test_shape_preserved(self):
        """*test_shape_preserved()* the solver's output vector must match the input dimensionality (13-node TAS baseline)."""
        _P = np.zeros((13, 13))
        _lambdas = solve_jackson_lambdas(_P, np.zeros(13))

        # shape must match the number of nodes in the network
        assert _lambdas.shape == (13,)
