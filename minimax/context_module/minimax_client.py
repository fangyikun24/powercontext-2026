"""
MiniMax 调用模块（MiniMax 赛道 · 上下文管理系统）

通过 MiniMax API 生成代码补丁，完成任务上下文描述的开发任务。

配置（环境变量）：
- MINIMAX_API_KEY   必填
- MINIMAX_MODEL     默认 glm-4.5 类模型（MiniMax 平台模型名以平台为准，可用环境变量覆盖）
- MINIMAX_BASE_URL  默认 https://api.minimax.io/v1（OpenAI 兼容端点；请以平台文档为准）
"""
from __future__ import annotations

import os

import requests


class MiniMaxClient:
    def __init__(self) -> None:
        self.api_key = os.environ.get("MINIMAX_API_KEY", "")
        self.model = os.environ.get("MINIMAX_MODEL", "MiniMax-Text-01")
        self.base_url = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
        self.mock = os.environ.get("MOCK", "").lower() in ("1", "true", "yes")
        if not self.api_key and not self.mock:
            raise RuntimeError("缺少 MINIMAX_API_KEY 环境变量（或设置 MOCK=1 使用演示模式）")

    def _mock_patch(self) -> str:
        """演示模式：返回确定性补丁（模拟 MiniMax 的修复输出，完整文件内容）。"""
        return '''"""
示例业务工程：订单折扣计算器

用途：作为 MiniMax 赛道的“真实业务工程”载体。
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
    """
    if unit_price <= 0:
        raise DiscountError("unit_price 必须大于 0")
    if quantity < 1:
        raise DiscountError("quantity 必须大于等于 1")
    if not (0 <= discount_rate <= 1):
        raise DiscountError("discount_rate 必须在 0 到 1 之间")
    return round(unit_price * quantity * (1 - discount_rate), 2)
'''

    def generate_patch(self, context: dict, instruction: str) -> str:
        """基于上下文生成代码修改补丁（以统一 diff 形式返回）。

        Args:
            context: 上下文组装器的输出（含 task/retrieved/context_text）。
            instruction: 附加指令（如"只修改目标函数，保持其他不变"）。

        Returns:
            生成的补丁文本（unified diff 或代码块）。
        """
        if self.mock:
            return self._mock_patch()
        prompt = (
            f"{context['context_text']}\n\n"
            f"# 指令\n{instruction}\n\n"
            "# 输出要求\n"
            "请给出对目标工程的最小修改，以 unified diff 格式输出。"
            "diff 必须包含足够上下文（行号或 @@ 片段），且只修改目标文件。"
        )
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是严谨的代码工程师，输出最小可用修改。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
