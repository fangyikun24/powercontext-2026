"""
StudyMate · 记忆层（PowerContext 接入）

任务状态 / 学习薄弱点通过 PowerContext 保存与复用（赛题必用技术）。

接入方式：PowerContext HTTP API（方式不限，此处选 HTTP 直连）。
两种模式：
1. PowerContext server（默认）：env POWERCONTEXT_URL（默认 http://127.0.0.1:8000）
   使用 POST /v1/context/prepare、/v1/memory/remember、/v1/memory/search
   （实际端点以 powercontext 的 /openapi.json 为准，本项目对端点做容错适配）
2. 本地 SQLite（降级，无需第三方依赖）：std 库 sqlite3 持久化，保证任何环境可运行

记忆内容：学习过程中的薄弱知识点（kind=weakness）、复习计划（kind=review）、
任务进度（kind=task-state）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Optional

import urllib.request
import urllib.error

SCOPE = "project:studymate"


class MemoryLayer:
    """记忆层：优先 PowerContext HTTP，不可用时降级本地 SQLite。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.pc_url = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        self.sqlite_path = os.path.join(self.data_dir, "studymate.sqlite3")
        self._sqlite_ready = False
        self.mode = "powercontext" if self._ping() else "sqlite"

    # ---------- 探测 ----------
    def _ping(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.pc_url}/health/ready", timeout=2)
            with urllib.request.urlopen(req) as r:
                return r.status == 200
        except Exception:
            return False

    # ---------- 内部：HTTP 调用 ----------
    def _http_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.pc_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}

    # ---------- 内部：SQLite ----------
    def _ensure_sqlite(self) -> None:
        if self._sqlite_ready:
            return
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT, kind TEXT, text TEXT, created TEXT
            )"""
        )
        conn.commit()
        conn.close()
        self._sqlite_ready = True

    # ---------- 写入 ----------
    def remember(self, kind: str, text: str) -> str:
        """保存一条记忆，返回记忆标识。"""
        if self.mode == "powercontext":
            try:
                # 优先 v1/memory/remember；兼容 /v1/context/prepare 语义
                try:
                    return str(self._http_json("POST", "/v1/memory/remember", {
                        "scope_id": SCOPE, "kind": kind, "text": text,
                    }))
                except urllib.error.HTTPError:
                    # 端点名不同：尝试 /v1/memories
                    self._http_json("POST", "/v1/memories", {
                        "scope_id": SCOPE, "kind": kind, "text": text,
                    })
                    return "memory-recorded"
            except Exception:
                pass  # 降级 sqlite
        self._ensure_sqlite()
        conn = sqlite3.connect(self.sqlite_path)
        conn.execute(
            "INSERT INTO memory (scope, kind, text, created) VALUES (?,?,?,?)",
            (SCOPE, kind, text, time.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return f"sqlite:{rid}"

    # ---------- 检索 ----------
    def search(self, query: str, limit: int = 5) -> list[str]:
        """按语义/关键词检索记忆，返回文本列表。"""
        if self.mode == "powercontext":
            try:
                try:
                    res = self._http_json("POST", "/v1/memory/search", {
                        "scope_id": SCOPE, "query": query, "limit": limit,
                    })
                except urllib.error.HTTPError:
                    res = self._http_json("GET", "/v1/memories", {"scope_id": SCOPE})
                hits = res.get("hits") or res.get("memories") or []
                texts = []
                for h in hits:
                    if isinstance(h, dict):
                        texts.append(h.get("text") or h.get("content") or "")
                    else:
                        texts.append(str(h))
                return [t for t in texts if t][:limit]
            except Exception:
                pass  # 降级 sqlite
        self._ensure_sqlite()
        conn = sqlite3.connect(self.sqlite_path)
        rows = conn.execute(
            "SELECT text FROM memory WHERE scope=? ORDER BY id DESC LIMIT ?",
            (SCOPE, limit),
        ).fetchall()
        conn.close()
        # 简单关键词打分：query 词命中越多越靠前
        terms = [t for t in query.lower().split() if len(t) > 1]
        scored = []
        for (text,) in rows:
            score = sum(1 for t in terms if t in text.lower())
            scored.append((score, text))
        scored.sort(key=lambda x: -x[0])
        return [t for _, t in scored][:limit]

    # ---------- 报告 ----------
    def report(self) -> str:
        return f"记忆层模式：{self.mode}（{'PowerContext ' + self.pc_url if self.mode == 'powercontext' else '本地 SQLite ' + self.sqlite_path}）"
