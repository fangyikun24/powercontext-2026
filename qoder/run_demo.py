"""StudyMate seekdb 一键验收（无需启动 HTTP 服务，评审可直接运行）。

    cd qoder
    pip install -r requirements.txt
    python run_demo.py

依次验证：中文全文检索（笔记/错题）、科目过滤、复习写回、统计。
数据目录可用 STUDYMATE_SEEKDB_DIR 覆盖（默认 Windows 为 C:\\Users\\Public\\StudyMateData\\seekdb，
Linux/macOS 为 /tmp/studymate-seekdb）。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "backend"))

import server as be  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} · {detail}")


def main() -> int:
    print(f"数据目录：{be.DATA_DIR}")
    instance, conn = be.connect()
    try:
        created = be.init_schema(conn)
        print(f"初始化：{'建表并写入 8 条笔记 / 6 道错题' if created else '复用已有数据'}")

        notes = be.search_notes(conn, "边际效用", "")
        check(
            "seekdb 中文全文检索（笔记）",
            len(notes) > 0 and "score" in notes[0],
            f"命中 {len(notes)} 条，首条《{notes[0]['title'] if notes else '无'}》"
            f" score={notes[0]['score'] if notes else '无'}",
        )

        questions = be.search_questions(conn, "导数", "")
        check(
            "seekdb 中文全文检索（错题）",
            len(questions) > 0 and "score" in questions[0],
            f"命中 {len(questions)} 条，首条「{questions[0]['question'] if questions else '无'}」",
        )

        math_hits = be.search_questions(conn, "导数", "数学")
        english_hits = be.search_questions(conn, "导数", "英语")
        check(
            "科目过滤下推到 seekdb",
            len(math_hits) > 0 and len(english_hits) == 0,
            f"subject=数学 {len(math_hits)} 条 / subject=英语 {len(english_hits)} 条",
        )

        before = be.stats(conn)
        target = questions[0]
        row = be.review_question(conn, target["id"], True)
        check(
            "复习动作写回数据库",
            row["attempts"] == target["attempts"] + 1,
            f"attempts {target['attempts']} → {row['attempts']}",
        )

        after = be.stats(conn)
        check(
            "review_log 增加 1 条",
            after["reviews"] == before["reviews"] + 1,
            f"reviews {before['reviews']} → {after['reviews']}",
        )
        check(
            "分科目正确率统计",
            len(after["by_subject"]) > 0,
            " / ".join(
                f"{r['subject']} {r['attempts']}次 正确率{r['accuracy']}%"
                for r in after["by_subject"]
            ),
        )
    finally:
        conn.close()
        instance.close()

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n共 {len(results)} 项，失败 {len(failed)} 项")
    if failed:
        print("FAIL：seekdb 验收未通过，请检查上方失败项")
        return 1
    print("PASS：seekdb 检索 / 过滤 / 复习写回 / 统计全部可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
