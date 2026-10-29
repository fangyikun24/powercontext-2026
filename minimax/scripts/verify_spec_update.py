"""Prove the context follows an edited specification instead of returning a fixed answer.

Runs three phases and prints a machine-checkable summary:

1. ingest the project as committed, snapshot the SPEC-ORD-004 hash and excerpt;
2. edit ``specs/orders.md`` (add a new normative clause), re-ingest, rebuild the context;
3. restore the original spec and re-ingest.

The check passes only when the retrieved spec content changes with the file and the new
clause is actually present in the context handed to the model.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from sdd_context.context import build_context
from sdd_context.config import Settings
from sdd_context.db import open_materials_database
from sdd_context.materials import collect_materials, project_key

TASK = (
    "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders "
    "whose total is at least min_total are returned; negative min_total must be rejected"
)
SPEC_FILE = "specs/orders.md"
SPEC_ID = "SPEC-ORD-004"
NEW_CLAUSE = "- **要求**: 当 `min_total` 为 `Decimal(\"0\")` 时必须返回全部未取消订单（新增试验条款）。"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def ingest(settings: Settings) -> dict[str, object]:
    project = project_key(settings.project_dir)
    rows = collect_materials(settings.project_dir)
    with open_materials_database(settings) as database:
        stats = database.replace_project(project, rows)
        counts = database.count(project)
    return {"project": project, "stats": stats, "counts": counts}


def node(settings: Settings) -> tuple[str, str]:
    """Return (content_hash, excerpt) of the retrieved SPEC-ORD-004 context item."""
    with open_materials_database(settings) as database:
        context = build_context(
            database,
            task_id="SPEC-UPDATE-CHECK",
            task_text=TASK,
            project=project_key(settings.project_dir),
        )
    for item in context.specs:
        if item.title.startswith(SPEC_ID):
            return item.content_hash, item.excerpt
    return "", ""


def main() -> int:
    settings = Settings.from_env(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    spec_path = settings.project_dir / SPEC_FILE
    original = spec_path.read_text(encoding="utf-8")
    results: dict[str, object] = {}

    try:
        ingest(settings)
        hash_before, excerpt_before = node(settings)
        results["before"] = {"hash": hash_before, "has_clause": NEW_CLAUSE in excerpt_before}

        # Edit the spec, keeping a valid markdown requirement block.
        edited = original.replace(
            "- **兼容性**: 该参数必须是**仅关键字**参数，且默认 `None`，保证既有调用方不受影响。",
            "- **兼容性**: 该参数必须是**仅关键字**参数，且默认 `None`，保证既有调用方不受影响。\n" + NEW_CLAUSE,
        )
        if edited == original:
            print("FAIL: could not locate the anchor line to edit")
            return 1
        spec_path.write_text(edited, encoding="utf-8")

        ingest(settings)
        hash_after, excerpt_after = node(settings)
        results["after"] = {"hash": hash_after, "has_clause": NEW_CLAUSE in excerpt_after}
    finally:
        spec_path.write_text(original, encoding="utf-8")
        ingest(settings)
        hash_restored, excerpt_restored = node(settings)
        results["restored"] = {"hash": hash_restored, "has_clause": NEW_CLAUSE in excerpt_restored}

    ok = (
        results["before"]["hash"] != results["after"]["hash"]
        and results["after"]["has_clause"]
        and results["restored"]["hash"] == results["before"]["hash"]
        and not results["restored"]["has_clause"]
    )
    print(f"spec_id      : {SPEC_ID}")
    print(f"before       : {results['before']}")
    print(f"after edit   : {results['after']}")
    print(f"after restore: {results['restored']}")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} — context content follows the specification file")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
