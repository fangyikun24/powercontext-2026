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

为了便于评审一键复现，本模块会在首次使用时探测并自动拉起官方 Server
（仅在 health 检查失败时启动；已有 Server 不会被重复启动）。

记忆内容：学习过程中的薄弱知识点（kind=weakness）、复习计划（kind=review）、
任务进度（kind=task-state）。全部经官方 PowerContext 保存，语义检索复用。
"""
from __future__ import annotations

import asyncio
import atexit
import os
import shutil
import subprocess
import sys
import time
import urllib.request

SCOPE = "project:studymate"
_SERVER_PROC = None


def _server_alive(url: str) -> bool:
    for path in ("/health/live", "/health/ready"):
        try:
            with urllib.request.urlopen(url + path, timeout=0.8) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            continue
    return False


def _stop_server() -> None:
    global _SERVER_PROC
    if _SERVER_PROC is not None:
        try:
            _SERVER_PROC.terminate()
            _SERVER_PROC.wait(timeout=5)
        except Exception:
            pass
        _SERVER_PROC = None


def _server_command() -> list[str]:
    """定位官方 powercontext 命令：优先同解释器目录下的 console script。"""
    args = ["server", "run", "--host", "127.0.0.1", "--port", "8000"]
    exe_name = "powercontext.exe" if os.name == "nt" else "powercontext"
    adjacent = os.path.join(os.path.dirname(sys.executable), exe_name)
    if os.path.isfile(adjacent):
        return [adjacent, *args]
    found = shutil.which("powercontext")
    if found:
        return [found, *args]
    # 兜底：用当前解释器调用 console entry 的 main()（等价于 powercontext 命令）
    return [sys.executable, "-c", "from powercontext.cli.app import main; main()", *args]


class MemoryLayer:
    """记忆层：官方 PowerContext SDK 接入（唯一路径，无 SQLite 降级）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.pc_url = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
        self.scope = SCOPE
        self._ensure_server()

    # ---------- 自动拉起官方 Server（便于一键复现） ----------
    def _ensure_server(self) -> None:
        global _SERVER_PROC
        if _server_alive(self.pc_url):
            return
        cmd = _server_command()
        try:
            _SERVER_PROC = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            return
        atexit.register(_stop_server)
        deadline = time.time() + 90
        while time.time() < deadline:
            if _server_alive(self.pc_url):
                return
            if _SERVER_PROC.poll() is not None:
                return
            time.sleep(1)

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
