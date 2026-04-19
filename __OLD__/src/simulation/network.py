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
    """ **QueueNode** is a class representing a queueing node in the network with multiple servers and capacity limit.
    """
    def __init__(self,
                 env: simpy.Environment,
                 node_id: int,
                 mu: float,
                 s: int,
                 K: int,
                 P: float,
                 results: pd.DataFrame,
                 n_exp: int):
        """*__init__()* QueueNode constructor.

        Args:
            env (simpy.Environment): The simulation environment.
            node_id (int): The unique identifier for the node.
            mu (float): The service rate of the node.
            s (int): The number of servers at the node.
            K (int): The capacity of the node.
            P (float): The routing probability for the node.
            results (pd.DataFrame): The DataFrame to store results.
            n_exp (int): The number of events to simulate.
        """
        self.env = env
        self.node_id = node_id
        self.mu = mu    # Service rate per server
        self.s = s      # Number of servers
        self.K = K      # System capacity (queue + service)
        self.P = P
        self.results = results
        self.n_exp = n_exp

        # Use Resource with capacity equal to number of servers
        self.server = simpy.Resource(env, capacity=s)

        # Track when jobs are blocked due to capacity
        self.blocked_jobs = 0

        # Track times WITH collection timestamp for warm-up filtering
        self.coll_service_times = []  # (service_time, coll_time)
        self.coll_queue_times = []    # (queue_time, coll_time)
        self.coll_system_times = []   # (system_time, coll_time)

        # Original tracking for backward compatibility
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

        # Optional: Add job tracking for debugging
        self.job_log = []  # Track individual job processing

    def is_full(self) -> bool:
        """*is_full()* Check if the system is at capacity.

        Returns:
            bool: True if the system is full, False otherwise.
        """
        return (self.in_queue + self.in_service) >= self.K

    def record_state_change(self, env: simpy.Environment) -> None:
        """*record_state_change()* Record a state change in the system.

        Args:
            env (simpy.Environment): The simulation environment.
        """
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

    def service(self, job: str) -> simpy.events.Event:
        """*service()* Process a job at the node.

        Args:
            job (str): The job being processed.

        Returns:
            simpy.events.Event: The event representing the service process.

        Yields:
            Iterator[simpy.events.Event]: An iterator over the service process event.
        """
        service_time = random.expovariate(self.mu)
        coll_time = self.env.now

        # Store with timestamp for warm-up filtering
        self.coll_service_times.append((service_time, coll_time))
        self.service_times.append(service_time)

        self.job_log.append({
            "job_id": job,
            "node": self.node_id,
            "start_time": coll_time,
            "service_time": service_time,
            "end_time": coll_time + service_time
        })

        yield self.env.timeout(service_time)


def job_generator(env: simpy.Environment,
                  node_id: int,
                  rate: float,
                  nodes: list,
                  P: np.ndarray,
                  results: dict,
                  n_exp: int) -> simpy.events.Event:
    """*job_generator()* Generate external arrivals to the network.

    Args:
        env (simpy.Environment): The simulation environment.
        node_id (int): The ID of the node generating jobs.
        rate (float): The arrival rate of jobs.
        nodes (list): The list of nodes in the network.
        P (np.ndarray): The transition probability matrix.
        results (dict): The dictionary to store results.
        n_exp (int): The number of events to simulate.

    Returns:
        simpy.events.Event: The event representing the job generation process.

    Yields:
        Iterator[simpy.events.Event]: An iterator over the job generation events.
    """

    while True:
        interarrival = random.expovariate(rate)
        yield env.timeout(interarrival)
        env.process(job(env, node_id, nodes, P, results, n_exp))


def job(env: simpy.Environment,
        node_id: int,
        nodes: list,
        P: np.ndarray,
        results: dict,
        n_exp: int) -> simpy.events.Event:
    """*job()* Process a job in the network.

    Args:
        env (simpy.Environment): The simulation environment.
        node_id (int): The ID of the node processing the job.
        nodes (list): The list of nodes in the network.
        P (np.ndarray): The transition probability matrix.
        results (dict): The dictionary to store results.
        n_exp (int): The number of events to simulate.

    Returns:
        simpy.events.Event: The event representing the job processing.

    Yields:
        Iterator[simpy.events.Event]: An iterator over the job processing events.
    """
    # Generate unique job ID
    job_id = f"job_{env.now:.4f}_{node_id}"
    current = node_id

    while True:
        node = nodes[current]
        arrival_time = env.now

        # Check if we've reached the experiment limit
        if all(len(node.system_times) for node in nodes) >= n_exp:
            break  # Stop processing if enough jobs served

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
            coll_time = env.now

            # Store with timestamp for warm-up filtering
            node.coll_queue_times.append((queue_time, coll_time))
            node.queue_times.append(queue_time)

            node.in_queue -= 1
            node.in_service += 1  # Track actual number of jobs in service
            # Record state change at service start
            node.record_state_change(env)

            # Service process - now passing unique job_id
            yield env.process(node.service(job_id))

            # Calculate total time in system
            total_time = env.now - arrival_time
            coll_time = env.now

            # Store with timestamp for warm-up filtering
            node.coll_system_times.append((total_time, coll_time))
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
            # Update job_id to track routing
            job_id = f"{job_id}_to_{next_node}"


def simulate_network(mu: np.ndarray,
                     lambda_zero: np.ndarray,
                     s: np.ndarray,
                     K: np.ndarray,
                     P: np.ndarray,
                     n_exp: int = 5000,
                     warm_exp: int = 1000,
                     reps: int = 10,
                     verbose: bool = False) -> tuple:
    """*simulate_network()* Simulate open queueing network using SimPy with warm-up and repetitions.

    Args:
        mu (np.ndarray): Service rates for each node.
        lambda_zero (np.ndarray): External arrival rates for each node.
        s (np.ndarray, optional): Number of servers for each node.
        K (np.ndarray, optional): System capacity for each node.
        P (np.ndarray): Routing probability matrix.
        n_exp (int, optional): Total simulation duration (including warm-up). Defaults to 5000.
        warm_exp (int, optional): Warm-up period duration (data collected after this time). Defaults to 1000.
        reps (int, optional): Number of independent replications to run. Defaults to 10.
        verbose (bool, optional): If True, print detailed information. Defaults to False.

    Returns:
        tuple: (df_all_reps, df_summary)
            - df_all_reps: DataFrame with metrics from all replications
            - df_summary: DataFrame with aggregated statistics (mean, std) across replications
    """

    # Set default values if not provided
    if s is None:
        s = [1] * len(mu)
    if K is None:
        K = [float("inf")] * len(mu)

    # Store results from all replications
    all_reps_metrics = []

    for rep in range(reps):
        if verbose:
            print(f"--- Running Replication {rep + 1}/{reps} ---")

        env = simpy.Environment()
        results = [[] for _ in range(len(mu))]

        # Create nodes with multiple servers and capacity limits
        nodes = []
        for i in range(len(mu)):
            node = QueueNode(env, i, mu[i], s[i], K[i], P, results, n_exp)
            nodes.append(node)

        # Initialize state recording for each node
        for node in nodes:
            node.record_state_change(env)

        # Start external arrivals
        for i, rate in enumerate(lambda_zero):
            if rate > 0:
                env.process(job_generator(env,
                                          i,
                                          rate,
                                          nodes,
                                          P,
                                          results,
                                          n_exp))

        # Run simulation until completion
        env.run(until=n_exp)

        # Final state recording for accurate time-weighted statistics
        for node in nodes:
            # Record the final state duration
            time_delta = n_exp - node.last_event_time
            if time_delta > 0:
                node.queue_len_data.append((node.current_queue_length,
                                            time_delta))
                node.system_len_data.append((node.current_system_length,
                                             time_delta))

        # Calculate metrics for each node (only using data after warm-up)
        sim_metrics = []
        for i, node in enumerate(nodes):
            # Filter data to only include post-warm-up period
            # For queue and system length data: filter by last_event_time
            warm_queue_data = []
            warm_system_data = []

            cumulative_time = 0
            for length, time_delta in node.queue_len_data:
                event_time = cumulative_time + time_delta
                if cumulative_time >= warm_exp:
                    # Event occurred after warm-up
                    warm_queue_data.append((length, time_delta))
                elif event_time > warm_exp:
                    # Event spans warm-up boundary - only count portion after warm-up
                    time_after_warmup = event_time - warm_exp
                    warm_queue_data.append((length, time_after_warmup))
                cumulative_time = event_time

            cumulative_time = 0
            for length, time_delta in node.system_len_data:
                event_time = cumulative_time + time_delta
                if cumulative_time >= warm_exp:
                    warm_system_data.append((length, time_delta))
                elif event_time > warm_exp:
                    time_after_warmup = event_time - warm_exp
                    warm_system_data.append((length, time_after_warmup))
                cumulative_time = event_time

            # For service, queue, and system times - filter by collection time
            ncst = node.coll_service_times
            warm_service_times = [t for t, time in ncst if time >= warm_exp]
            ncqt = node.coll_queue_times
            warm_queue_times = [t for t, time in ncqt if time >= warm_exp]
            ncst = node.coll_system_times
            warm_system_times = [t for t, time in ncst if time >= warm_exp]
            jobs_served = len(warm_system_times)

            # Count blocked jobs during warm-up period (approximation)
            total_blocked = node.blocked_jobs
            # We assume blocking rate is roughly constant
            blocking_ratio = (n_exp - warm_exp) / n_exp if n_exp > 0 else 0
            blocked_after_warmup = int(total_blocked * blocking_ratio)

            total_arrivals = jobs_served + blocked_after_warmup

            # Determine queue model type
            if node.s == 1:
                model_type = "M/M/1" if node.K == float("inf") else f"M/M/1/{node.K}"
            else:
                model_type = f"M/M/{node.s}" if node.K == float("inf") else f"M/M/{node.s}/{node.K}"

            # Calculate time-average L and Lq (only post-warm-up)
            coll_duration = n_exp - warm_exp
            total_time = sum(time for _, time in warm_system_data) or coll_duration
            L_sim = sum(length * time for length, time in warm_system_data) / total_time if warm_system_data else 0

            total_q_time = sum(time for _, time in warm_queue_data) or coll_duration
            Lq_sim = sum(length * time for length, time in warm_queue_data) / total_q_time if warm_queue_data else 0

            # Calculate W and Wq from filtered times
            W_sim = np.mean(warm_system_times) if warm_system_times else 0
            Wq_sim = np.mean(warm_queue_times) if warm_queue_times else 0

            # Calculate lambda and rho
            lambda_sim = jobs_served / coll_duration if coll_duration > 0 else 0
            avg_service_time = np.mean(warm_service_times) if warm_service_times else (1 / mu[i])
            service_rate_sim = 1 / avg_service_time if avg_service_time > 0 else mu[i]
            rho_sim = min(1.0, lambda_sim / (node.s * service_rate_sim)) if service_rate_sim > 0 else 0

            # Validate with Little's Law
            L_from_littles = lambda_sim * W_sim
            Lq_from_littles = lambda_sim * Wq_sim

            # Calculate blocking probability
            blocking_prob = blocked_after_warmup / total_arrivals if total_arrivals > 0 else 0

            sim_metrics.append({
                "replication": rep + 1,
                "node": i,
                "type": model_type,
                "lambda": lambda_sim,
                "mu": service_rate_sim,
                "rho": rho_sim,
                "L": L_sim,
                "Lq": Lq_sim,
                "W": W_sim,
                "Wq": Wq_sim,
                "L_littles": L_from_littles,
                "Lq_littles": Lq_from_littles,
                "Jobs_Served": jobs_served,
                "Jobs_Blocked": blocked_after_warmup,
                "Blocking_Prob": blocking_prob,
            })

        all_reps_metrics.extend(sim_metrics)

    # TODO check this data stuff
    # Convert to DataFrame
    df_all = pd.DataFrame(all_reps_metrics)

    # Calculate aggregate statistics across replications
    df_summary = df_all.groupby("node").agg({
        "lambda": ["mean", "std"],
        "mu": ["mean", "std"],
        "rho": ["mean", "std"],
        "L": ["mean", "std"],
        "Lq": ["mean", "std"],
        "W": ["mean", "std"],
        "Wq": ["mean", "std"],
        "Jobs_Served": ["mean", "std"],
        "Jobs_Blocked": ["mean", "std"],
        "Blocking_Prob": ["mean", "std"]
    }).reset_index()

    # Flatten column names
    df_summary.columns = ["_".join(col).strip("_") for col in df_summary.columns.values]
    if verbose:
        print("\n=== Summary Statistics Across Replications ===")
        print(df_summary.shape)

    # return df_all, df_summary
    return df_summary


# df_summary = simulate_network(
#     mu=[2.0, 3.0, 1.5],
#     lambda_zero=[1.0, 0.5, 0.3],
#     P=[[0.0, 0.5, 0.3],
#       [0.0, 0.0, 0.0],
#       [0.0, 0.0, 0.0]],
#     s=[1, 2, 1],
#     K=[10, 20, 15],
#     n_exp=1000,      # Total simulation time
#     warm_exp=100,      # Discard first 100 time units
#     reps=10              # Run 10 independent replications
# )
