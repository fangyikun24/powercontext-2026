"""
上下文组装器（MiniMax 赛道 · 上下文管理系统）

核心流程：任务描述 → 从 seekdb 检索相关工程资料 → 组装为结构化上下文
（规格 / 代码 / 测试 三类，均带来源标注）→ 交给 MiniMax 生成补丁。

关键性质（对应赛题要求）：
- 输出上下文必须包含规格、代码、测试的来源（来源=seekdb 检索结果，非凭空拼接）；
- 规格更新后（如 materials/SPEC.md 变化并重新入库存），下一次检索会带回新内容，
  输出随之更新 —— 证明数据库真实参与，而非静态模板。
"""
from __future__ import annotations

import json


class ContextAssembler:
    """把任务描述与检索到的资料组装为结构化上下文。"""

    def __init__(self, store) -> None:
        self.store = store

    def assemble(self, task: str, query_embedding: list[float],
                 query_text: str | None = None, limit: int = 4) -> dict:
        """组装上下文。

        Args:
            task: 要交给 MiniMax 的开发任务描述。
            query_embedding: 任务语义向量（用于在 seekdb 中检索资料）。
            query_text: 可选的全文关键词（增强检索）。
            limit: 每类资料最多选取条数。

        Returns:
            结构化上下文 dict：
            {
              "task": ...,
              "retrieved": [...],   # 带来源的资料条目（含 kind/title/id/text/score）
              "context_text": ...   # 拼好的上下文文本（含来源标注）
            }
        """
        hits = self.store.search(query_embedding=query_embedding,
                                 query_text=query_text, limit=limit)

        # 按类整理（规格/代码/测试），保留来源
        by_kind: dict[str, list[dict]] = {"spec": [], "code": [], "test": []}
        for hit in hits:
            kind = hit.get("kind", "")
            if kind in by_kind:
                by_kind[kind].append(hit)

        sections = []
        sections.append(f"# 开发任务\n{task}")
        for kind, label in (("spec", "规格（来源：seekdb material SPEC）"),
                            ("code", "代码（来源：seekdb material CODE）"),
                            ("test", "测试（来源：seekdb material TEST）")):
            items = by_kind.get(kind, [])
            if not items:
                continue
            block = [f"## {label}"]
            for it in items:
                block.append(
                    f"[{it['id']}] ({it.get('title', '')}, score={it.get('score')})"
                )
                block.append(it.get("text", ""))
            sections.append("\n".join(block))

        context_text = "\n\n".join(sections)
        return {
            "task": task,
            "retrieved": hits,
            "context_text": context_text,
        }

    def to_json(self, ctx: dict) -> str:
        return json.dumps(ctx, ensure_ascii=False, indent=2)
