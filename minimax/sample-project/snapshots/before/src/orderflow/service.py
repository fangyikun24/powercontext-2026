"""Application service: order registration, lookup, listing and placement."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from orderflow.errors import InvalidTransitionError, OrderNotFoundError
from orderflow.inventory import StockLedger
from orderflow.models import Order, OrderStatus


class OrderService:
    """In-memory order repository plus the operations the API exposes."""

    def __init__(self, orders: Iterable[Order] = (), ledger: StockLedger | None = None) -> None:
        self._orders: dict[str, Order] = {}
        self._ledger = ledger if ledger is not None else StockLedger()
        for order in orders:
            self.add_order(order)

    @property
    def ledger(self) -> StockLedger:
        return self._ledger

    def add_order(self, order: Order) -> Order:
        if order.order_id in self._orders:
            raise ValueError(f"duplicate order id: {order.order_id}")
        self._orders[order.order_id] = order
        return order

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError as error:
            raise OrderNotFoundError(order_id) from error

    def list_orders(
        self,
        *,
        status: OrderStatus | None = None,
        customer_id: str | None = None,
    ) -> list[Order]:
        """Return orders matching the supplied filters, oldest first.

        Every filter is optional; omitted filters do not restrict the result.
        """
        result = list(self._orders.values())
        if status is not None:
            result = [order for order in result if order.status == status]
        if customer_id is not None:
            result = [order for order in result if order.customer_id == customer_id]
        return sorted(result, key=lambda order: (order.created_at, order.order_id))

    def place(self, order_id: str) -> Order:
        """Move a draft order to placed and reserve its stock."""
        order = self.get(order_id)
        if order.status is not OrderStatus.DRAFT:
            raise InvalidTransitionError(f"{order_id}: cannot place from {order.status}")
        for line in order.lines:
            self._ledger.reserve(line.sku, line.quantity)
        order.status = OrderStatus.PLACED
        return order

    def cancel(self, order_id: str) -> Order:
        """Cancel an order, releasing any reserved stock."""
        order = self.get(order_id)
        if order.status is OrderStatus.CANCELLED:
            raise InvalidTransitionError(f"{order_id}: already cancelled")
        if order.status is OrderStatus.PLACED:
            for line in order.lines:
                self._ledger.release(line.sku, line.quantity)
        order.status = OrderStatus.CANCELLED
        return order

    def total_revenue(self) -> Decimal:
        """Sum of totals for orders that are not cancelled or draft."""
        payable = [order for order in self._orders.values() if order.status in {OrderStatus.PLACED, OrderStatus.PAID}]
        return sum((order.total for order in payable), Decimal("0"))
