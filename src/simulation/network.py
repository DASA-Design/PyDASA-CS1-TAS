import numpy as np
import pandas as pd
# import os
# from pydasa import Queue
import random
import simpy

# -----------------------------
# Simulation with SimPy
# -----------------------------


class QueueNode:
    def __init__(self, env, node_id, miu, s, K, P, results, sim_time):
        self.env = env
        self.node_id = node_id
        self.miu = miu  # Service rate per server
        self.s = s      # Number of servers
        self.K = K      # System capacity (queue + service)
        self.P = P
        self.results = results
        self.sim_time = sim_time

        # Use Resource with capacity equal to number of servers
        self.server = simpy.Resource(env, capacity=s)

        # Track when jobs are blocked due to capacity
        self.blocked_jobs = 0

        # For tracking queue and system metrics
        self.service_times = []  # Track service times
        self.queue_times = []    # Time spent only in queue
        self.system_times = []   # Total time in system (queue + service)

        # For time-weighted L and Lq calculation (event-driven)
        self.queue_len_data = []     # (length, time_delta) pairs
        self.system_len_data = []    # (length, time_delta) pairs
        self.last_event_time = 0
        self.in_queue = 0
        self.in_service = 0
        self.current_queue_length = 0
        self.current_system_length = 0

    def is_full(self):
        """Check if the system is at capacity"""
        return (self.in_queue + self.in_service) >= self.K

    def record_state_change(self, env):
        """Record a state change in the system"""
        current_time = env.now
        time_delta = current_time - self.last_event_time

        if time_delta > 0:
            # Record the previous state duration
            self.queue_len_data.append((self.current_queue_length, time_delta))
            self.system_len_data.append(
                (self.current_system_length, time_delta))

        # Update current state
        self.current_queue_length = self.in_queue
        self.current_system_length = self.in_queue + self.in_service
        self.last_event_time = current_time

    def service(self, job):
        service_time = random.expovariate(self.miu)
        self.service_times.append(service_time)
        yield self.env.timeout(service_time)


def job_generator(env, node_id, rate, nodes, P, results, sim_time):
    """Generate external arrivals"""
    while True:
        interarrival = random.expovariate(rate)
        yield env.timeout(interarrival)
        env.process(job(env, node_id, nodes, P, results, sim_time))


def job(env, node_id, nodes, P, results, sim_time):
    current = node_id
    while True:
        node = nodes[current]
        arrival_time = env.now

        # Check if the system is at capacity (M/M/*/K model)
        if node.is_full():
            # Job is blocked/lost due to capacity constraint
            node.blocked_jobs += 1
            break  # Job leaves the network

        # Update queue length when job arrives
        node.in_queue += 1
        node.record_state_change(env)  # Record state change at arrival

        with node.server.request() as req:
            # Time when request is made
            queue_start = env.now

            # Wait until server is available
            yield req

            # Update queue length and track queue waiting time
            queue_time = env.now - queue_start
            node.queue_times.append(queue_time)
            node.in_queue -= 1
            node.in_service += 1  # Track actual number of jobs in service
            # Record state change at service start
            node.record_state_change(env)

            # Service process
            yield env.process(node.service("job"))

            # Calculate total time in system
            total_time = env.now - arrival_time
            node.system_times.append(total_time)
            results[current].append(total_time)

            # Update system metrics
            node.in_service -= 1  # One job less in service
            node.record_state_change(env)  # Record state change at departure

        # routing decision
        exit_prob = 1 - np.sum(P[current])
        if random.random() < exit_prob:
            break  # leave system
        else:
            # Normalize the probabilities to ensure they sum to 1
            probs = P[current] / np.sum(P[current])
            next_node = np.random.choice(range(len(P)), p=probs)
            current = next_node


def simulate_network(miu, lambda0, P, s=None, K=None, sim_time=5000):
    """
    Simulate open queueing network using SimPy

    Parameters:
    -----------
    miu : array-like
        Service rates for each node
    lambda0 : array-like
        External arrival rates for each node
    P : array-like
        Routing probability matrix
    s : array-like, optional
        Number of servers for each node (default=1 for all nodes)
    K : array-like, optional
        System capacity for each node (default=inf for all nodes)
    sim_time : float
        Simulation duration
    """
    # Set default values if not provided
    if s is None:
        s = [1] * len(miu)
    if K is None:
        K = [float('inf')] * len(miu)

    env = simpy.Environment()
    results = [[] for _ in range(len(miu))]

    # Create nodes with multiple servers and capacity limits
    nodes = []
    for i in range(len(miu)):
        node = QueueNode(env, i, miu[i], s[i], K[i], P, results, sim_time)
        nodes.append(node)

    # Initialize state recording for each node
    for node in nodes:
        node.record_state_change(env)

    # start external arrivals
    for i, rate in enumerate(lambda0):
        if rate > 0:
            env.process(job_generator(env,
                                      i,
                                      rate,
                                      nodes,
                                      P,
                                      results,
                                      sim_time))

    env.run(until=sim_time)

    # Final state recording for accurate time-weighted statistics
    for node in nodes:
        # Record the final state duration
        time_delta = sim_time - node.last_event_time
        if time_delta > 0:
            node.queue_len_data.append((node.current_queue_length, time_delta))
            node.system_len_data.append(
                (node.current_system_length, time_delta))

    # Calculate metrics for each node
    sim_metrics = []
    for i, node in enumerate(nodes):
        # Number of jobs served and blocked
        jobs_served = len(node.system_times)
        total_arrivals = jobs_served + node.blocked_jobs

        # Determine queue model type
        if node.s == 1:
            if node.K == float('inf'):
                model_type = "M/M/1"
            else:
                model_type = f"M/M/1/{node.K}"
        else:
            if node.K == float('inf'):
                model_type = f"M/M/{node.s}"
            else:
                model_type = f"M/M/{node.s}/{node.K}"

        # Print raw data for debugging
        print(f"Node {i} queue length data points: {len(node.queue_len_data)}")
        # Format sample data to 4 decimal places
        formatted_data = []
        for length, time_val in node.queue_len_data[:5]:
            if isinstance(time_val, (float, np.number)):
                formatted_data.append((length, float(time_val)))
            else:
                formatted_data.append((length, time_val))
        print(f"Sample queue length data: {formatted_data}")

        # Calculate time-average L (system length)
        total_time = sum(time for _, time in node.system_len_data) or sim_time
        L_sim = sum(length * time for length, time in node.system_len_data) / \
            total_time if node.system_len_data else 0

        # Calculate time-average Lq (queue length)
        total_q_time = sum(time for _, time in node.queue_len_data) or sim_time
        Lq_sim = sum(length * time for length, time in node.queue_len_data) / \
            total_q_time if node.queue_len_data else 0

        # Calculate W (time in system) and Wq (time in queue)
        W_sim = np.mean(node.system_times) if node.system_times else 0
        Wq_sim = np.mean(node.queue_times) if node.queue_times else 0

        # Calculate lambda (arrival rate) and rho (utilization)
        lambda_sim = jobs_served / sim_time

        # Calculate actual average service rate from the service times
        avg_service_time = np.mean(node.service_times) if node.service_times else 1 / miu[i]

        # Calculated average service rate
        service_rate_sim = 1 / avg_service_time if avg_service_time > 0 else miu[i]

        # For multi-server queues, utilization is per server
        rho_sim = min(1.0, lambda_sim / (node.s * service_rate_sim))

        # Validate with Little's Law
        L_from_littles = lambda_sim * W_sim
        Lq_from_littles = lambda_sim * Wq_sim

        # Calculate blocking probability for finite capacity queues
        blocking_prob = node.blocked_jobs / total_arrivals if total_arrivals > 0 else 0

        sim_metrics.append({
            "node": i,
            "type": model_type,
            "lambda": lambda_sim,
            "miu": service_rate_sim,
            "rho": rho_sim,
            "L": L_sim,
            "Lq": Lq_sim,
            "W": W_sim,
            "Wq": Wq_sim,
            "L_littles": L_from_littles,
            "Lq_littles": Lq_from_littles,
            "Jobs_Served": jobs_served,
            "Jobs_Blocked": node.blocked_jobs,
            "Blocking_Prob": blocking_prob,
        })

    return pd.DataFrame(sim_metrics)
