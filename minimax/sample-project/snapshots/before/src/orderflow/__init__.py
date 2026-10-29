"""Orderflow sample service: a small, testable order-management business project."""

from __future__ import annotations

from orderflow.errors import (
    InsufficientStockError,
    InvalidTransitionError,
    OrderFlowError,
    OrderNotFoundError,
)
from orderflow.inventory import StockLedger
from orderflow.models import CustomerTier, Order, OrderLine, OrderStatus, money, summarize
from orderflow.pricing import discount_rate, order_total
from orderflow.service import OrderService

__all__ = [
    "CustomerTier",
    "InsufficientStockError",
    "InvalidTransitionError",
    "Order",
    "OrderFlowError",
    "OrderLine",
    "OrderNotFoundError",
    "OrderService",
    "OrderStatus",
    "StockLedger",
    "discount_rate",
    "money",
    "order_total",
    "summarize",
]
