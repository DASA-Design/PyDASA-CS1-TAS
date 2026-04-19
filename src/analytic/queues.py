# -*- coding: utf-8 -*-
"""
Module queues.py
================

Closed-form queue models used by the analytic method for the TAS case
study with field names renamed to the PyDASA acronym convention:

    -`lamb`: (arrival rate lambda; avoids Python's keyword)
    -`c_max`: (number of servers c)
    -`K_max`: (system capacity K, None means infinite)

*IMPORTANT:* Formulas from standard queueing theory:

    - Kleinrock, L. (1975), *Queueing Systems, Vol. 1: Theory*.
    - Gross, D. et al. (2008), *Fundamentals of Queueing Theory*, 4th ed.

# TODO: Implement additional queue models (M/G/1, G/G/1, priority queues).
"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations
from dataclasses import dataclass, field

# data types
from typing import Any, Dict, Optional

# indicate it is an abstract base class
from abc import ABC, abstractmethod

# shared math helpers
from src.utils.mathx import gfactorial


@dataclass
class BasicQueue(ABC):
    """**BasicQueue** is an abstract base class for queueing theory models.

    Attributes:
        Input parameters:
            lamb (float): Arrival rate (lambda).
            mu (float): Service rate (mu).
            c_max (int): Number of servers (c).
            K_max (Optional[int]): Maximum capacity (K), None for unbounded.

        Output parameters:
            rho (float): Server utilization (rho).
            tau (float): Traffic intensity (tau).
            p_z (float): Probability of zero requests in the system (P(0)).
            p_n (float): Probability of n requests in the system (P(n)).
            avg_len (float): L, or mean number of requests in the system.
            avg_len_q (float): Lq, or mean number of requests in queue.
            avg_wait (float): W, or mean time a request spends in the system.
            avg_wait_q (float): Wq, or mean waiting time in queue.
            lamb_eff (float): Effective arrival rate (lamb_eff).
    """

    # :attr: lamb
    lamb: float = -1.0
    """Arrival rate (lambda)."""

    # :attr: mu
    mu: float = -1.0
    """Service rate (mu)."""

    # :attr: c_max
    c_max: int = 1
    """Number of servers (c)."""

    # :attr: K_max
    K_max: Optional[int] = None
    """Maximum capacity (K), None for unbounded."""

    # :attr: rho
    rho: float = field(default=0.0, init=False)
    """Server utilization (rho)."""

    # :attr: tau
    tau: float = field(default=0.0, init=False)
    """Server traffic intensity (tau)."""

    # :attr: p_z
    p_z: float = field(default=0.0, init=False)
    """Probability of having 0 requests in the system (P(0))."""

    # :attr: p_n
    p_n: float = field(default=0.0, init=False)
    """Probability of having n requests in the system (P(n))."""

    # :attr: avg_len
    avg_len: float = field(default=0.0, init=False)
    """Average length of elements in the system (L: mean number of requests in the system with the Little's Law)."""

    # :attr: avg_len_q
    avg_len_q: float = field(default=0.0, init=False)
    """Average length of elements in the queue (Lq: mean number of requests in queue with the Little's Law)."""

    # :attr: avg_wait
    avg_wait: float = field(default=0.0, init=False)
    """Average time a request spends in the system (W: mean time in system with the Little's Law)."""

    # :attr: avg_wait_q
    avg_wait_q: float = field(default=0.0, init=False)
    """Average time a request spends waiting in the queue (Wq: mean waiting time in queue with the Little's Law)."""

    # :attr: lamb_eff
    lamb_eff: float = field(default=0.0, init=False)
    """Effective arrival rate (lamb_eff = lamb * (1 - P(K))) for finite-K models."""

    def __post_init__(self):
        """*__post_init__()* Post-initialization processing to coerce numeric
        types and run both basic and model-specific parameter validation.

        Raises:
            ValueError: If any input parameter violates the common or the model-specific constraints.
        """
        # Ensure c_max and K_max are integers (when K_max is bounded)
        self.c_max = int(self.c_max)
        if self.K_max is not None:
            self.K_max = int(self.K_max)

        # run validation hooks (common first, then model-specific)
        self._validate_basic_params()
        self._validate_params()

    def _validate_basic_params(self) -> None:
        """*_validate_basic_params()* Validates basic parameters common to all queueing models.

        Raises:
            ValueError: If arrival rate is negative.
            ValueError: If service rate is non-positive.
            ValueError: If number of servers is non-positive.
        """
        if self.lamb < 0:
            raise ValueError("Arrival rate must be non-negative.")
        if self.mu <= 0:
            raise ValueError("Service rate must be positive.")
        if self.c_max < 1:
            raise ValueError("Number of servers must be positive.")

    @abstractmethod
    def _validate_params(self) -> None:
        """*_validate_params()* Validates parameters specific to each queueing model.

        Raises:
            ValueError: If the concrete model's invariants are violated.
        """
        pass

    @abstractmethod
    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates analytical metrics for the queueing model and writes them in place on the instance.

        Side effects: Sets `rho`, `tau`, `p_z`, `avg_len`, `avg_len_q`, `avg_wait`, `avg_wait_q`, and (for finite-K models) `lamb_eff`.
        """
        pass

    @abstractmethod
    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) or the probability of having 0 requests in the system.

        Returns:
            float: Probability of having 0 requests in the system.
        """
        pass

    @abstractmethod
    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n), or the probability of having n requests in the system.

        Args:
            n (int): Number of requests in the system.

        Returns:
            float: Probability of having n requests in the system.
        """
        pass

    @abstractmethod
    def is_stable(self) -> bool:
        """*is_stable()* Checks whether the queueing system admits a steady-state solution.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        pass

    def get_metrics(self) -> Dict[str, Any]:
        """*get_metrics()* Returns a summary of the queueing system's computed performance metrics.

        Returns:
            Dict[str, Any]: A dictionary containing the calculated metrics with the following keys:

                - 'L': Average number of requests inside the system.
                - 'Lq': Average number of requests in queue.
                - 'W': Average request time in the system.
                - 'Wq': Average request time in queue.
                - 'rho': Server utilization.
        """
        return {
            "L": self.avg_len,
            "Lq": self.avg_len_q,
            "W": self.avg_wait,
            "Wq": self.avg_wait_q,
            "rho": self.rho,
        }

    def __str__(self) -> str:
        """*__str__()* String representation of the queue model.

        Returns:
            str: Formatted string with queue model details and metrics.
        """
        # Create header with class name
        output = [f"{self.__class__.__name__}("]

        # Add basic parameters
        params = [
            f"\tlamb={self.lamb}",
            f"\tmu={self.mu}",
            f"\tc_max={self.c_max}"
        ]
        output.extend(params)
        if self.K_max is not None:
            output.append(f"\tK_max={self.K_max}")

        # Add stability status
        status = f"\tStatus: {'STABLE' if self.is_stable() else 'UNSTABLE'}"
        output.append(status)

        # Add metrics with formatting
        metrics = self.get_metrics()
        for key, value in metrics.items():
            if isinstance(value, float):
                output.append(f"\t{key}={value:.6f}")
            else:
                output.append(f"\t{key}={value}")
        output.append(")")
        # Join all lines with newlines
        return ",\n".join(output)

    def __repr__(self) -> str:
        """*__repr__()* Detailed string representation.

        Returns:
            str: String representation of the queue instance.
        """
        return self.__str__()


@dataclass
class QueueMM1(BasicQueue):
    """**QueueMM1** represents an M/M/1 queue system (1 server, infinite capacity).

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is not 1.
        ValueError: If the capacity is not infinite.
        ValueError: If the system is unstable (lamb >= mu).

    Returns:
        QueueMM1: An instance of the M/M/1 queue model.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/1 queue.

        Raises:
            ValueError: If the number of servers is not 1.
            ValueError: If the capacity is not infinite.
            ValueError: If the system is unstable (lamb >= mu).
        """
        if self.c_max != 1:
            _msg = f"M/M/1 requires exactly 1 server. c={self.c_max}"
            raise ValueError(_msg)
        if self.K_max is not None:
            _msg = f"M/M/1 assumes infinite capacity. K={self.K_max}"
            raise ValueError(_msg)
        if not self.is_stable():
            _msg = "System is unstable (lamb >= mu). "
            _msg += f"lamb={self.lamb}, mu={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        return self.lamb / self.mu < 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/1 queue.

        The model metrics are:

            - rho: Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.

        Side effects:
            Sets `rho`, `tau`, `p_z`, `avg_len`, `avg_len_q`, `avg_wait`,
            `avg_wait_q` on the instance.
        """
        # Calculate utilization (rho)
        self.rho = self.lamb / self.mu

        # Calculate traffic intensity (tau)
        self.tau = self.lamb / self.mu

        # Calculate the probability of having 0 requests in the system
        self.p_z = self.calculate_prob_zero()

        # Calculate average number of requests in the system (L)
        self.avg_len = self.rho / (1 - self.rho)

        # Calculate average number of requests in the queue (Lq)
        self.avg_len_q = self.rho ** 2 / (1 - self.rho)

        # Calculate average time a request spends in the system (W)
        # Calculate average time a request spends in the queue (Wq)
        if self.lamb > 0:
            self.avg_wait = self.avg_len / self.lamb
            self.avg_wait_q = self.avg_len_q / self.lamb
        else:
            self.avg_wait = 0.0
            self.avg_wait_q = 0.0

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) for the M/M/1 model.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        p_z = 1.0 - self.rho
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n) for the M/M/1 model.

        Args:
            n (int): The number of requests in the system.

        Returns:
            float: The probability of having n requests in the system; `-1.0` when n is negative.
        """
        p_n = 0.0
        if n < 0:
            p_n = -1.0
        elif n >= 0:
            p_n = (1 - self.rho) * (self.rho ** n)
        self.p_n = p_n
        return p_n


@dataclass
class QueueMMs(BasicQueue):
    """**QueueMMs** represents an M/M/s queue system (multi-server, infinite capacity).

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is less than 1.
        ValueError: If the capacity is not infinite.
        ValueError: If the system is unstable (lamb >= c * mu).

    Returns:
        QueueMMs: An instance of the M/M/s queue model.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/s model.

        Raises:
            ValueError: If the number of servers is less than 1.
            ValueError: If the capacity is not infinite.
            ValueError: If the system is unstable (lamb >= c * mu).
        """
        if self.c_max < 1:
            _msg = f"M/M/s requires at least one server. c={self.c_max}"
            raise ValueError(_msg)
        if self.K_max is not None:
            _msg = f"M/M/s assumes infinite capacity. K={self.K_max}"
            raise ValueError(_msg)
        if not self.is_stable():
            _msg = "System is unstable (lamb >= c * mu). "
            _msg += f"lamb={self.lamb}, c={self.c_max}, mu={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        return self.lamb / (self.c_max * self.mu) < 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for
        the M/M/s queue using the Erlang C formulas.

        The model metrics are:

            - rho: Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.

        Side effects:
            Sets `rho`, `tau`, `p_z`, `avg_len`, `avg_len_q`, `avg_wait`, `avg_wait_q` on the instance.
        """
        # Calculate utilization (rho)
        self.rho = self.lamb / (self.c_max * self.mu)

        # Calculate traffic intensity (tau)
        self.tau = self.lamb / self.mu

        # Calculate the probability of having 0 requests in the system
        self.p_z = self.calculate_prob_zero()

        # Calculate the average number of requests in the queue (Lq)
        numerator = self.p_z * (self.tau ** self.c_max) * self.rho
        denominator = gfactorial(self.c_max) * ((1 - self.rho) ** 2)
        self.avg_len_q = numerator / denominator

        # Calculate the average number of requests in the system (L)
        self.avg_len = self.avg_len_q + self.tau

        # Calculate the average time spent in the queue (Wq)
        if self.lamb > 0:
            self.avg_wait_q = self.avg_len_q / self.lamb
        else:
            self.avg_wait_q = 0.0

        # Calculate the average time spent in the system (W)
        self.avg_wait = self.avg_wait_q + self.mu ** -1

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) for the M/M/s model via the Erlang C denominator.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # calculate probability of having up to c requests in the system
        p_under_c = sum((self.tau ** i) / gfactorial(i)
                        for i in range(self.c_max))

        # calculate probability of having more than c requests in the system
        numerator = (self.tau ** self.c_max)
        denominator = gfactorial(self.c_max) * (1 - self.rho)
        p_over_c = numerator / denominator

        # calculate the probability of having 0 requests in the system
        p_z = (p_under_c + p_over_c) ** -1
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n) for the M/M/s model.

        Args:
            n (int): The number of requests in the system.

        Returns:
            float: The probability of having n requests in the system;
                `-1.0` when n is negative.
        """
        # default value, for error checking
        p_n = -1.0

        # if request count is invalid
        if n < 0:
            self.p_n = p_n
            return p_n

        # calculate the probability of having n requests in the system
        numerator = self.tau ** n

        # if there are fewer requests than servers
        if n <= self.c_max:
            denominator = gfactorial(n)

        # otherwise, there are more requests than servers
        else:
            power = self.c_max ** (n - self.c_max)
            denominator = gfactorial(self.c_max) * power

        # finishing up calculations
        p_n = (numerator / denominator) * self.p_z
        self.p_n = p_n
        return p_n


@dataclass
class QueueMM1K(BasicQueue):
    """**QueueMM1K** represents an M/M/1/K queue system with finite capacity K and one server.

    Narrows the base class's `K_max: Optional[int]` to a plain `int` so that downstream math does not need null-guards.

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is not 1.
        ValueError: If the capacity is not positive.

    Returns:
        QueueMM1K: An instance of the M/M/1/K queue model.
    """

    # :attr: K_max
    K_max: int = 0  # type: ignore[assignment]
    """Maximum capacity (K), narrowed from Optional[int] to int."""

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/1/K model.

        Raises:
            ValueError: If the number of servers is not 1.
            ValueError: If the capacity is not positive.
        """
        if self.c_max != 1:
            _msg = f"M/M/1/K requires exactly 1 server. c={self.c_max}"
            raise ValueError(_msg)
        if self.K_max < 1:
            _msg = "M/M/1/K requires a positive finite capacity. "
            _msg += f"K={self.K_max}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True; finite-K queues always admit a steady state.
        """
        return True

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/1/K queue, handling both rho<1 and rho=1 regimes.

        The model metrics are:

            - rho: Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.

        Side effects:
            Sets `rho`, `tau`, `lamb_eff`, `avg_len`, `avg_len_q`, `avg_wait`, `avg_wait_q` on the instance.
        """
        # Calculate utilization (rho)
        self.rho = self.lamb / self.mu

        # Calculate traffic intensity (tau)
        self.tau = self.lamb / self.mu

        # Calculate the probability of being at max capacity
        p_kmax = self.calculate_prob_n(self.K_max)

        # Calculate the effective arrival rate (lamb_eff)
        self.lamb_eff = self.lamb * (1 - p_kmax)

        # if utilization (rho) is less than 1
        if self.rho < 1.0:
            # Calculate requests in the server
            in_server = self.rho / (1 - self.rho)

            # Calculate the queue excess from finite truncation
            numerator = (self.K_max + 1) * self.rho ** (self.K_max + 1)
            denominator = (1 - self.rho ** (self.K_max + 1))
            in_queue = numerator / denominator

            # Calculate average number of requests in the system (L)
            self.avg_len = in_server - in_queue

            # Calculate average number of requests in the queue (Lq)
            # equivalent to: self.avg_len_q = self.avg_len - self.rho * (1 - p_kmax)
            self.avg_len_q = self.avg_len - self.lamb_eff / self.mu

        # if utilization (rho) is equal to 1, saturation occurs
        else:
            # Calculate average number of requests in the system (L)
            self.avg_len = self.K_max / 2.0

            # Calculate average number of requests in the queue (Lq)
            numerator = self.K_max * (self.K_max - 1)
            denominator = 2 * self.K_max + 1
            self.avg_len_q = numerator / denominator

        # Calculate average time spent in the system (W)
        # Calculate average time spent in the queue (Wq)
        if self.lamb_eff > 0:
            self.avg_wait = self.avg_len / self.lamb_eff
            self.avg_wait_q = self.avg_len_q / self.lamb_eff

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) for the M/M/1/K model, handling both rho<1 and rho=1 regimes.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # if utilization (rho) is equal to 1, saturation occurs
        if self.rho == 1.0:
            p_z = 1.0 / (self.K_max + 1)
            return p_z

        # otherwise, geometric sum
        numerator = 1 - self.rho
        denominator = 1 - self.rho ** (self.K_max + 1)
        p_z = numerator / denominator
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n) for the M/M/1/K model.

        Args:
            n (int): The number of requests.

        Returns:
            float: The probability of having n requests in the system.
        """
        # if utilization (rho) is equal to 1, saturation occurs
        if self.rho == 1.0:
            p_n = 1.0 / (self.K_max + 1)
        # otherwise, geometric distribution truncated to K_max
        else:
            numerator = (1 - self.rho) * (self.rho ** n)
            denominator = (1 - self.rho ** (self.K_max + 1))
            p_n = numerator / denominator

        self.p_n = p_n
        return p_n


@dataclass
class QueueMMsK(BasicQueue):
    """**QueueMMsK** represents an M/M/c/K queue system (finite capacity K, c servers).

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing
            theory models.

    Raises:
        ValueError: If the number of servers is less than 1.
        ValueError: If the capacity is less than the number of servers.

    Returns:
        QueueMMsK: An instance of the M/M/c/K queueing system.
    """

    # :attr: K_max
    K_max: int = 0  # type: ignore[assignment]
    """Maximum capacity (K), narrowed from Optional[int] to int."""

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/c/K model.

        Raises:
            ValueError: If the number of servers is less than 1.
            ValueError: If the capacity is less than the number of servers.
        """
        if self.c_max < 1:
            _msg = f"M/M/c/K requires at least one server. c={self.c_max}"
            raise ValueError(_msg)
        if self.K_max < self.c_max:
            _msg = "M/M/c/K requires capacity K >= c. "
            _msg += f"K={self.K_max}, c={self.c_max}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the M/M/c/K queueing system is stable.

        Returns:
            bool: True; finite-K queues always admit a steady state.
        """
        return True

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/c/K queue via truncated state sums.

        The model metrics are:

            - rho: Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.

        Side effects:
            Sets `rho`, `tau`, `p_z`, `lamb_eff`, `avg_len`, `avg_len_q`, `avg_wait`, `avg_wait_q` on the instance.
        """
        # calculate the server utilization (rho)
        self.rho = self.lamb / (self.c_max * self.mu)

        # calculate the traffic intensity (tau)
        self.tau = self.lamb / self.mu

        # calculate probability of zero requests in the system
        self.p_z = self.calculate_prob_zero()

        # calculate the probability of being at full capacity
        p_kmax = self.calculate_prob_n(self.K_max)

        # Calculate effective arrival rate (lamb_eff)
        self.lamb_eff = self.lamb * (1 - p_kmax)

        # calculate the average number of requests in the system (L)
        K = self.K_max
        L = sum([i * self.calculate_prob_n(i) for i in range(K + 1)])
        self.avg_len = L

        # Calculate average number of requests in the queue (Lq)
        c = self.c_max
        Lq = sum([(i - c) * self.calculate_prob_n(i)
                  for i in range(c, K + 1)])
        self.avg_len_q = Lq

        # calculate the average time a request spends in the system (W)
        # calculate the average time a request spends in the queue (Wq)
        if self.lamb_eff > 0:
            self.avg_wait = self.avg_len / self.lamb_eff
            self.avg_wait_q = self.avg_len_q / self.lamb_eff

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) for the M/M/c/K model from the truncated denominator.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # local shortcuts for the closed-form expressions
        tau = self.tau
        c = self.c_max
        K = self.K_max

        # partial sum under capacity (states 0..c-1)
        sum_under_c = sum((tau ** i) / gfactorial(i) for i in range(c))

        # partial sum over capacity (states c..K)
        sum_over_c = sum((tau ** i) / (gfactorial(c) * (c ** (i - c)))
                         for i in range(c, K + 1))

        # calculate the probability of having 0 requests in the system
        p_z = (sum_under_c + sum_over_c) ** -1
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n) for the M/M/c/K model.

        Args:
            n (int): The number of requests.

        Returns:
            float: The probability of having n requests in the system; `0.0` when `n` falls outside `[0, K_max]`.
        """
        # if request count is out of valid range
        if n < 0 or n > self.K_max:
            return 0.0

        # Calculate the probability of having n requests in the system
        numerator = self.tau ** n

        # if request count is less than number of servers
        if n < self.c_max:
            denominator = gfactorial(n)
        # otherwise, request count between servers and capacity
        else:
            power = self.c_max ** (n - self.c_max)
            denominator = gfactorial(self.c_max) * power

        p_n = (numerator / denominator) * self.p_z
        self.p_n = p_n
        return p_n


# registry of supported queue models.
# maps the canonical model string to a shape spec:
#
#     class   (type[BasicQueue]): concrete implementation class.
#     c_rule  (str):              "single" means c_max must be exactly 1;
#                                 "multi"  means c_max must be >= 1.
#     K_rule  (str):              "infinite" means K_max must be None;
#                                 "finite"   means K_max must be set.
#
# M/M/s/K is kept as an alias for M/M/c/K (same class, same rules).
# Adding a new model = adding a new entry here (plus its class above).
_QUEUE_MODELS: Dict[str, Dict[str, Any]] = {
    "M/M/1": {
        "class": QueueMM1,
        "c_rule": "single",
        "K_rule": "infinite",
    },
    "M/M/s": {
        "class": QueueMMs,
        "c_rule": "multi",
        "K_rule": "infinite",
    },
    "M/M/1/K": {
        "class": QueueMM1K,
        "c_rule": "single",
        "K_rule": "finite",
    },
    "M/M/c/K": {
        "class": QueueMMsK,
        "c_rule": "multi",
        "K_rule": "finite",
    },
    # alias for M/M/c/K
    "M/M/s/K": {
        "class": QueueMMsK,
        "c_rule": "multi",
        "K_rule": "finite",
    },
}


def Queue(model: str,
          lamb: float,
          mu: float,
          c_max: int = 1,
          K_max: Optional[int] = None) -> BasicQueue:
    """*Queue()* factory function to create different queue models.

    NOTE: parameter names follow the PyDASA acronym convention
    (`lamb` for lambda, `c_max` for server count, `K_max` for capacity).

    Args:
        model (str): Type of queue model to create. Options: 'M/M/1', 'M/M/s', 'M/M/1/K', 'M/M/c/K', plus 'M/M/s/K' as an alias for the M/M/c/K class.
        lamb (float): Arrival rate ($\\lambda$) of the queue.
        mu (float): Service rate ($\\mu$) of the queue.
        c_max (int, optional): Number of servers ($c$). Defaults to 1.
        K_max (Optional[int], optional): Maximum system capacity ($K$). Defaults to None (infinite).

    Raises:
        NotImplementedError: If the queue configuration is not supported.
        ValueError: If the requested model's parameter combination is invalid (e.g. M/M/1 with finite K, or M/M/c/K with K < c).

    Returns:
        BasicQueue: An instance of a specific queue model (based on the
            abstract basic model).
    """
    # check for supported models against the registry
    if model not in _QUEUE_MODELS:
        _msg = f"Unsupported queue model: {model}. "
        _msg += f"Supported models: {list(_QUEUE_MODELS.keys())}"
        raise NotImplementedError(_msg)

    # look up the shape rules for this model
    _spec = _QUEUE_MODELS[model]
    _cls = _spec["class"]
    _c_rule = _spec["c_rule"]
    _K_rule = _spec["K_rule"]

    # validate server count (c_max) against the model's shape.
    # "single" requires exactly 1 server; "multi" requires at least 1.
    _c1 = (_c_rule == "single" and c_max == 1)
    _c2 = (_c_rule == "multi" and c_max >= 1)
    _c_ok = _c1 or _c2
    if not _c_ok:
        _msg = f"{model} requires {_c_rule}-server shape. "
        _msg += f"c={c_max}"
        raise ValueError(_msg)

    # validate system capacity (K_max) against the model's shape.
    # "infinite" requires K_max=None; "finite" requires K_max to be set.
    _c1 = (_K_rule == "infinite" and K_max is None)
    _c2 = (_K_rule == "finite" and K_max is not None)
    _K_ok = _c1 or _c2
    if not _K_ok:
        _msg = f"{model} requires {_K_rule} capacity. "
        _msg += f"K={K_max}"
        raise ValueError(_msg)

    # finite multi-server models additionally require K >= c
    if _K_rule == "finite" and _c_rule == "multi" and K_max < c_max:
        _msg = f"{model} requires capacity K >= c. "
        _msg += f"K={K_max}, c={c_max}"
        raise ValueError(_msg)

    # build the queue instance. Every concrete class accepts the full
    # (lamb, mu, c_max, K_max) shape through the inherited dataclass
    # fields; validation above guarantees the values match the model.
    _queue = _cls(lamb, mu, c_max, K_max)

    # TODO: Implement additional queue models (M/G/1, G/G/1, priority).

    return _queue
