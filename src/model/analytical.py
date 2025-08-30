import numpy as np
import pandas as pd
from typing import List
# import os
# from pydasa import Queue
from src.model.queueing import Queue
# import random
# import simpy


# -----------------------------
# Analytical Solver (Jackson)
# -----------------------------


def solve_jackson_network(miu: List[float],
                          lambda_zero: List[float],
                          n_servers: List[int],
                          kap: List[int],
                          P: np.ndarray) -> List[pd.DataFrame]:
    """*solve_jackson_network()* solves the open Jackson network using traffic equations.

    Args:
        miu (List[float]): Service rates for each node.
        lambda_zero (List[float]): Arrival rates for each node.
        n_servers (List[int]): Number of servers for each node.
        kap (List[int]): Capacity limits for each node.
        P (np.ndarray): State transition probability matrix.

    Raise:
        ValueError: If the system is unstable (ρ >= 1 at some node).

    Returns:
        List[pd.DataFrame]: A list containing two DataFrames, one with the node results and other with the network metrics.
    """
    # creating identity matrix
    Is = np.eye(len(miu))
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
    for la, m, n, k in zip(lambdas, miu, n_servers, kap):
        # creating Queue instance for each node
        q = Queue(la, m, n, k)
        # calculating metrics for the queue
        q.calculate_metrics()
        # append metric results
        rho.append(q.rho)
        L.append(q.avg_len)
        Lq.append(q.avg_len_q)
        W.append(q.avg_wait)
        Wq.append(q.avg_wait_q)

    # Format rho values for console output
    if any(r >= 1.0 for r in rho):
        aprox_rho = [f"{r:.4f}" for r in rho]
        _msg = f"Warning!, unestable system!, calculated rho (ρ): {aprox_rho}"
        raise ValueError(_msg)

    # Calculate network-wide metrics
    net_metrics = calculate_net_metrics(lambdas, L, Lq, W, Wq, rho, miu)
    # Create DataFrame for node-specific metrics
    node_metrics = pd.DataFrame({
        "node": range(1, len(lambdas) + 1),
        "lambda": lambdas,
        "miu": miu,
        "rho": rho,
        "L": L,
        "Lq": Lq,
        "W": W,
        "Wq": Wq
    })

    # Return individual node metrics
    return node_metrics, net_metrics


def calculate_net_metrics(lambdas: List[float],
                          L: List[float],
                          Lq: List[float],
                          W: List[float],
                          Wq: List[float],
                          rho: List[float] = None,
                          miu: List[float] = None) -> pd.DataFrame:
    """*calculate_net_metrics()* calculates network-wide performance metrics for a Jackson network.

    Args:
        lambdas (List[float]): Arrival rates at each node.
        L (List[float]): Average number of jobs in the system at each node.
        Lq (List[float]): Average number of jobs waiting in queues at each node.
        W (List[float]): Average time a job spends in the system at each node.
        Wq (List[float]): Average time a job spends waiting in queues at each node.
        rho (List[float], optional): Utilization at each node. Defaults to None.
        miu (List[float], optional): Service rates for fallback calculations. Defaults to None.

    Returns:
        pd.DataFrame: DataFrame containing network-wide performance metrics.
    """
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
    avg_miu = np.mean(miu) if miu is not None and len(miu) > 0 else 0

    # Create DataFrame for network-wide metrics
    net_metrics = pd.DataFrame({
        "avg_miu": avg_miu,
        "avg_rho": avg_rho,
        "L_net": L_network,
        "Lq_net": Lq_network,
        "W_net": W_network,
        "Wq_net": Wq_network,
        "total_throughput": total_lambda
    })
    return net_metrics
