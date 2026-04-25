﻿import numpy as np
import pandas as pd
from typing import List, Union
# import os
# from pydasa import Queue
from __OLD__.src.model.queueing import QueueMM1, QueueMMs, QueueMM1K, QueueMMsK
# import random
# import simpy

Queue = Union[QueueMM1, QueueMMs, QueueMM1K, QueueMMsK]


# -----------------------------
# Analytical Solver (Jackson)
# -----------------------------


def solve_jackson_network(mu: List[float],
                          lambda_zero: List[float],
                          queues: List[Queue],
                          P: np.ndarray) -> pd.DataFrame:
    """*solve_jackson_network()* solves the open Jackson network using traffic equations.

    Args:
        mu (List[float]): Service rates for each node.
        lambda_zero (List[float]): Arrival rates for each node.
        queues (List[Queue]): List of Queue instances representing each node.
        P (np.ndarray): State transition probability matrix.

    Raise:
        ValueError: If the system is unstable (ρ >= 1 at some node).

    Returns:
        pd.DataFrame: DataFrame containing performance metrics for each node.
    """
    # creating identity matrix
    Is = np.eye(len(mu))
    # solving for lambdas
    lambdas = np.linalg.solve(Is - P.T, lambda_zero)
    lambdas = list(lambdas)

    # initializing lists for performance metrics
    rho = []
    L = []
    Lq = []
    W = []
    Wq = []

    # iterating over each node's parameters
    # for la, m, n, k in zip(lambdas, mu, n_servers, kap):
    for q, la in zip(queues, lambdas):
        # creating Queue instance for each node
        # q = Queue(la, m, n, k)
        q._lambda = la
        # calculating metrics for the queue
        q.calculate_metrics()
        # print("---------")
        # print(q)
        # print("---------")

        # append metric results
        rho.append(q.rho)
        L.append(q.avg_len)
        Lq.append(q.avg_len_q)
        W.append(q.avg_wait)
        Wq.append(q.avg_wait_q)

    # Format rho values for console output
    if any(r > 1.0 for r in rho):
        aprox_rho = [f"{r:.4f}" for r in rho]
        _msg = f"Warning!, unestable system!, calculated rho (ρ): {aprox_rho}"
        raise ValueError(_msg)

    # # Calculate network-wide metrics
    # net_metrics = calculate_net_metrics(lambdas, L, Lq, W, Wq, rho, mu)

    # Create DataFrame for node-specific metrics
    node_metrics = pd.DataFrame({
        "node": range(1, len(lambdas) + 1),
        "lambda": lambdas,
        "mu": mu,
        "rho": rho,
        "L": L,
        "Lq": Lq,
        "W": W,
        "Wq": Wq
    })

    # Return individual node metrics
    return node_metrics


def calculate_net_metrics(nd_metrics: pd.DataFrame) -> pd.DataFrame:
    """*calculate_net_metrics()* calculates network-wide performance metrics for a Jackson network.

    Args:
        nd_metrics (pd.DataFrame): DataFrame containing node-specific performance metrics. The expected columns are:
            - "lambda": Arrival rates at each node.
            - "mu": Service rates at each node. (Optional, if available)
            - "rho": Utilization at each node. (Optional, if available)
            - "L": Average number of jobs in the system at each node.
            - "Lq": Average number of jobs waiting in queues at each node.
            - "W": Average time a job spends in the system at each node.
            - "Wq": Average time a job spends waiting in queues at each node.

    Returns:
        pd.DataFrame: DataFrame containing network-wide performance metrics.
    """
    lambdas = nd_metrics["lambda"].tolist()
    L = nd_metrics["L"].tolist()
    Lq = nd_metrics["Lq"].tolist()
    W = nd_metrics["W"].tolist()
    Wq = nd_metrics["Wq"].tolist()
    rho = nd_metrics["rho"].tolist() if "rho" in nd_metrics.columns else None
    mu = nd_metrics["mu"].tolist() if "mu" in nd_metrics.columns else None

    # Sum of all arrival rates (total throughput)
    total_lambda = np.sum(lambdas)

    # Total L and Lq are the sum of all node L and Lq values
    L_network = np.sum(L)
    Lq_network = np.sum(Lq)

    # For W and Wq, we need to consider the relative importance of each node
    # based on its arrival rate (throughput-weighted average)
    if total_lambda > 0:
        # Weighted averages based on relative throughput
        W_network = np.sum(np.multiply(W, lambdas)) / total_lambda
        Wq_network = np.sum(np.multiply(Wq, lambdas)) / total_lambda
    else:
        W_network = 0
        Wq_network = 0

    # Average utilization (arithmetic mean of node utilizations)
    avg_rho = np.mean(rho) if rho is not None and len(rho) > 0 else 0

    # Average service rate (arithmetic mean of node service rates)
    avg_mu = np.mean(mu) if mu is not None and len(mu) > 0 else 0

    # Create DataFrame for network-wide metrics
    net_metrics = pd.DataFrame({
        "avg_mu": [avg_mu],
        "avg_rho": [avg_rho],
        "L_net": [L_network],
        "Lq_net": [Lq_network],
        "W_net": [W_network],
        "Wq_net": [Wq_network],
        "total_throughput": [total_lambda]
    })
    return net_metrics
