"""
PowerContext 状态持久化（MiniMax 赛道 · 上下文管理系统）

任务状态通过 PowerContext 保存与恢复：
- remember_memory：任务进度、当前阶段、目标、已应用补丁、测试结果
- search_memory：重启后读取最近状态，支持"从断点继续"

PowerContext 部署：
- 本地起 server（powercontext server run，默认 http://127.0.0.1:8000）
- 或使用已配置的 PowerContext 服务地址（环境变量 POWERCONTEXT_URL）
"""
from __future__ import annotations

import asyncio
import json
import os
import time

SCOPE = "project:minimax-contest"


def _try_client():
    """尝试创建 PowerContext 客户端；不可用时返回 None（降级为本地 JSON）。"""
    url = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000")
    try:
        from powercontext.client import PowerContextClient
        from powercontext.http import RememberMemoryRequest, SearchMemoryRequest

        class Wrapper:
            def __init__(self, base: str) -> None:
                self.base = base
                self._client = PowerContextClient(base)

            async def remember(self, kind: str, text: str) -> str | None:
                async with self._client as c:
                    await c.remember_memory(
                        RememberMemoryRequest(scope_id=SCOPE, kind=kind, text=text)
                    )
                return text

            async def search(self, query: str) -> list:
                async with self._client as c:
                    result = await c.search_memory(
                        SearchMemoryRequest(scope_id=SCOPE, query=query)
                    )
                return [hit.text for hit in result.hits]

        return Wrapper(url)
    except Exception:
        return None


class StateManager:
    """任务状态管理器：优先 PowerContext，缺失时降级本地 JSON（records/state.json）。"""

    def __init__(self, fallback_path: str | None = None) -> None:
        self._pc = _try_client()
        self.fallback_path = fallback_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "records", "state.json"
        )
        self.using_powercontext = self._pc is not None

    def save_state(self, state: dict) -> None:
        """保存任务状态（增量文本）。"""
        text = json.dumps(state, ensure_ascii=False)
        if self._pc:
            try:
                asyncio.run(self._pc.remember("task-state", text))
                return
            except Exception:
                pass  # 降级本地
        os.makedirs(os.path.dirname(self.fallback_path), exist_ok=True)
        with open(self.fallback_path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "state": state},
                      f, ensure_ascii=False, indent=2)

    def load_state(self) -> dict | None:
        """恢复任务状态。返回 None 表示无历史状态。"""
        if self._pc:
            try:
                hits = asyncio.run(self._pc.search("task-state latest"))
                if hits:
                    return json.loads(hits[0])
            except Exception:
                pass
        if os.path.exists(self.fallback_path):
            with open(self.fallback_path, encoding="utf-8") as f:
                return json.load(f).get("state")
        return None

    def report(self) -> str:
        return (
            f"状态存储：{'PowerContext（在线）' if self.using_powercontext else '本地 JSON（降级）'}"
            f"\n存储位置：{self.fallback_path if not self.using_powercontext else 'PowerContext scope=' + SCOPE}"
        )
