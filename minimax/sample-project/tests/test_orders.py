"""Regression tests for order listing (SPEC-ORD-001..003).

These tests must pass both before and after the SPEC-ORD-004 change.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from orderflow import Order, OrderLine, OrderService, OrderStatus


def build_order(order_id: str, customer_id: str, *, day: int, amount: str, status: OrderStatus) -> Order:
    return Order(
        order_id=order_id,
        customer_id=customer_id,
        lines=[OrderLine(sku="SKU-1", quantity=1, unit_price=Decimal(amount))],
        status=status,
        created_at=datetime(2026, 1, day, tzinfo=UTC),
    )


@pytest.fixture
def service() -> OrderService:
    return OrderService(
        [
            build_order("O-1", "C-1", day=1, amount="10.00", status=OrderStatus.DRAFT),
            build_order("O-2", "C-1", day=2, amount="150.00", status=OrderStatus.PLACED),
            build_order("O-3", "C-2", day=3, amount="90.00", status=OrderStatus.PLACED),
            build_order("O-4", "C-2", day=4, amount="300.00", status=OrderStatus.CANCELLED),
        ]
    )


# --- SPEC-ORD-001 -----------------------------------------------------------


def test_duplicate_order_id_is_rejected(service):
    with pytest.raises(ValueError):
        service.add_order(build_order("O-1", "C-9", day=9, amount="1.00", status=OrderStatus.DRAFT))


def test_blank_order_id_is_rejected():
    with pytest.raises(ValueError):
        Order(order_id="  ", customer_id="C-1")


def test_get_unknown_order_raises(service):
    with pytest.raises(Exception) as excinfo:
        service.get("missing")
    assert excinfo.value.__class__.__name__ == "OrderNotFoundError"


# --- SPEC-ORD-002 -----------------------------------------------------------


def test_list_without_filters_returns_all_in_stable_order(service):
    orders = service.list_orders()
    assert [order.order_id for order in orders] == ["O-1", "O-2", "O-3", "O-4"]


def test_list_filters_by_status(service):
    orders = service.list_orders(status=OrderStatus.PLACED)
    assert [order.order_id for order in orders] == ["O-2", "O-3"]


def test_list_with_unknown_status_returns_empty(service):
    assert service.list_orders(status=OrderStatus.PAID) == []


# --- SPEC-ORD-003 -----------------------------------------------------------


def test_list_filters_by_customer(service):
    orders = service.list_orders(customer_id="C-2")
    assert [order.order_id for order in orders] == ["O-3", "O-4"]


def test_list_combines_status_and_customer(service):
    orders = service.list_orders(status=OrderStatus.PLACED, customer_id="C-2")
    assert [order.order_id for order in orders] == ["O-3"]


def test_list_returns_new_list_each_call(service):
    first = service.list_orders()
    first.clear()
    assert len(service.list_orders()) == 4
