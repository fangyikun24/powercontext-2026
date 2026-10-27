# 订单折扣计算器 · 规格说明（SPEC）

**模块**：discount.py — calculate_discount

## 功能
计算订单折扣后总价。

## 输入
| 参数 | 类型 | 约束 |
|---|---|---|
| unit_price | float | 必须 > 0 |
| quantity | int | 必须 >= 1 |
| discount_rate | float | 必须在 [0, 1] 之间，默认 0.0 |

## 输出
- 合法输入：返回 `round(unit_price * quantity * (1 - discount_rate), 2)`
- 非法输入：抛出 `DiscountError`（`ValueError` 子类），**禁止静默返回**

## 边界与错误语义
1. `unit_price <= 0` → DiscountError
2. `quantity < 1`（包括 0 和负数）→ DiscountError
3. `discount_rate < 0 或 > 1` → DiscountError
4. 任何参数非法时，函数不得返回数值或退出码 0 之外的结果

## 验收标准
- 目标测试 `test_discount_negative_quantity`（数量为负数时抛错）必须通过
- 回归测试（正常折扣、满折扣、价格校验）不受影响
