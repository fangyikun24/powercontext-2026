"""Regression tests for pricing rules (SPEC-PRC-001..004).

These tests must pass both before and after the SPEC-ORD-004 change.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from orderflow import CustomerTier, Order, OrderLine, discount_rate, money, order_total


def make_order(*lines: tuple[str, int, str]) -> Order:
    return Order(
        order_id="O-1",
        customer_id="C-1",
        lines=[OrderLine(sku=sku, quantity=qty, unit_price=Decimal(price)) for sku, qty, price in lines],
    )


# --- SPEC-PRC-001 -----------------------------------------------------------


def test_money_uses_half_up_rounding():
    assert money("1.005") == Decimal("1.01")
    assert money("1.004") == Decimal("1.00")
    assert money("2.675") == Decimal("2.68")


def test_line_subtotal_is_quantized_to_cents():
    line = OrderLine(sku="SKU-1", quantity=3, unit_price=Decimal("1.005"))
    assert line.subtotal == Decimal("3.02")


# --- SPEC-PRC-002 -----------------------------------------------------------


def test_order_subtotal_sums_lines():
    order = make_order(("A", 2, "10.00"), ("B", 1, "5.50"))
    assert order.subtotal == Decimal("25.50")


def test_order_total_equals_subtotal():
    order = make_order(("A", 2, "10.00"))
    assert order.total == order.subtotal


def test_empty_order_has_zero_total():
    order = Order(order_id="O-EMPTY", customer_id="C-1")
    assert order.subtotal == Decimal("0.00")
    assert order.total == Decimal("0.00")


# --- SPEC-PRC-003 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "subtotal", "expected"),
    [
        (CustomerTier.STANDARD, "1000.00", "0"),
        (CustomerTier.SILVER, "99.99", "0"),
        (CustomerTier.SILVER, "100.00", "0.05"),
        (CustomerTier.GOLD, "49.99", "0"),
        (CustomerTier.GOLD, "50.00", "0.05"),
        (CustomerTier.GOLD, "200.00", "0.10"),
    ],
)
def test_discount_rate_thresholds(tier, subtotal, expected):
    assert discount_rate(tier, Decimal(subtotal)) == Decimal(expected)


def test_discount_rate_takes_best_not_sum():
    # GOLD at 200 hits both 5% and 10%; the result must be 10%, not 15%.
    assert discount_rate(CustomerTier.GOLD, Decimal("200.00")) == Decimal("0.10")


def test_unknown_tier_behaves_like_standard():
    assert discount_rate("platinum", Decimal("500.00")) == Decimal("0")


# --- SPEC-PRC-004 -----------------------------------------------------------


def test_order_total_applies_discount():
    order = make_order(("A", 1, "200.00"))
    assert order_total(order, CustomerTier.GOLD) == Decimal("180.00")


def test_order_total_zero_rate_is_exact():
    order = make_order(("A", 1, "10.00"))
    assert order_total(order, CustomerTier.STANDARD) == order.subtotal
