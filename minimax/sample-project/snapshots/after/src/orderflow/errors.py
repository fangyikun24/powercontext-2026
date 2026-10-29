"""Error types for the orderflow sample service."""

from __future__ import annotations


class OrderFlowError(Exception):
    """Base class for every orderflow error."""


class OrderNotFoundError(OrderFlowError):
    """Raised when an order id is not known to the service."""


class InsufficientStockError(OrderFlowError):
    """Raised when a reservation asks for more stock than is available."""

    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(f"insufficient stock for {sku}: requested {requested}, available {available}")
        self.sku = sku
        self.requested = requested
        self.available = available


class InvalidTransitionError(OrderFlowError):
    """Raised when an order status transition is not allowed."""
