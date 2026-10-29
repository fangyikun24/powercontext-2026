"""Verify the PowerContext task-state round trip across separate processes."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sdd_context.config import Settings
from sdd_context.state import TaskRecord, TaskStateStore, TodoItem, VerificationResult


async def main() -> int:
    mode = sys.argv[1]
    settings = Settings.from_env(Path(sys.argv[2]))
    store = TaskStateStore(settings)
    project = settings.project_dir.name

    if mode == "save":
        record = TaskRecord(
            task_id="SDD-ORD-004",
            project=project,
            task_text="add min_total filter to OrderService.list_orders",
            status="planned",
            spec_ids=["SPEC-ORD-004"],
            spec_sources=["specs/orders.md:33-43"],
            code_targets=["src/orderflow/service.py:38-53"],
            functional_tests=["tests/test_min_total_filter.py:43-45"],
            regression_tests=["tests/test_orders.py:60-62"],
            todo=[
                TodoItem(id="1", text="select context", status="done"),
                TodoItem(id="2", text="apply change", status="pending"),
            ],
        )
        await store.save(record)
        print(f"saved task {record.task_id} in scope {await store.scope_id(project=project)}")
        return 0

    record = await store.load("SDD-ORD-004", project=project)
    if record is None:
        print("FAIL: no record found after restart")
        return 1
    print(f"loaded task {record.task_id} status={record.status}")
    print(f"  specs={record.spec_ids} sources={record.spec_sources}")
    print(f"  code={record.code_targets}")
    print(f"  done={record.done_items()} todo={record.pending_items()}")
    print(f"  saved_at={record.saved_at}")
    tasks = await store.list_tasks(project=project)
    print(f"  listed={tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
