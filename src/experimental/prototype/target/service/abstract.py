"""AbstractService: root of the service-class hierarchy (Weyns & Calinescu 2015 Fig. 2).

Defines the lifecycle hooks (`start_service`, `stop_service`) and the operation-invocation contract (`invoke_operation`) every atomic and composite service honours, so the controller's monitor and effector see a single, uniform attachment point.

Translated from the paper's Java interface to a Python `abc.ABC`: `serviceName` becomes `service_name`, methods are snake_case. Lifecycle hooks default to no-ops; subclasses override when they need warm-up or tear-down.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractService(ABC):
    """Root of the service-class hierarchy.

    Attributes:
        service_name (str): identifier; matches the catalogue key for this service.
    """

    def __init__(self, *, service_name: str) -> None:
        """Record the service identifier.

        Args:
            service_name (str): catalogue identifier (e.g. `vernier`, `AS_{1}`).
        """
        self.service_name = service_name

    def start_service(self) -> None:
        """Hook fired before requests start arriving. Default: no-op."""
        return

    def stop_service(self) -> None:
        """Hook fired after the last request drains. Default: no-op."""
        return

    @abstractmethod
    async def invoke_operation(self,
                               payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Handle one operation; return `(body, status_code)`.

        Args:
            payload (dict[str, Any]): parsed request body.

        Returns:
            tuple[dict[str, Any], int]: response body + HTTP status code.
        """
        ...
