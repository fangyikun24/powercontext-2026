"""
StudyMate · 记忆层（官方 PowerContext SDK 接入）

通过 OceanBase 官方 PowerContext 1.4.x 的 Python SDK 保存/检索学习记忆：

    from powercontext.client import PowerContextClient
    from powercontext.http import RememberMemoryRequest, SearchMemoryRequest

依赖（见 requirements.txt）：
    pip install "powercontext[cli,builtin]>=1.4"

官方 Server 部署（等价 powercontext server run --host 127.0.0.1 --port 8000）：
    python -m powercontext.server.cli run --host 127.0.0.1 --port 8000
    或使用项目内 server/run_powercontext.py 启动封装

记忆内容：学习过程中的薄弱知识点（kind=weakness）、复习计划（kind=review）、
任务进度（kind=task-state）。全部经官方 PowerContext 保存，语义检索复用。
"""
from __future__ import annotations

import asyncio
import os

SCOPE = "project:studymate"


class MemoryLayer:
    """记忆层：官方 PowerContext SDK 接入（唯一路径，无 SQLite 降级）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.pc_url = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
        self.scope = SCOPE

    # ---------- 官方 SDK 调用 ----------
    def _run(self, coro):
        return asyncio.run(coro)

    async def _remember(self, kind: str, text: str):
        from powercontext.client import PowerContextClient
        from powercontext.http import RememberMemoryRequest

        async with PowerContextClient(self.pc_url) as client:
            return await client.remember_memory(
                RememberMemoryRequest(scope_id=self.scope, kind=kind, text=text)
            )

    async def _search(self, query: str, limit: int):
        from powercontext.client import PowerContextClient
        from powercontext.http import SearchMemoryRequest

        async with PowerContextClient(self.pc_url) as client:
            return await client.search_memory(
                SearchMemoryRequest(scope_id=self.scope, query=query, limit=limit)
            )

    # ---------- 写入 ----------
    def remember(self, kind: str, text: str) -> str:
        """保存一条记忆到官方 PowerContext，返回记忆标识。"""
        resp = self._run(self._remember(kind, text))
        if not resp.records:
            raise RuntimeError("PowerContext 未返回写入记录")
        return str(resp.records[0].artifact)

    # ---------- 检索 ----------
    def search(self, query: str, limit: int = 5) -> list[str]:
        """官方 PowerContext 语义检索记忆，返回文本列表。"""
        resp = self._run(self._search(query, limit))
        return [h.memory.text for h in resp.hits][:limit]

    # ---------- 报告 ----------
    def report(self) -> str:
        return (
            f"记忆层：官方 PowerContext SDK（{self.pc_url}，scope={self.scope}）"
        )
