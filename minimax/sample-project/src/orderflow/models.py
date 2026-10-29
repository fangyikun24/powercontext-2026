"""Domain models for the orderflow sample service.

This is the business project the SDD task is performed on. It is deliberately small
but complete: real value objects, real validation, and a test suite that runs offline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

CENTS = Decimal("0.01")


def money(value: Decimal | int | str) -> Decimal:
    """Quantize a value to two decimal places using commercial rounding."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PLACED = "placed"
    PAID = "paid"
    CANCELLED = "cancelled"


class CustomerTier(StrEnum):
    STANDARD = "standard"
    SILVER = "silver"
    GOLD = "gold"


@dataclass(frozen=True)
class OrderLine:
    """One SKU ordered in a quantity."""

    sku: str
    quantity: int
    unit_price: Decimal

    def __post_init__(self) -> None:
        if not self.sku or not self.sku.strip():
            raise ValueError("sku must not be blank")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"unit_price must not be negative, got {self.unit_price}")

    @property
    def subtotal(self) -> Decimal:
        return money(self.unit_price * self.quantity)


@dataclass
class Order:
    """A customer order made of one or more lines."""

    order_id: str
    customer_id: str
    lines: list[OrderLine] = field(default_factory=list)
    status: OrderStatus = OrderStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.order_id or not self.order_id.strip():
            raise ValueError("order_id must not be blank")
        if not self.customer_id or not self.customer_id.strip():
            raise ValueError("customer_id must not be blank")

    @property
    def subtotal(self) -> Decimal:
        """Sum of line subtotals, before any discount."""
        return money(sum((line.subtotal for line in self.lines), Decimal("0")))

    @property
    def total(self) -> Decimal:
        """Payable amount for this order, before customer-tier discount."""
        return self.subtotal

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines)


def summarize(orders: Iterable[Order]) -> dict[str, Decimal | int]:
    """Aggregate a collection of orders into a small report."""
    orders = list(orders)
    return {
        "orders": len(orders),
        "items": sum(order.item_count for order in orders),
        "total": money(sum((order.total for order in orders), Decimal("0"))),
    }
