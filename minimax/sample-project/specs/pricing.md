# Pricing Specification

本规格描述订单金额与客户等级折扣的计算口径。

## 1. 范围

适用于 `orderflow.models` 的金额类型与 `orderflow.pricing` 的折扣规则。

## 2. 需求条目

### SPEC-PRC-001 — 金额精度

- **状态**: accepted
- **要求**: 所有对外金额使用 `Decimal`，保留两位小数。
- **要求**: 舍入方式为 `ROUND_HALF_UP`（商业四舍五入）。
- **要求**: 行小计 `line.subtotal = unit_price * quantity`，按上述规则量化。

### SPEC-PRC-002 — 订单小计与总额

- **状态**: accepted
- **接口**: `Order.subtotal`、`Order.total`
- **要求**: `subtotal` 为所有行小计之和，两位小数。
- **要求**: `total` 在本版本中等于 `subtotal`（折扣由 `pricing.order_total` 在展示层施加）。

### SPEC-PRC-003 — 客户等级折扣

- **状态**: accepted
- **接口**: `pricing.discount_rate(tier, subtotal) -> Decimal`
- **要求**: `standard` 无折扣。
- **要求**: `silver` 在 `subtotal >= 100.00` 时享 5% 折扣。
- **要求**: `gold` 在 `subtotal >= 50.00` 时享 5%，在 `subtotal >= 200.00` 时享 10%。
- **要求**: 同一等级命中多个门槛时取**折扣率最高**的一条（不是叠加）。

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
