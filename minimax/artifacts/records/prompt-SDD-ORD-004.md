# System prompt

You are a senior engineer performing a spec-driven development (SDD) change.

You will receive:
- the task to perform,
- the authoritative specification entries that apply,
- the current source of the code that must change,
- the functional tests that must go from failing to passing,
- the regression tests that must keep passing.

Rules:
1. Implement exactly what the specifications require. Do not invent behaviour.
2. Do NOT modify, delete, skip or weaken any test. Tests are the acceptance criteria.
3. Do NOT change unrelated files.
4. Keep the change minimal and idiomatic for the project's existing style.
5. Every requirement that mentions a preserved behaviour must remain satisfied.
6. The COMPLETE current content of every file you may change is included in the prompt.
   You have everything you need; never reply that you cannot read files or need a tool.
   Always return at least one entry in "changes".

Respond with ONE JSON object and nothing else, using this shape:

{
  "summary": "<one paragraph describing what you changed and why>",
  "changes": [
    {"path": "<project-relative path>", "content": "<the complete new file content>"}
  ],
  "spec_coverage": [{"spec": "SPEC-...", "how": "<how the change satisfies it>"}],
  "risks": ["<anything a reviewer should double-check>"]
}


# User prompt

# Development context for task SDD-ORD-004

Task: SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders whose total is at least min_total are returned; negative min_total must be rejected

## Applicable specifications
### SPEC-ORD-004 订单列表金额下限筛选
source: specs/orders.md:33-43
content_sha256: 78428e78df8c0ab797591c36bd1d957738f359b1d886598fd81162643dae3ad5
```markdown
### SPEC-ORD-004 — 订单列表金额下限筛选

- **状态**: accepted（本次任务新增）
- **接口**: `OrderService.list_orders(min_total=None) -> list[Order]`
- **要求**: 新增可选关键字参数 `min_total: Decimal | None`。
- **要求**: `min_total` 为 `None` 时不过滤，行为与未传该参数完全一致。
- **要求**: 给定时只返回 `order.total >= min_total` 的订单，**下界包含等号**。
- **要求**: `order.total` 指订单 `models.Order.total` 属性（折扣前应付金额）。
- **要求**: 与其他筛选条件按**逻辑与**组合。
- **要求**: `min_total` 为负数时抛出 `ValueError`，不得静默当作无过滤。
- **兼容性**: 该参数必须是**仅关键字**参数，且默认 `None`，保证既有调用方不受影响。
```

### SPEC-ORD-005 下单与取消的库存联动
source: specs/orders.md:45-69
content_sha256: a2c3412fec9d91f9715b986c45472f41efc1cb1b053824b628ffa5af1c429f1b
```markdown
### SPEC-ORD-005 — 下单与取消的库存联动

- **状态**: accepted
- **接口**: `OrderService.place(order_id)`、`OrderService.cancel(order_id)`
- **要求**: `place` 仅允许从 `draft` 流转到 `placed`，并对每一行预留库存。
- **要求**: 库存不足时抛出 `InsufficientStockError`，订单状态保持 `draft`（不得部分预留）。
- **要求**: `cancel` 对 `placed` 订单释放已预留库存；对已取消订单抛 `InvalidTransitionError`。

## 3. 必须保持的既有行为（回归约束）

以下行为在本次修改中**不得改变**，任何实现必须继续满足：

1. `list_orders()` 无参调用返回全部订单，且顺序稳定（SPEC-ORD-002）。
2. `list_orders(status=...)` 与 `list_orders(customer_id=...)` 的既有筛选语义不变（SPEC-ORD-002/003）。
3. 订单金额相关属性 `Order.subtotal` / `Order.total` 语义不变，仍为两位小数、四舍五入（见 pricing 规格）。
4. 下单/取消的库存联动与异常类型不变（SPEC-ORD-005）。
5. 既有调用方以位置参数或关键字参数调用 `add_order` / `get` / `place` / `cancel` 的方式不变。

## 4. 验收映射

| 需求 | 功能测试 | 回归测试 |
| --- | --- | --- |
| SPEC-ORD-004 | `tests/test_min_total_filter.py` | `tests/test_orders.py` |
| SPEC-ORD-002/003 | `tests/test_orders.py` | — |
| SPEC-ORD-005 | `tests/test_service.py` | — |
```

### SPEC-ORD-001 订单创建与唯一性
source: specs/orders.md:12-17
content_sha256: 6c0aa6be1bb493d2d30ce7b0108a3118170202e2ba49d8b504b8663f87d6eca9
```markdown
### SPEC-ORD-001 — 订单创建与唯一性

- **状态**: accepted
- **接口**: `OrderService.add_order(order) -> Order`
- **要求**: 相同 `order_id` 不得重复加入，重复时必须抛出 `ValueError`。
- **要求**: `order_id` 与 `customer_id` 不允许为空白字符串。
```

### SPEC-ORD-002 按状态筛选
source: specs/orders.md:19-24
content_sha256: fe13ca5435d1f7aa0618d2bec6fce2b9bf40917cd97daeae37c7d48c4638a601
```markdown
### SPEC-ORD-002 — 按状态筛选

- **状态**: accepted
- **接口**: `OrderService.list_orders(status=None) -> list[Order]`
- **要求**: `status` 为 `None` 时返回全部订单；否则只返回 `order.status == status` 的订单。
- **要求**: 结果按 `(created_at, order_id)` 升序排列，保证输出稳定可回归。
```

### SPEC-ORD-003 按客户筛选
source: specs/orders.md:26-31
content_sha256: afd8e86d6b66113269f79d4e64c5242a822be5749b88104d1854d203770aacfb
```markdown
### SPEC-ORD-003 — 按客户筛选

- **状态**: accepted
- **接口**: `OrderService.list_orders(customer_id=None) -> list[Order]`
- **要求**: `customer_id` 为 `None` 时不限制；否则只返回该客户的订单。
- **要求**: 与 `status` 同时给出时按**逻辑与**组合。
```

### SPEC-PRC-004 折扣后应付金额
source: specs/pricing.md:34-54
content_sha256: fb2e71bed8123d20d3aa1c23dbc523b372860ffc372e4f0d25b32f9813d8d054
```markdown
### SPEC-PRC-004 — 折扣后应付金额

- **状态**: accepted
- **接口**: `pricing.order_total(order, tier) -> Decimal`
- **要求**: `order_total = subtotal * (1 - rate)`，两位小数、`ROUND_HALF_UP`。
- **要求**: `rate == 0` 时直接返回 `subtotal`，不得因乘法引入精度抖动。
- **要求**: 未知等级按 `standard` 处理，不得抛出异常。

## 3. 必须保持的既有行为（回归约束）

1. 金额量化的舍入方式为 `ROUND_HALF_UP`，不得改为银行家舍入（SPEC-PRC-001）。
2. `Order.total == Order.subtotal`（SPEC-PRC-002）。
3. 折扣率取最高命中门槛，不叠加（SPEC-PRC-003）。
4. `rate == 0` 时返回原 `subtotal` 对象等值金额，不改变数值（SPEC-PRC-004）。

## 4. 验收映射

| 需求 | 功能测试 | 回归测试 |
| --- | --- | --- |
| SPEC-PRC-001/002 | `tests/test_pricing.py` | — |
| SPEC-PRC-003/004 | `tests/test_pricing.py` | — |
```

## Code to change
### OrderService.list_orders
source: src/orderflow/service.py:38-59
content_sha256: 0163b6b036b58505fe093e9fad83dfa94f064a7770b9008be4fc4907f95d492d
```python
Return orders matching the supplied filters, oldest first.

Every filter is optional; omitted filters do not restrict the result.

    def list_orders(
        self,
        *,
        status: OrderStatus | None = None,
        customer_id: str | None = None,
        min_total: Decimal | None = None,
    ) -> list[Order]:
        """Return orders matching the supplied filters, oldest first.

        Every filter is optional; omitted filters do not restrict the result.
        """
        if min_total is not None and min_total < 0:
            raise ValueError("min_total must not be negative")

        result = list(self._orders.values())
        if status is not None:
            result = [order for order in result if order.status == status]
        if customer_id is not None:
            result = [order for order in result if order.customer_id == customer_id]
        if min_total is not None:
            result = [order for order in result if order.total >= min_total]
        return sorted(result, key=lambda order: (order.created_at, order.order_id))
```

### OrderService
source: src/orderflow/service.py:13-85
content_sha256: b85d87f244517c740179f38135f6d8075d74cd0af627985f0beae25e2d8c9b56
```python
In-memory order repository plus the operations the API exposes.

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
        min_total: Decimal | None = None,
    ) -> list[Order]:
        """Return orders matching the supplied filters, oldest first.

 
... (truncated)
```

### Order.total
source: src/orderflow/models.py:78-81
content_sha256: f1cecf23029d3e27bbef30c2f1efe74aa871effb74f229c48631d840b8ece933
```python
Payable amount for this order, before customer-tier discount.

    @property
    def total(self) -> Decimal:
        """Payable amount for this order, before customer-tier discount."""
        return self.subtotal
```

### OrderService.add_order
source: src/orderflow/service.py:26-30
content_sha256: 910c433017c2a778a0d0a30d99f191a98057928bfbc14724fefae006276f0d72
```python
def add_order(self, order: Order) -> Order:
        if order.order_id in self._orders:
            raise ValueError(f"duplicate order id: {order.order_id}")
        self._orders[order.order_id] = order
        return order
```

### OrderService.__init__
source: src/orderflow/service.py:16-20
content_sha256: a8dae9604263c4d12a94c228a7a02290de80bb42861a36544fbb058efacb75b9
```python
def __init__(self, orders: Iterable[Order] = (), ledger: StockLedger | None = None) -> None:
        self._orders: dict[str, Order] = {}
        self._ledger = ledger if ledger is not None else StockLedger()
        for order in orders:
            self.add_order(order)
```

### StockLedger
source: src/orderflow/inventory.py:11-51
content_sha256: ad79e8248234475ef76718c0cc99972688224971eab64dd3e3c5f57238d9e081
```python
Tracks on-hand and reserved quantity per SKU.

@dataclass
class StockLedger:
    """Tracks on-hand and reserved quantity per SKU."""

    on_hand: dict[str, int] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for sku, quantity in self.on_hand.items():
            if quantity < 0:
                raise ValueError(f"on_hand for {sku} must not be negative")
        for sku, quantity in self.reserved.items():
            if quantity < 0:
                raise ValueError(f"reserved for {sku} must not be negative")

    def available(self, sku: str) -> int:
        return self.on_hand.get(sku, 0) - self.reserved.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        available = self.available(sku)
        if quantity > available:
            raise InsufficientStockError(sku, quantity, available)
        self.reserved[sku] = self.reserved.get(sku, 0) + quantity

    def release(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity
... (truncated)
```

## Functional tests (must fail before, pass after)
- test_negative_min_total_is_rejected [covers SPEC-ORD-004] — tests/test_min_total_filter.py:73-75
- test_min_total_none_returns_everything [covers SPEC-ORD-004] — tests/test_min_total_filter.py:54-56
- test_min_total_filters_out_smaller_orders [covers SPEC-ORD-004] — tests/test_min_total_filter.py:43-45
- test_min_total_combines_with_status_and_customer [covers SPEC-ORD-004] — tests/test_min_total_filter.py:63-65
- test_min_total_still_respects_customer_filter [covers SPEC-ORD-004] — tests/test_min_total_filter.py:68-70
- test_min_total_above_everything_returns_empty [covers SPEC-ORD-004] — tests/test_min_total_filter.py:59-60
- test_min_total_boundary_is_inclusive [covers SPEC-ORD-004] — tests/test_min_total_filter.py:48-51
- test_min_total_is_keyword_only_and_keeps_existing_calls_working [covers SPEC-ORD-004] — tests/test_min_total_filter.py:78-83

## Regression tests (must keep passing)
- test_negative_on_hand_is_rejected — tests/test_inventory.py:44-46
- test_total_revenue_counts_placed_and_paid_only — tests/test_service.py:54-63
- test_cancel_twice_is_rejected — tests/test_service.py:47-51
- test_place_twice_is_rejected — tests/test_service.py:32-36
- test_snapshot_is_sorted_and_covers_all_skus — tests/test_inventory.py:49-51
- test_place_reserves_stock — tests/test_service.py:17-21
- test_cancel_releases_reserved_stock — tests/test_service.py:39-44
- test_place_without_stock_raises_and_leaves_order_draft — tests/test_service.py:24-29
- test_duplicate_order_id_is_rejected — tests/test_orders.py:41-43
- test_list_filters_by_customer — tests/test_orders.py:77-79
- test_list_filters_by_status — tests/test_orders.py:65-67
- test_list_combines_status_and_customer — tests/test_orders.py:82-84


## Complete current content of the files you may change


### src/orderflow/service.py
```python
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
        min_total: Decimal | None = None,
    ) -> list[Order]:
        """Return orders matching the supplied filters, oldest first.

        Every filter is optional; omitted filters do not restrict the result.
        """
        if min_total is not None and min_total < 0:
            raise ValueError("min_total must not be negative")

        result = list(self._orders.values())
        if status is not None:
            result = [order for order in result if order.status == status]
        if customer_id is not None:
            result = [order for order in result if order.customer_id == customer_id]
        if min_total is not None:
            result = [order for order in result if order.total >= min_total]
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

```


### src/orderflow/models.py
```python
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

```


### src/orderflow/inventory.py
```python
"""Stock tracking for the orderflow sample service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from orderflow.errors import InsufficientStockError


@dataclass
class StockLedger:
    """Tracks on-hand and reserved quantity per SKU."""

    on_hand: dict[str, int] = field(default_factory=dict)
    reserved: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for sku, quantity in self.on_hand.items():
            if quantity < 0:
                raise ValueError(f"on_hand for {sku} must not be negative")
        for sku, quantity in self.reserved.items():
            if quantity < 0:
                raise ValueError(f"reserved for {sku} must not be negative")

    def available(self, sku: str) -> int:
        return self.on_hand.get(sku, 0) - self.reserved.get(sku, 0)

    def reserve(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        available = self.available(sku)
        if quantity > available:
            raise InsufficientStockError(sku, quantity, available)
        self.reserved[sku] = self.reserved.get(sku, 0) + quantity

    def release(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        current = self.reserved.get(sku, 0)
        if quantity > current:
            raise ValueError(f"cannot release {quantity} of {sku}, only {current} reserved")
        self.reserved[sku] = current - quantity

    def receive(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError(f"quantity must be positive, got {quantity}")
        self.on_hand[sku] = self.on_hand.get(sku, 0) + quantity

    def snapshot(self) -> Mapping[str, int]:
        return {sku: self.available(sku) for sku in sorted(set(self.on_hand) | set(self.reserved))}

```


## Required output

Return only the JSON object described in the system prompt. The complete current content of each file you may change is included above, so you need no tools. Every entry in `changes` must hold the ENTIRE new file content — never a fragment, a diff, or a comment like 'unchanged'.