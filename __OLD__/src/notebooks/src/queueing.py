# -*- coding: utf-8 -*-
"""
Configuration module for...

# FIXME: adjust documentation to match the actual implementation.
# TODO: Add description of the module.
# TODO: check Q-Model formula and consistency with the theory.

*IMPORTANT:* Based on the theory from:
    # TODO add proper references!!!

"""
# native python modules
# forward references + postpone eval type hints
from __future__ import annotations
from dataclasses import dataclass, field

# data types
from typing import Any, Dict, Optional, Union

# indicate it is an abstract base class
from abc import ABC, abstractmethod
import math

# infinite for numbers
INF = math.inf


def Queue(model: str,
          _lambda: float,
          mu: float,
          n_servers: int = 1,
          kapacity: Optional[int] = None) -> BasicQueue:
    """*Queue()* factory function to create different queue models.

    NOTE: some variable names start with underscore (_) to avoid conflict with Python keywords.

    Args:
        model (str): Type of queue model to create. Options: 'M/M/1', 'M/M/s', 'M/M/1/K', 'M/M/c/K'.
        _lambda (float): Arrival rate ($\\lambda$) of the queue.
        mu (float): Service rate ($\\mu$) of the queue.
        n_servers (int, optional): Number of servers ($c$). Defaults to 1.
        kapacity (Optional[int], optional): Maximum capacity ($K$) of the queue. Defaults to None.

    Raises:
        NotImplementedError: If the queue configuration is not supported.

    Returns:
        BasicQueue: An instance of a specific queue model (based on the abstract basic model).
    """
    _queue = None
    options = ["M/M/1", "M/M/s", "M/M/1/K", "M/M/c/K"]
    # check for supported models
    if model not in options:
        _msg = f"Unsupported queue model: {model}. "
        _msg += f"Supported models: {options}"
        raise NotImplementedError(_msg)

    # Single server, infinite capacity
    elif model == "M/M/1":
        if n_servers != 1 or kapacity is not None:
            _msg = "M/M/1 requires exactly 1 server and infinite capacity. "
            _msg += f"s={n_servers}, K={kapacity}"
            raise ValueError(_msg)
        _queue = QueueMM1(_lambda, mu)
        # print(f"Created M/M/1 Queue Model: {type(_queue)}")

    # Multi-server, infinite capacity
    elif model == "M/M/s":
        if n_servers < 1 or kapacity is not None:
            _msg = "M/M/s requires at least 1 server and infinite capacity. "
            _msg += f"s={n_servers}, K={kapacity}"
            raise ValueError(_msg)
        _queue = QueueMMs(_lambda, mu, n_servers)
        # print(f"Created M/M/s Queue Model: {type(_queue)}")

    # Single server, finite capacity
    elif model == "M/M/1/K":
        if n_servers != 1 or kapacity is None:
            _msg = "M/M/1/K requires exactly 1 server and finite capacity. "
            _msg += f"s={n_servers}, K={kapacity}"
            raise ValueError(_msg)
        _queue = QueueMM1K(_lambda, mu, n_servers, kapacity)
        # print(f"Created M/M/1/K Queue Model: {type(_queue)}")

    # Multi-server, finite capacity
    elif model == "M/M/c/K":
        if n_servers < 1 or kapacity is None:
            _msg = "M/M/c/K requires at least 1 server and finite capacity. "
            _msg += f"s={n_servers}, K={kapacity}"
            raise ValueError(_msg)
        if kapacity < n_servers:
            _msg = "M/M/c/K requires capacity K >= s. "
            _msg += f"K={kapacity}, s={n_servers}"
            raise ValueError(_msg)
        _queue = QueueMMsK(_lambda, mu, n_servers, kapacity)
        # print(f"Created M/M/c/K Queue Model: {type(_queue)}")

    # Add more conditions for other queue types. e.g., M/G/1, G/G/1, etc.
    # TODO: Implement additional queue models

    # otherwise, raise an error
    else:
        _msg = f"Unsupported queue configuration: {n_servers} "
        _msg += f"servers, {kapacity} max capacity"
        raise NotImplementedError(_msg)
    return _queue


def gfactorial(x: Union[int, float],
               prec: Optional[int] = None) -> Union[int, float]:
    """*gfactorial()* calculates the factorial of a number, including support for floats less than 1.0.

        - For integers n ≥ 0: Returns n! (n factorial).
        - For floats x: Returns Γ(x+1) (gamma function).

    Args:
        x (Union[int, float]): The number to compute the factorial for.
        prec (Optional[int], optional): precision, or the number of decimal places to round the result to. Defaults to None.

    Raises:
        ValueError: If x is a negative integer.

    Returns:
        Union[int, float]: The factorial of x. Returns an integer for integer inputs ≥ 0, and a float for float inputs or integers < 0.

    Examples:
        >>> gfactorial(5)
        120
        >>> gfactorial(0)
        1
        >>> gfactorial(0.5)  # Equivalent to Γ(1.5) = 0.5 * Γ(0.5) = 0.5 * √π
        0.8862269254527579
        >>> gfactorial(-0.5)  # Equivalent to Γ(0.5) = √π
        1.7724538509055159
    """
    if isinstance(x, int) and x >= 0:
        # Standard factorial for non-negative integers
        result = math.factorial(x)
    elif isinstance(x, int) and x < 0:
        # Factorial is not defined for negative integers
        raise ValueError("Factorial is not defined for negative integers")
    else:
        # For floats, use the gamma function: Γ(x+1)
        result = math.gamma(x + 1)

    # Apply precision if specified
    if prec is not None:
        result = round(result, prec)

    return result


@dataclass
class BasicQueue(ABC):
    """**BasicQueue** is an abstract base class for queueing theory models.

    Attributes:
        Input parameters:
        _lambda (float): Arrival rate (λ: lambda).
        mu (float): Service rate (μ: mu).
        n_servers (int): Number of servers (s: servers).
        kapacity (Optional[int]): Maximum capacity (K: capacity).

        # Output parameters:
        rho (float): Server utilization (ρ: rho).
        avg_len (float): L, or mean number of requests in the system.
        avg_len_q (float): Lq, or mean number of requests in queue.
        avg_wait (float): W, or mean time a request spends in the system.
        avg_wait_q (float): Wq, or mean waiting time in queue.
    """

    # :attr: _lambda
    _lambda: float = -1.0
    """Arrival rate (λ: lambda)."""

    # :attr: mu
    mu: float = -1.0
    """Service rate (μ: mu)."""

    # :attr: n_servers
    n_servers: int = 1
    """Number of servers (s: servers)."""

    # :attr: rho
    rho: float = field(default=0.0, init=False)
    """Server utilization (ρ: rho)."""

    # :attr: tau
    tau: float = field(default=0.0, init=False)
    """ Server traffic intensity (τ: tau)."""

    # :attr: kapacity
    kapacity: Optional[int] = None
    """Maximum capacity (K: capacity)."""

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

    _lambda_eff: float = field(default=0.0, init=False)
    """Effective Arrival rate (λe: lambda_eff = lambda * (1 - ))."""

    def __post_init__(self):
        """*__post_init__()* Post-initialization processing to validate parameters and calculate metrics.
        """
        # Ensure n_servers and kapacity are integers
        self.n_servers = int(self.n_servers)
        if self.kapacity is not None:
            self.kapacity = int(self.kapacity)
        elif self.kapacity is None:
            self.kapacity = -1
        else:
            # self.kapacity < 0:
            _msg = "Capacity must be non-negative or None for unbounded."
            raise ValueError(_msg)

        self._validate_basic_params()
        self._validate_params()

    def _validate_basic_params(self) -> None:
        """*_validate_basic_params()* Validates basic parameters common to all queueing models.

        Raises:
            ValueError: If arrival rate is non-positive.
            ValueError: If service rate is non-positive.
            ValueError: If number of servers is non-positive.
        """

        if self._lambda < 0:
            raise ValueError("Arrival rate must be positive.")
        if self.mu < 0:
            raise ValueError("Service rate must be positive.")
        if self.n_servers < 1:
            raise ValueError("Number of servers must be positive.")

    @abstractmethod
    def _validate_params(self) -> None:
        """*_validate_params()* Validates parameters specific to each queueing model.
        """
        pass

    @abstractmethod
    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates analytical metrics for the queueing model.
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
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        pass

    def get_metrics(self) -> Dict[str, Any]:
        """*get_metrics()* Returns a summary of the queueing system's metrics.

        Returns:
            Dict[str, Any]: A dictionary containing the calculated metrics with the following keys:
                - 'L': Average number requests inside the system.
                - 'Lq': Average number requests in queue.
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
            f"\tλ={self._lambda}",
            f"\tμ={self.mu}",
            f"\tservers={self.n_servers}"
        ]
        output.extend(params)
        if self.kapacity is not None:
            output.append(f"\tcapacity={self.kapacity}")

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
            str: String representation.
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
        ValueError: If the system is unstable (λ ≥ μ).

    Returns:
        QueueMM1: An instance of the M/M/1 queue model.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/1 queue.

        Raises:
            ValueError: If the number of servers is not 1.
            ValueError: If the capacity is not infinite.
            ValueError: If the system is unstable (λ ≥ μ).
        """

        if self.n_servers != 1:
            _msg = f"M/M/1 requires exactly 1 server. s={self.n_servers}"
            raise ValueError(_msg)
        if self.kapacity is not None:
            _msg = f"M/M/1 assumes infinite capacity. K={self.kapacity}"
            raise ValueError(_msg)
        if not self.is_stable():
            _msg = f"System is unstable (λ ≥ μ). λ={self._lambda}, μ={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """

        return self._lambda / self.mu < 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/1 queue.

        The model metrics are:
            - ρ (rho): Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.
        """
        # Calculate utilization (rho: ρ)
        self.rho = self._lambda / self.mu

        # Calculate traffic intensity (tau: τ)
        self.tau = self._lambda / self.mu

        # Calculate the probability of having 0 requests in the system
        self.p_z = self.calculate_prob_zero()

        # Calculate average number of requests in the system (L)
        self.avg_len = self.rho / (1 - self.rho)

        # Calculate average number of requests in the queue (Lq)
        self.avg_len_q = self.rho ** 2 / (1 - self.rho)

        # Calculate average time a request spends in the system (W)
        self.avg_wait = self.avg_len / self._lambda

        # Calculate average time a request spends in the queue (Wq)
        self.avg_wait_q = self.avg_len_q / self._lambda

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) or the probability of having 0 requests in the system for M/M/1 model.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        p_z = 1.0 - self.rho
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* calculates P(n), or the probability of having n requests in the system for M/M/1.

        Args:
            n (int): The number of requests in the system.

        Raises:
            ValueError: If the system is unstable.

        Returns:
            float: The probability of having n requests in the system.
        """
        p_n = 0
        if n < 0:
            p_n = -1.0
        elif n >= 0:
            p_n = (1 - self.rho) * (self.rho ** n)
        self.p_n = p_n
        return p_n


@dataclass
class QueueMMs(BasicQueue):
    """**QueueMMs** represents an M/M/s queue system (Multi-server, infinite capacity).

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is less than 1.
        ValueError: If the capacity is not infinite.
        ValueError: If the system is unstable (λ ≥ s * μ).

    Returns:
        QueueMMs: An instance of the M/M/s queue model.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/s model.

        Raises:
            ValueError: If the number of servers is less than 1.
            ValueError: If the capacity is not infinite.
            ValueError: If the system is unstable (λ ≥ c x μ).
        """
        if self.n_servers < 1:
            _msg = f"M/M/s requires at least one server. s={self.n_servers}"
            raise ValueError(_msg)
        if self.kapacity is not None:
            _msg = f"M/M/s assumes infinite capacity. K={self.kapacity}"
            raise ValueError(_msg)
        if not self.is_stable():
            _msg = f"System is unstable (λ ≥ s * μ). λ={self._lambda}, "
            _msg += f"s={self.n_servers}, μ={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """

        return self._lambda / (self.n_servers * self.mu) < 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/s queue.

        The model metrics are:
            - ρ (rho): Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.
        """
        # Calculate utilization (rho)
        self.rho = self._lambda / (self.n_servers * self.mu)

        # Calculate traffic intensity (tau)
        self.tau = self._lambda / self.mu

        # Calculate the probability of having 0 requests in the system
        self.p_z = self.calculate_prob_zero()

        # Calculate the average number of requests in the queue
        numerator = self.p_z * (self.tau ** self.n_servers) * self.rho
        denominator = gfactorial(self.n_servers) * ((1 - self.rho) ** 2)
        self.avg_len_q = numerator / denominator

        # Calculate the average number of requests in the system
        self.avg_len = self.avg_len_q + self.tau

        # Calculate the average time spent in the queue
        self.avg_wait_q = self.avg_len_q / self._lambda

        # Calculate the average time spent in the system
        self.avg_wait = self.avg_wait_q + self.mu**-1

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) or the probability of having 0 requests in the system for M/M/s model.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # calculate probability of having up to s requests in the system
        p_under_s = sum((self.tau ** i) / gfactorial(i)
                        for i in range(self.n_servers))

        # calculate probability of having more than s requests in the system
        numerator = (self.tau ** self.n_servers)
        denominator = gfactorial(self.n_servers) * (1 - self.rho)
        p_over_s = numerator / denominator

        # calculate the probability of having 0 requests in the system
        p_z = (p_under_s + p_over_s)**-1
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* calculates P(n), or the probability of having n requests in the system for M/M/s.

        Args:
            n (int): The number of requests in the system.

        Raises:
            ValueError: If the system is unstable.

        Returns:
            float: The probability of having n requests in the system.
        """
        # calculate the probability of having n requests in the system
        numerator = self.tau ** n
        denominator = 1.0

        # default value, for error checking
        p_n = -1.0
        # if request is less than 0
        if n < 0:
            p_n = -1.0

        # if there are less requests than servers
        elif n <= self.n_servers:
            denominator = gfactorial(n)

        # otherwise, there are more requests than servers
        elif n >= self.n_servers:
            power = (self.n_servers ** (n - self.n_servers))
            denominator = (gfactorial(self.n_servers) * power)

        # finishing up calculations
        p_n = (numerator / denominator) * self.p_z
        self.p_n = p_n
        return p_n


@dataclass
class QueueMM1K(BasicQueue):
    """**QueueMM1K** Represents an M/M/1/K queue system with finite capacity 'K' and one server.


    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is not 1.
        ValueError: If the capacity is not positive.
        ValueError: If the system is unstable (λ ≥ s * μ).

    Returns:
        QueueMM1K: An instance of the M/M/1/K queue model.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/1/k model.

        Raises:
            ValueError: If the number of servers is not 1.
            ValueError: If the capacity is not positive.
            ValueError: If the system is unstable (λ ≥ μ).
        """
        if self.n_servers != 1:
            _msg = f"M/M/1/K requires exactly 1 server. s={self.n_servers}"
            raise ValueError(_msg)
        if self.kapacity is None or self.kapacity < 1:
            _msg = f"M/M/1/K requires a positive finite capacity. K={self.kapacity}"
            raise ValueError(_msg)
        if self.is_stable() is False:
            _msg = f"System is unstable (λ ≥ μ). λ={self._lambda}, μ={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        return self._lambda / self.mu <= 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/1/K queue model.

        The model metrics are:
            - ρ (rho): Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.
        """
        # Calculate the utilization (rho)
        self.rho = self._lambda / self.mu

        # Calculate traffic intensity (tau)
        self.tau = self._lambda / self.mu

        if self.kapacity is not None:
            # Calculate the probability of having max capacity
            _p_kapacity = self.calculate_prob_n(self.kapacity)

            # Calculate the effective arrival rate
            self._lambda_eff = self._lambda * (1 - _p_kapacity)

            # if utilization (rho) is less than 1
            if self.rho < 1.0:
                # Calculate requests in server
                in_server = (self.rho) / (1 - self.rho)
                # Calculate requests in system
                numerator = (self.kapacity + 1) * self.rho ** (self.kapacity + 1)
                denominator = (1 - self.rho ** (self.kapacity + 1))
                in_queue = numerator / denominator
                # Calculate average number of requests in the system
                self.avg_len = in_server - in_queue

                # Calculate average number of requests in the queue
                # aquivalent to:
                # self.avg_len_q = self.avg_len - self.rho * (1 - _p_kapacity)
                self.avg_len_q = self.avg_len - self._lambda_eff / self.mu

            # if utilization (rho) is equal to 1, saturation occurs
            if self.rho == 1.0:
                self.avg_len = self.kapacity / 2

                # Calculate average number of requests in the queue
                numerator = self.kapacity * (self.kapacity - 1)
                denominator = (2 * self.kapacity + 1)
                self.avg_len_q = numerator / denominator

            # Calculate average time spent in the system
            self.avg_wait = self.avg_len / self._lambda_eff

            # Calculate average time spent in the queue
            self.avg_wait_q = self.avg_len_q / self._lambda_eff

    def calculate_prob_zero(self) -> float:
        """*calculate_prob_zero()* Calculates P(0) or the probability of having 0 requests in the system for M/M/1/k model.

        NOTE: Unnecessary function but was weird not to have it.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # use the probability of having n = 0 requests in the system.
        p_z = -1
        if self.kapacity is not None:
            numerator = 1 - self.rho
            denominator = 1 - self.rho ** (self.kapacity + 1)
            p_z = numerator / denominator

        # return the calculated probability of having 0 requests in the system
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*get_prob_n()* Calculates P(n) or the probability of having n requests in the system for M/M/1/k model.

        Args:
            n (int): The number of requests.

        Returns:
            float: The probability of having n requests in the system.
        """

        # default values for checking errors
        p_n = -1.0

        if self.kapacity is not None:
            # if utilization (rho) is less than 1
            if self.rho < 1.0:
                numerator = (1 - self.rho) * (self.rho ** n)
                denominator = (1 - self.rho ** (self.kapacity + 1))
                p_n = numerator / denominator

            # if utilization (rho) is equal to 1, saturation occurs
            elif self.rho == 1.0:
                p_n = (self.kapacity + 1)**-1

        # return the calculated probability of having 0 requests in the system
        self.p_n = p_n
        return p_n


@dataclass
class QueueMMsK(BasicQueue):
    """**QueueMMsK** Represents an M/M/c/K queue system (finite capacity 'K', 's' number of servers).

    Args:
        BasicQueue (ABC, dataclass): Abstract base class for queueing theory models.

    Raises:
        ValueError: If the number of servers is less than 1.
        ValueError: If the capacity is less than the number of servers.
        ValueError: If the system is unstable (λ ≥ s * μ).

    Returns:
        QueueMMsK: An instance of the M/M/c/K queueing system.
    """

    def _validate_params(self) -> None:
        """*_validate_params()* Validates the parameters for the M/M/c/K queueing system.

        Raises:
            ValueError: If the number of servers is less than 1.
            ValueError: If the capacity is less than the number of servers.
            ValueError: If the system is unstable (λ ≥ s * μ).
        """
        if self.n_servers < 1:
            _msg = f"M/M/c/K requires at least one server. s={self.n_servers}"
            raise ValueError(_msg)
        if self.kapacity is None or self.kapacity < self.n_servers:
            _msg = f"M/M/c/K requires capacity K >= s. K={self.kapacity}, "
            _msg += f"s={self.n_servers}"
            raise ValueError(_msg)
        if not self.is_stable():
            _msg = f"System is unstable (λ ≥ s * μ). λ={self._lambda}, "
            _msg += f"s={self.n_servers}, μ={self.mu}"
            raise ValueError(_msg)

    def is_stable(self) -> bool:
        """*is_stable()* Checks if the M/M/c/K queueing system is stable.

        Returns:
            bool: True if the system is stable, False otherwise.
        """
        return self._lambda / (self.n_servers * self.mu) < 1.0

    def calculate_metrics(self) -> None:
        """*calculate_metrics()* Calculates the performance metrics for the M/M/c/K queue.

        The model metrics are:
            - ρ (rho): Server utilization.
            - L (avg_len): Average number of requests in the system.
            - Lq (avg_len_q): Average number of requests in the queue.
            - W (avg_wait): Average time a request spends in the system.
            - Wq (avg_wait_q): Average time a request spends in the queue.
        """
        # calculate the server utilization (rho)
        self.rho = self._lambda / (self.n_servers * self.mu)

        # calculate the traffic intensity (tau)
        self.tau = self._lambda / self.mu

        # calculate probability of zero requests in the system
        self.p_z = self.calculate_prob_zero()

        if self.kapacity is not None:
            # calculate the probability to be at full capacity
            _p_kapacity = self.calculate_prob_n(self.kapacity)

            # Calculate effective arrival rate (λ_eff)
            self._lambda_eff = self._lambda * (1 - _p_kapacity)

            # calculate the average number of requests in the queue (Lq)
            K = self.kapacity
            L = sum([i * self.calculate_prob_n(i) for i in range(K + 1)])
            self.avg_len = L

            # Calculate average number of requests in the queue (Lq)
            s = self.n_servers
            Lq = sum([(i - s) * self.calculate_prob_n(i)
                      for i in range(s, K + 1)])
            self.avg_len_q = Lq

            # calculate the average time a request spends in the system (W)
            self.avg_wait = self.avg_len / self._lambda_eff

            # calculate the average time a request spends in the queue (Wq)
            self.avg_wait_q = self.avg_len_q / self._lambda_eff

    def calculate_prob_zero(self) -> float:
        """*get_prob_zero()* Calculates P(0) or the probability of having 0 requests in the system for M/M/c/K model.

        Returns:
            float: The probability of having 0 requests in the system.
        """
        # default value, for error checking
        p_z = -1.0

        if self.kapacity is not None:
            # Calculate probability in servers
            tau = self.tau
            s = self.n_servers
            K = self.kapacity
            _sum_s = sum((tau ** i) / gfactorial(i) for i in range(s))
            _sum_q = sum((tau ** i) / (gfactorial(s) * (s ** (i - s)))
                         for i in range(s, K + 1))

            p_z = (_sum_s + _sum_q)**-1
        return p_z

    def calculate_prob_n(self, n: int) -> float:
        """*calculate_prob_n()* Calculates P(n), or the probability of having n requests in the system for M/M/c/K model.

        Args:
            n (int): The number of requests.

        Returns:
            float: The probability of having n requests in the system.
        """
        # default value, for error checking
        p_n = -1.0

        # Calculate the probability of having n requests in the system
        numerator = self.tau ** n

        if self.kapacity is not None:
            # if request is less than 0
            if n < 0:
                # return default value
                p_n = -1.0

            # otherwise, if request is greater than capacity
            elif n > self.kapacity:
                p_n = -1.0

            # else if, request is less than number of servers
            elif 0 <= n < self.n_servers:
                # Calculate the probability of having n requests in the system
                p_n = (numerator / gfactorial(n)) * self.p_z
            # else if, request is greater than or equal to number of servers
            elif self.n_servers <= n <= self.kapacity:

                _pow = self.n_servers ** (n - self.n_servers)
                denominator = gfactorial(self.n_servers) * _pow
                p_n = (numerator / denominator) * self.p_z

        self.p_n = p_n
        return p_n
