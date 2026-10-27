"""
StudyMate · 学习资料库

管理学习笔记（标题/标签/内容），提供轻量全文检索。
可选用 seekdb 做向量/全文混合检索（环境变量 STUDY_KEEP_KV=1 时不依赖 seekdb，
纯本地检索；配置 SEEKDB_HOST 后自动启用 seekdb 增强）。
"""
from __future__ import annotations

import json
import os
import re


class StudyKB:
    """本地学习笔记库（JSON 文件持久化 + 轻量检索）。"""

    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
        )
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "notes.json")
        self.notes: list[dict] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.notes = json.load(f)

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.notes, f, ensure_ascii=False, indent=2)

    def add_note(self, title: str, tags: list[str], content: str) -> dict:
        note = {
            "id": len(self.notes) + 1,
            "title": title,
            "tags": tags,
            "content": content,
            "created": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        }
        self.notes.append(note)
        self._save()
        return note

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """全文检索：query 的词在标题/内容/标签中命中计分。"""
        terms = [t for t in query.lower().split() if len(t) > 1]
        scored = []
        for n in self.notes:
            hay = " ".join([n["title"], " ".join(n.get("tags", [])), n["content"]]).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, n))
        scored.sort(key=lambda x: (-x[0], -x[1]["id"]))
        return [n for _, n in scored][:limit]

    def list_all(self) -> list[dict]:
        return list(reversed(self.notes))

    def count(self) -> int:
        return len(self.notes)
