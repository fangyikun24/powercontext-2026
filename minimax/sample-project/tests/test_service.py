"""Regression tests for order placement and cancellation (SPEC-ORD-005)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from orderflow import InsufficientStockError, InvalidTransitionError, Order, OrderLine, OrderService, OrderStatus
from orderflow.inventory import StockLedger


def build_order(order_id: str = "O-1", *, quantity: int = 2, amount: str = "10.00") -> Order:
    return Order(order_id=order_id, customer_id="C-1", lines=[OrderLine(sku="SKU-1", quantity=quantity, unit_price=Decimal(amount))])


def test_place_reserves_stock():
    service = OrderService([build_order()], ledger=StockLedger(on_hand={"SKU-1": 5}))
    service.place("O-1")
    assert service.get("O-1").status is OrderStatus.PLACED
    assert service.ledger.available("SKU-1") == 3


def test_place_without_stock_raises_and_leaves_order_draft():
    service = OrderService([build_order()], ledger=StockLedger(on_hand={"SKU-1": 1}))
    with pytest.raises(InsufficientStockError):
        service.place("O-1")
    assert service.get("O-1").status is OrderStatus.DRAFT
    assert service.ledger.available("SKU-1") == 1


def test_place_twice_is_rejected():
    service = OrderService([build_order()], ledger=StockLedger(on_hand={"SKU-1": 10}))
    service.place("O-1")
    with pytest.raises(InvalidTransitionError):
        service.place("O-1")


def test_cancel_releases_reserved_stock():
    service = OrderService([build_order()], ledger=StockLedger(on_hand={"SKU-1": 5}))
    service.place("O-1")
    service.cancel("O-1")
    assert service.get("O-1").status is OrderStatus.CANCELLED
    assert service.ledger.available("SKU-1") == 5


def test_cancel_twice_is_rejected():
    service = OrderService([build_order()])
    service.cancel("O-1")
    with pytest.raises(InvalidTransitionError):
        service.cancel("O-1")


def test_total_revenue_counts_placed_and_paid_only():
    service = OrderService(
        [
            build_order("O-1", amount="10.00"),
            build_order("O-2", amount="20.00"),
        ]
    )
    service.ledger.receive("SKU-1", 10)
    service.place("O-1")
    assert service.total_revenue() == Decimal("20.00")
