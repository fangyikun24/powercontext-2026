# Order Management Specification

本规格描述订单查询与状态流转的**可验收要求**。实现必须与本文一致；本文是唯一权威来源。

## 1. 范围

适用于 `orderflow.service.OrderService`。不涉及定价（见 `specs/pricing.md`）与库存记账
（见 `specs/inventory.md`），但状态流转会调用库存预留。

## 2. 需求条目

### SPEC-ORD-001 — 订单创建与唯一性

- **状态**: accepted
- **接口**: `OrderService.add_order(order) -> Order`
- **要求**: 相同 `order_id` 不得重复加入，重复时必须抛出 `ValueError`。
- **要求**: `order_id` 与 `customer_id` 不允许为空白字符串。

### SPEC-ORD-002 — 按状态筛选

- **状态**: accepted
- **接口**: `OrderService.list_orders(status=None) -> list[Order]`
- **要求**: `status` 为 `None` 时返回全部订单；否则只返回 `order.status == status` 的订单。
- **要求**: 结果按 `(created_at, order_id)` 升序排列，保证输出稳定可回归。

### SPEC-ORD-003 — 按客户筛选

- **状态**: accepted
- **接口**: `OrderService.list_orders(customer_id=None) -> list[Order]`
- **要求**: `customer_id` 为 `None` 时不限制；否则只返回该客户的订单。
- **要求**: 与 `status` 同时给出时按**逻辑与**组合。

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
