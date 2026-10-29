"""StudyMate seekdb 参考实现（本地可运行，Windows 已验证）。

- 嵌入式 seekdb 存储笔记与错题
- ngram 中文全文索引 + 科目结构化过滤
- 复习记录写回，统计薄弱科目
- 标准库 HTTP 服务 + 静态页面，无第三方 Web 框架
"""

from __future__ import annotations

import json
import os
import shutil
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pymysql
import pylibseekdb

def _default_data_dir() -> str:
    if os.name == "nt":
        return r"C:\Users\Public\StudyMateData\seekdb"
    return "/tmp/studymate-seekdb"


DATA_DIR = os.environ.get("STUDYMATE_SEEKDB_DIR", _default_data_dir())
PORT = int(os.environ.get("STUDYMATE_PORT", "8787"))
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

NOTES = [
    ("边际效用递减", "边际效用递减规律是指随着某种物品的连续消费，消费者从每一额外单位消费中获得的满足感会逐渐减少。企业常用折扣促销来鼓励多买。", "经济学", "效用,定价,需求"),
    ("需求价格弹性", "需求价格弹性衡量价格变化对需求量的影响。必需品弹性小，奢侈品弹性大，降价策略要结合弹性判断。", "经济学", "弹性,定价"),
    ("导数四则运算", "两个函数乘积的导数等于前导后不导加上前不导后导。复合函数使用链式法则，由外向内逐层求导。", "数学", "导数,链式法则"),
    ("定积分换元法", "定积分换元时，积分上下限要随变量一起替换；被积函数和微分都要换成新变量，最后不必回代。", "数学", "积分,换元"),
    ("考研英语长难句", "长难句先找主谓宾，再处理定语从句和状语从句。把插入语先括起来，句子主干就清楚了。", "英语", "语法,阅读"),
    ("艾宾浩斯复习节奏", "间隔重复按 1 天、3 天、7 天、14 天安排复习，在遗忘发生前重新激活记忆，比集中突击更省时间。", "方法", "记忆,复习"),
    ("政治选择题排除法", "先排除表述绝对化和与题干无关的选项，再在剩余选项中比较主体和范围，注意偷换概念。", "政治", "选择题,排除法"),
    ("错题归因三问", "每道错题记录三件事：考哪个知识点、为什么错、下次怎么避免。只抄答案不写归因，复习价值很低。", "方法", "错题,复盘"),
]

QUESTIONS = [
    ("数学", "求函数 f(x) = x²e^x 的导数", "f'(x) = 2xe^x", "f'(x) = e^x(x² + 2x)", "乘积求导法则", 3, 2),
    ("数学", "求 ∫(2x+1)dx", "x² + 1", "x² + x + C", "不定积分与常数 C", 2, 1),
    ("经济学", "边际效用递减说明什么", "消费越多总效用越低", "连续消费同种物品时，新增一单位带来的满足感递减", "边际效用", 2, 2),
    ("英语", "The book ___ on the desk is mine.", "lays", "lying", "现在分词作定语", 3, 1),
    ("政治", "实践是检验真理的唯一标准，是因为", "实践具有直接现实性", "实践能把主观认识与客观实际联系起来", "实践与认识", 1, 0),
    ("方法", "错题本最应该记录什么", "正确答案", "知识点、错因和改进动作", "错题归因", 2, 2),
]


def connect():
    os.makedirs(os.path.dirname(DATA_DIR) or ".", exist_ok=True)
    instance = pylibseekdb.open(DATA_DIR)
    options = instance.connection_options()
    conn = pymysql.connect(
        database="test",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        **options,
    )
    return instance, conn


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = {list(row.values())[0] for row in cur.fetchall()}
        if {"notes", "questions", "review_log"} <= tables:
            return False

        cur.execute("DROP TABLE IF EXISTS review_log")
        cur.execute("DROP TABLE IF EXISTS questions")
        cur.execute("DROP TABLE IF EXISTS notes")

        cur.execute(
            """
            CREATE TABLE notes (
                id INT AUTO_INCREMENT PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                subject VARCHAR(50) NOT NULL,
                tags VARCHAR(200),
                FULLTEXT INDEX ft_notes (content) WITH PARSER ngram
            ) ORGANIZATION = HEAP
            """
        )
        cur.execute(
            """
            CREATE TABLE questions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                subject VARCHAR(50) NOT NULL,
                question TEXT NOT NULL,
                wrong_answer VARCHAR(500),
                correct_answer VARCHAR(500),
                knowledge_point VARCHAR(200),
                attempts INT NOT NULL DEFAULT 0,
                correct_count INT NOT NULL DEFAULT 0,
                FULLTEXT INDEX ft_questions (question) WITH PARSER ngram
            ) ORGANIZATION = HEAP
            """
        )
        cur.execute(
            """
            CREATE TABLE review_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                question_id INT NOT NULL,
                correct TINYINT NOT NULL,
                reviewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ORGANIZATION = HEAP
            """
        )

        cur.executemany(
            "INSERT INTO notes (title, content, subject, tags) VALUES (%s,%s,%s,%s)",
            NOTES,
        )
        cur.executemany(
            """INSERT INTO questions
               (subject, question, wrong_answer, correct_answer, knowledge_point, attempts, correct_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            QUESTIONS,
        )
        return True


def search_notes(conn, q, subject):
    sql = (
        "SELECT id, title, subject, content, MATCH(content) AGAINST(%s) AS score "
        "FROM notes WHERE MATCH(content) AGAINST(%s)"
    )
    args = [q, q]
    if subject:
        sql += " AND subject = %s"
        args.append(subject)
    sql += " ORDER BY score DESC LIMIT 10"
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def search_questions(conn, q, subject):
    sql = (
        "SELECT id, subject, question, wrong_answer, correct_answer, knowledge_point, "
        "attempts, correct_count, MATCH(question) AGAINST(%s) AS score "
        "FROM questions WHERE MATCH(question) AGAINST(%s)"
    )
    args = [q, q]
    if subject:
        sql += " AND subject = %s"
        args.append(subject)
    sql += " ORDER BY score DESC LIMIT 10"
    with conn.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def review_question(conn, question_id, correct):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE questions SET attempts = attempts + 1, "
            "correct_count = correct_count + %s WHERE id = %s",
            (1 if correct else 0, question_id),
        )
        cur.execute(
            "INSERT INTO review_log (question_id, correct) VALUES (%s, %s)",
            (question_id, 1 if correct else 0),
        )
        cur.execute(
            "SELECT id, question, attempts, correct_count FROM questions WHERE id = %s",
            (question_id,),
        )
        return cur.fetchone()


def stats(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM notes")
        notes = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM questions")
        questions = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM review_log")
        reviews = cur.fetchone()["c"]
        cur.execute(
            "SELECT subject, SUM(attempts) AS attempts, SUM(correct_count) AS correct "
            "FROM questions GROUP BY subject ORDER BY attempts DESC"
        )
        by_subject = cur.fetchall()
    for row in by_subject:
        attempts = int(row["attempts"] or 0)
        correct = int(row["correct"] or 0)
        row["attempts"] = attempts
        row["correct"] = correct
        row["accuracy"] = round(correct / attempts * 100, 1) if attempts else None
    return {
        "notes": notes,
        "questions": questions,
        "reviews": reviews,
        "by_subject": by_subject,
    }


class Handler(BaseHTTPRequestHandler):
    conn = None

    def log_message(self, fmt, *args):  # 安静一点，避免中文路径乱码
        pass

    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            path = os.path.join(STATIC_DIR, "index.html")
            with open(path, "rb") as fh:
                self._send(200, fh.read(), "text/html; charset=utf-8")
            return

        if parsed.path == "/api/health":
            self._send(200, {"ok": True, "engine": "seekdb"})
            return

        if parsed.path == "/api/stats":
            self._send(200, {"engine": "seekdb", **stats(self.conn)})
            return

        if parsed.path in ("/api/search", "/api/questions"):
            q = (query.get("q") or [""])[0].strip()
            subject = (query.get("subject") or [""])[0].strip()
            if not q:
                self._send(400, {"error": "缺少查询词 q"})
                return
            started = time.perf_counter()
            try:
                if parsed.path == "/api/search":
                    rows = search_notes(self.conn, q, subject)
                    key = "notes"
                else:
                    rows = search_questions(self.conn, q, subject)
                    key = "questions"
            except Exception as exc:  # 返回可读错误，便于排查
                self._send(500, {"error": str(exc)[:300]})
                return
            took_ms = round((time.perf_counter() - started) * 1000, 2)
            self._send(
                200,
                {
                    "engine": "seekdb",
                    "query": q,
                    "subject": subject or None,
                    "took_ms": took_ms,
                    "count": len(rows),
                    key: rows,
                },
            )
            return

        self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/review":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            question_id = int(payload["question_id"])
            correct = bool(payload.get("correct"))
        except Exception:
            self._send(400, {"error": "请求体需要 question_id 与 correct"})
            return
        row = review_question(self.conn, question_id, correct)
        if not row:
            self._send(404, {"error": "题目不存在"})
            return
        self._send(200, {"engine": "seekdb", "question": row})


def main():
    instance, conn = connect()
    created = init_schema(conn)
    Handler.conn = conn
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[seekdb] data dir: {DATA_DIR}")
    print(f"[seekdb] initialized: {created}")
    print(f"[server] http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
        instance.close()


if __name__ == "__main__":
    main()
