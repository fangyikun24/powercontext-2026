# -*- coding: utf-8 -*-
"""
PowerContext 记忆服务 · 一键验证脚本（官方 Python SDK）

运行前提：已部署官方 PowerContext Server（见 run_powercontext.py / README.md）：
    pip install "powercontext[cli,builtin]"
    powercontext server run --host 127.0.0.1 --port 8000

本脚本通过官方 SDK（from powercontext.client import PowerContextClient）真实调用
PowerContext 的 remember_memory / search_memory 两个接口，输出即 VALIDATION.md 引用的真实运行证据。
"""
import asyncio
import sys

from powercontext.client import PowerContextClient
from powercontext.http import RememberMemoryRequest, SearchMemoryRequest

BASE = "http://127.0.0.1:8000"
SCOPE = "project:dify-idea-engine"


async def main() -> None:
    print(f"== 连接官方 PowerContext Server: {BASE} ==")
    async with PowerContextClient(BASE) as client:
        print("\n=== 1. remember_memory：保存脑洞记忆 ===")
        samples = [
            "主题：会飞的冰箱 生成：1.冷链快递员 2.空中菜市场 3.冰箱地铁",
            "主题：周一的早晨 生成：1.赖床缓冲器 2.咖啡胶囊舱 3.通勤悬浮舱",
        ]
        for text in samples:
            resp = await client.remember_memory(
                RememberMemoryRequest(scope_id=SCOPE, kind="idea", text=text)
            )
            print(f"remember_memory -> records={resp.records}")

        print("\n=== 2. search_memory：检索相关记忆（记忆复用） ===")
        resp = await client.search_memory(
            SearchMemoryRequest(scope_id=SCOPE, query="会飞的冰箱", limit=3)
        )
        print(f"search_memory('会飞的冰箱') -> hits={len(resp.records)}")
        for r in resp.records:
            print(f"  {getattr(r, 'artifact', '')} {getattr(r, 'content', '')[:60]}")

        print("\n=== 3. search_memory：相近主题续写检索 ===")
        resp = await client.search_memory(
            SearchMemoryRequest(scope_id=SCOPE, query="冰箱 快递", limit=3)
        )
        print(f"search_memory('冰箱 快递') -> hits={len(resp.records)}")
        for r in resp.records:
            print(f"  {getattr(r, 'artifact', '')} {getattr(r, 'content', '')[:60]}")

    print("\n全部通过 ✅")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ModuleNotFoundError as e:
        print(f"[error] 缺少依赖: {e}. 请先执行 pip install \"powercontext[cli,builtin]\"", file=sys.stderr)
        raise SystemExit(2)
