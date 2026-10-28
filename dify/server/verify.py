# -*- coding: utf-8 -*-
"""
PowerContext 记忆服务 · 一键验证脚本
运行：python verify.py （需先启动 memory_server.py）
输出即 VALIDATION.md 中引用的真实运行证据。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
SCOPE = "project:dify-idea-engine"


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return resp.status, json.loads(resp.read().decode("utf-8"))


def get(path):
    resp = urllib.request.urlopen(BASE + path, timeout=10)
    return resp.status, json.loads(resp.read().decode("utf-8"))


def main():
    print("=== 0. 健康检查 ===")
    st, body = get("/health/live")
    print(f"GET /health/live -> {st} {json.dumps(body, ensure_ascii=False)}")

    print("\n=== 1. remember：保存脑洞记忆 ===")
    samples = [
        "主题：会飞的冰箱 生成：1.冷链快递员 2.空中菜市场 3.冰箱地铁",
        "主题：周一的早晨 生成：1.赖床缓冲器 2.咖啡胶囊舱 3.通勤悬浮舱",
    ]
    for text in samples:
        st, body = post(
            "/v1/memory/remember",
            {"scope_id": SCOPE, "kind": "idea", "text": text},
        )
        print(
            f"POST /v1/memory/remember -> {st} "
            + json.dumps(body, ensure_ascii=False)
        )

    print("\n=== 2. search：检索相关记忆（记忆复用） ===")
    st, body = post(
        "/v1/memory/search",
        {"scope_id": SCOPE, "query": "会飞的冰箱", "limit": 3},
    )
    print(f"POST /v1/memory/search -> {st}")
    for r in body.get("records", []):
        print(
            f"  [score={r.get('score', 0):.4f}] "
            f"{r.get('content', '')[:60]}"
        )

    print("\n=== 3. search：相近主题续写检索（第二次查询） ===")
    st, body = post(
        "/v1/memory/search",
        {"scope_id": SCOPE, "query": "冰箱 快递", "limit": 3},
    )
    print(f"POST /v1/memory/search -> {st}")
    for r in body.get("records", []):
        print(
            f"  [score={r.get('score', 0):.4f}] "
            f"{r.get('content', '')[:60]}"
        )


if __name__ == "__main__":
    main()
