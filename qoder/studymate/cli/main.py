"""
StudyMate · 学习提效助手 —— CLI 入口

命令：
  studymate note add <标题> [--tags 标签] [--content 内容]   新增学习笔记
  studymate note search <关键词>                             检索笔记
  studymate weakness add <知识点> <薄弱描述>                 记录薄弱点（存入 PowerContext 记忆）
  studymate weakness list                                    列出薄弱点（记忆复用）
  studymate review <关键词>                                  复习：检索笔记 + 记忆中的薄弱点
  studymate status                                           显示记忆层与资料库状态
"""
from __future__ import annotations

import argparse
import sys

from studymate.core.kb import StudyKB
from studymate.core.memory import MemoryLayer


def cmd_note(args) -> int:
    kb = StudyKB()
    if args.sub == "add":
        n = kb.add_note(args.title, args.tags or [], args.content or "")
        print(f"✔ 笔记已保存 (#{n['id']})：{n['title']}")
        return 0
    if args.sub == "search":
        hits = kb.search(args.query, limit=args.limit)
        if not hits:
            print("未找到匹配笔记。")
            return 1
        for n in hits:
            print(f"[{n['id']}] {n['title']}  标签={','.join(n['tags'])}")
            print(f"    {n['content'][:80]}")
        return 0
    print("用法：studymate note add|search ...")
    return 1


def cmd_weakness(args) -> int:
    mem = MemoryLayer()
    if args.sub == "add":
        rid = mem.remember("weakness", f"{args.topic}：{args.description}")
        print(f"✔ 薄弱点已记入记忆（{rid}）")
        print(mem.report())
        return 0
    if args.sub == "list":
        hits = mem.search("weakness 薄弱 复习", limit=20)
        if not hits:
            print("暂无记忆中的薄弱点。")
            return 0
        print("记忆中已记录的薄弱点：")
        for i, t in enumerate(hits, 1):
            print(f"  {i}. {t}")
        return 0
    print("用法：studymate weakness add|list ...")
    return 1


def cmd_review(args) -> int:
    """复习：合并笔记检索结果 + 记忆中的薄弱点，给出复习清单。"""
    kb = StudyKB()
    mem = MemoryLayer()
    print("=== 复习清单 ===\n")
    print(f"记忆层：{mem.report()}\n")
    print("【笔记匹配】")
    hits = kb.search(args.query, limit=args.limit)
    if hits:
        for n in hits:
            print(f"  - {n['title']}（标签 {','.join(n['tags'])}）")
    else:
        print("  （无匹配笔记）")
    print("\n【记忆中相关薄弱点】")
    weaks = mem.search(f"weakness {args.query}", limit=args.limit)
    if weaks:
        for w in weaks:
            print(f"  - {w}")
    else:
        print("  （无相关薄弱点，可先用 weakness add 记录）")
    return 0


def cmd_status(args) -> int:
    kb = StudyKB()
    mem = MemoryLayer()
    print(f"笔记总数：{kb.count()}")
    print(f"资料库：{kb.path}")
    print(mem.report())
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="studymate", description="学习提效助手（Qoder 赛道作品）")
    sub = p.add_subparsers(dest="cmd", required=True)

    note = sub.add_parser("note")
    nsub = note.add_subparsers(dest="sub", required=True)
    na = nsub.add_parser("add")
    na.add_argument("title")
    na.add_argument("--tags", nargs="*", default=[])
    na.add_argument("--content", default="")
    ns = nsub.add_parser("search")
    ns.add_argument("query")
    ns.add_argument("--limit", type=int, default=5)

    weak = sub.add_parser("weakness")
    wsub = weak.add_subparsers(dest="sub", required=True)
    wa = wsub.add_parser("add")
    wa.add_argument("topic")
    wa.add_argument("description")
    wl = wsub.add_parser("list")

    rev = sub.add_parser("review")
    rev.add_argument("query")
    rev.add_argument("--limit", type=int, default=5)

    sub.add_parser("status")

    args = p.parse_args()
    handlers = {
        ("note", "add"): lambda: cmd_note(args),
        ("note", "search"): lambda: cmd_note(args),
        ("weakness", "add"): lambda: cmd_weakness(args),
        ("weakness", "list"): lambda: cmd_weakness(args),
        ("review",): lambda: cmd_review(args),
        ("status",): lambda: cmd_status(args),
    }
    key = (args.cmd,) if args.cmd in ("review", "status") else (args.cmd, args.sub)
    return handlers[key]()


if __name__ == "__main__":
    sys.exit(main())
