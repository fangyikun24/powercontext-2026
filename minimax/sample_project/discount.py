"""
示例业务工程：订单折扣计算器

用途：作为 MiniMax 赛道的"真实业务工程"载体。
演示的开发任务：修复边界输入 —— 折扣计算在 quantity 为负数时应返回错误而不是静默返回 0。
修改前：目标功能测试因该行为未实现而失败；
修改后：目标功能测试全部通过，回归测试不受影响。
"""


class DiscountError(ValueError):
    """折扣计算参数错误。"""


def calculate_discount(unit_price: float, quantity: int, discount_rate: float = 0.0) -> float:
    """计算订单折扣后总价。

    规格要求（见 materials/SPEC.md）：
    - unit_price 必须 > 0
    - quantity 必须 >= 1
    - discount_rate 必须在 [0, 1] 之间
    - 非法输入必须抛出 DiscountError，不得静默返回
    - 总价 = unit_price * quantity * (1 - discount_rate)

    Args:
        unit_price: 单价（> 0）
        quantity: 数量（>= 1）
        discount_rate: 折扣率（0~1，默认 0 表示无折扣）

    Returns:
        折扣后总价

    Raises:
        DiscountError: 任一参数非法时
    """
    # 修改前基线：仅校验 unit_price 与 discount_rate，缺少 quantity >= 1 检查。
    # （该缺失使 test_discount_negative_quantity / test_discount_zero_quantity 失败，
    #  由上下文系统驱动 MiniMax 生成补丁补齐 —— 见 records/DEVELOPMENT_LOG.md）
    if unit_price <= 0:
        raise DiscountError("unit_price 必须大于 0")
    if not (0 <= discount_rate <= 1):
        raise DiscountError("discount_rate 必须在 0 到 1 之间")
    return round(unit_price * quantity * (1 - discount_rate), 2)
