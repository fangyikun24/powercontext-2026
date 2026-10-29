"""Target functional tests for SPEC-ORD-004 (order listing minimum-total filter).

covers: SPEC-ORD-004

This file is part of the fixed test set: it is identical in the pre-change and
post-change snapshots. Before the implementation lands, every test here fails with
``TypeError: list_orders() got an unexpected keyword argument 'min_total'`` — a real
missing-behaviour failure, not an environment error.
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


def test_min_total_filters_out_smaller_orders(service):
    orders = service.list_orders(min_total=Decimal("100.00"))
    assert [order.order_id for order in orders] == ["O-2", "O-4"]


def test_min_total_boundary_is_inclusive(service):
    # O-3 totals exactly 90.00 and must be kept when the floor is 90.00.
    orders = service.list_orders(min_total=Decimal("90.00"))
    assert [order.order_id for order in orders] == ["O-2", "O-3", "O-4"]


def test_min_total_none_returns_everything(service):
    orders = service.list_orders(min_total=None)
    assert [order.order_id for order in orders] == ["O-1", "O-2", "O-3", "O-4"]


def test_min_total_above_everything_returns_empty(service):
    assert service.list_orders(min_total=Decimal("10000.00")) == []


def test_min_total_combines_with_status_and_customer(service):
    orders = service.list_orders(status=OrderStatus.PLACED, customer_id="C-2", min_total=Decimal("50.00"))
    assert [order.order_id for order in orders] == ["O-3"]


def test_min_total_still_respects_customer_filter(service):
    orders = service.list_orders(customer_id="C-1", min_total=Decimal("100.00"))
    assert [order.order_id for order in orders] == ["O-2"]


def test_negative_min_total_is_rejected(service):
    with pytest.raises(ValueError):
        service.list_orders(min_total=Decimal("-1.00"))


def test_min_total_is_keyword_only_and_keeps_existing_calls_working(service):
    # Existing positional/keyword usage must be unaffected by the new parameter.
    assert [order.order_id for order in service.list_orders()] == ["O-1", "O-2", "O-3", "O-4"]
    assert [order.order_id for order in service.list_orders(status=OrderStatus.PLACED)] == ["O-2", "O-3"]
    with pytest.raises(TypeError):
        service.list_orders(OrderStatus.PLACED)  # type: ignore[misc]
