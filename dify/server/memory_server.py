# -*- coding: utf-8 -*-
"""
PowerContext 最小兼容记忆服务（Dify 赛道作品配套）

实现 OceanBase PowerContext HTTP API 中的两个记忆端点，供 Dify 工作流
（idea_engine.yml 的 http-request 节点）在本地调用：

  POST /v1/memory/remember  保存一条记忆
  POST /v1/memory/search    按 query 检索该 scope 下的相关记忆

请求/响应字段对齐官方 OpenAPI 合同：
  remember: body {scope_id, kind, text} -> records[{artifact, content, state, state_version}]
  search:   body {scope_id, query, limit} -> records[{artifact, content, score}]

存储：SQLite（单文件 memory.db，utf-8），仅标准库，无第三方依赖。
运行：python memory_server.py （默认 http://127.0.0.1:8000）

Dify 工作流无需插件：HTTP 节点 POST 到上述两个端点即可完成
「生成前检索历史脑洞、生成后保存本次脑洞」的记忆闭环。
"""

import json
import re
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

DB_PATH = "memory.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'idea',
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope_id)")


def simple_rank(query, text):
    """极简关键词计分：命中词越多分越高（仅用于本地演示）。"""
    q = re.sub(r"\s+", " ", query or "").strip().lower()
    if not q:
        return 0.0
    words = [w for w in q.split(" ") if w]
    if not words:
        return 0.0
    t = text.lower()
    hit = sum(1 for w in words if w in t)
    return round(hit / len(words), 4)


class MemoryHandler(BaseHTTPRequestHandler):
    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-PowerContext-Request-ID", "req-local")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/health/live", "/health/ready"):
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": {"code": "not_found", "message": path}})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self._read_json()
        except Exception as e:  # noqa: BLE001
            self._send(422, {"error": {"code": "invalid_request", "message": str(e)}})
            return

        scope_id = data.get("scope_id", "")
        if not scope_id:
            self._send(422, {"error": {"code": "invalid_request", "message": "scope_id required"}})
            return

        if path == "/v1/memory/remember":
            kind = data.get("kind", "idea")
            text = data.get("text", "")
            if not text:
                self._send(422, {"error": {"code": "invalid_request", "message": "text required"}})
                return
            with get_conn() as conn:
                cur = conn.execute(
                    "INSERT INTO memories (scope_id, kind, text, created_at) VALUES (?,?,?, datetime('now'))",
                    (scope_id, kind, text),
                )
                artifact = f"memory-{cur.lastrowid}"
            self._send(
                200,
                {
                    "records": [
                        {
                            "artifact": artifact,
                            "content": text,
                            "state": "active",
                            "state_version": 1,
                        }
                    ]
                },
            )
        elif path == "/v1/memory/search":
            query = data.get("query", "")
            limit = int(data.get("limit") or 5)
            with get_conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE scope_id=? ORDER BY id DESC LIMIT ?",
                    (scope_id, limit * 5),
                ).fetchall()
            ranked = []
            for r in rows:
                score = simple_rank(query, r["text"])
                ranked.append(
                    {
                        "artifact": f"memory-{r['id']}",
                        "content": r["text"],
                        "score": score,
                    }
                )
            ranked.sort(key=lambda x: x["score"], reverse=True)
            self._send(200, {"records": ranked[:limit]})
        else:
            self._send(404, {"error": {"code": "not_found", "message": path}})

    def log_message(self, fmt, *args):
        print("[server]", fmt % args)


def main():
    init_db()
    server = HTTPServer(("127.0.0.1", 8000), MemoryHandler)
    print("PowerContext-compatible memory server running on http://127.0.0.1:8000")
    print("Endpoints: POST /v1/memory/remember | POST /v1/memory/search | GET /health/live")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopped.")


if __name__ == "__main__":
    main()
