# -*- coding: utf-8 -*-
"""Closed-form queueing-network analytic solvers (M/M/c/K + Jackson + R1/R2/R3)."""

from src.analytic.queues import Queue, BasicQueue
from src.analytic.jackson import solve_network, solve_jackson_lambdas
from src.analytic.metrics import aggregate_network, check_requirements

__all__ = [
    "BasicQueue",
    "Queue",
    "aggregate_network",
    "check_requirements",
    "solve_jackson_lambdas",
    "solve_network",
]
