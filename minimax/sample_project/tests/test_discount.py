"""订单折扣计算器的单元测试。

包含：
- 回归测试（已通过）
- 目标功能测试 test_discount_negative_quantity（**修改前失败、修改后通过**）

运行：python -m pytest tests/test_discount.py -v
"""
import pytest

from discount import calculate_discount, DiscountError


# ---------- 回归测试（基线，修改前后都必须通过） ----------

def test_normal_discount():
    """正常折扣：10 件单价 5 元，8 折 → 40.0"""
    assert calculate_discount(5.0, 10, 0.2) == 40.0


def test_zero_discount():
    """无折扣：默认 discount_rate=0 → 原价总价"""
    assert calculate_discount(3.5, 2) == 7.0


def test_full_discount():
    """满折扣：1 折后总价 → 10%"""
    assert calculate_discount(100.0, 1, 0.9) == 10.0


def test_invalid_unit_price():
    """单价非法（<=0）应抛 DiscountError"""
    with pytest.raises(DiscountError):
        calculate_discount(0, 5)


def test_invalid_discount_rate():
    """折扣率非法（>1）应抛 DiscountError"""
    with pytest.raises(DiscountError):
        calculate_discount(10.0, 1, 1.5)


# ---------- 目标功能测试（修改前失败，修改后通过） ----------

def test_discount_negative_quantity():
    """数量为负数（-3）时必须抛 DiscountError，不得静默返回。

    规格要求：quantity 必须 >= 1，非法输入必须抛错。
    修改前实现缺失该检查 → 本测试失败；
    修改后实现补齐该检查 → 本测试通过。
    """
    with pytest.raises(DiscountError):
        calculate_discount(5.0, -3, 0.2)


def test_discount_zero_quantity():
    """数量为 0 时同样非法，必须抛 DiscountError。"""
    with pytest.raises(DiscountError):
        calculate_discount(5.0, 0, 0.2)
