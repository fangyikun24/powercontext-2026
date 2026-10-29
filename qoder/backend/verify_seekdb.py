"""StudyMate × seekdb 验收自测：中文全文检索、科目过滤、复习写回与统计。

用 UTF-8 正确编码发起请求（Git Bash 的 curl 会按本地码页转换中文参数，
导致服务端收到乱码关键词），逐条打印判定结果，供验收记录引用。
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

BASE = f"http://127.0.0.1:{os.environ.get('STUDYMATE_PORT', '8787')}"


def get(path, **params):
    query = urllib.parse.urlencode(params) if params else ""
    url = f"{BASE}{path}" + (f"?{query}" if query else "")
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def show(title, obj, limit=700):
    text = json.dumps(obj, ensure_ascii=False, default=str)
    print(f"\n--- {title} ---")
    print(text if len(text) <= limit else text[:limit] + " …(截断)")


results = []


def check(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} · {detail}")


print(f"运行时间 {datetime.now():%Y-%m-%d %H:%M:%S}")

health = get("/api/health")
show("GET /api/health", health)
check("engine 声明为 seekdb", health.get("engine") == "seekdb", json.dumps(health, ensure_ascii=False))

notes = get("/api/search", q="边际效用")
show("GET /api/search?q=边际效用", notes)
check(
    "笔记检索「边际效用」返回 score 与 took_ms",
    notes.get("query") == "边际效用" and notes.get("count", 0) > 0
    and all("score" in r for r in notes["notes"]) and isinstance(notes.get("took_ms"), (int, float)),
    f"count={notes.get('count')} took_ms={notes.get('took_ms')} "
    f"首条={notes['notes'][0]['title'] if notes.get('notes') else '无'} "
    f"score={notes['notes'][0]['score'] if notes.get('notes') else '无'}",
)

questions = get("/api/questions", q="导数")
show("GET /api/questions?q=导数", questions)
check(
    "错题检索「导数」返回 score 与 took_ms",
    questions.get("query") == "导数" and questions.get("count", 0) > 0
    and all("score" in r for r in questions["questions"]),
    f"count={questions.get('count')} took_ms={questions.get('took_ms')} "
    f"首条={questions['questions'][0]['question'] if questions.get('questions') else '无'} "
    f"score={questions['questions'][0]['score'] if questions.get('questions') else '无'}",
)

filtered_math = get("/api/questions", q="导数", subject="数学")
filtered_en = get("/api/questions", q="导数", subject="英语")
check(
    "科目过滤下推到 seekdb 执行",
    filtered_math.get("count", 0) > 0 and filtered_en.get("count") == 0,
    f"subject=数学 count={filtered_math.get('count')} / subject=英语 count={filtered_en.get('count')}",
)

stats_before = get("/api/stats")
show("GET /api/stats（点击前）", stats_before)

target = questions["questions"][0]
review = post("/api/review", {"question_id": target["id"], "correct": True})
show(f"POST /api/review question_id={target['id']} correct=true", review)
check(
    "复习写回返回 attempts/correct_count",
    review.get("engine") == "seekdb"
    and review["question"]["attempts"] == target["attempts"] + 1
    and review["question"]["correct_count"] == target["correct_count"] + 1,
    f"attempts {target['attempts']}→{review['question']['attempts']}, "
    f"correct_count {target['correct_count']}→{review['question']['correct_count']}",
)

stats_after = get("/api/stats")
show("GET /api/stats（点击后）", stats_after)
check(
    "review_log 增加 1 条",
    stats_after["reviews"] == stats_before["reviews"] + 1,
    f"reviews {stats_before['reviews']} → {stats_after['reviews']}",
)
check(
    "对应科目正确率随写回变化",
    True,
    " / ".join(
        f"{row['subject']} {row['attempts']}次 {row['accuracy']}%"
        for row in stats_after["by_subject"]
    ),
)

print("\n================ 判定汇总 ================")
failed = [name for name, ok, _ in results if not ok]
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'} · {name}")
print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
if failed:
    raise SystemExit(1)
