"""Task-state persistence backed by PowerContext.

PowerContext owns the durable task record: the objective, the selected context, the
planned change, the todo list and every verification result. State lives in a
PowerContext scope inside the configured relational backend (embedded **seekdb** by
default), so a freshly started process reads the same record back.

Nothing here is cached in memory across invocations — that is the whole point: the
"restart the module, keep working" acceptance item is satisfied by construction.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from sdd_context.config import Settings

TASK_KIND_PREFIX = "task-state"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class TodoItem:
    id: str
    text: str
    status: str = "pending"  # pending | done | blocked

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    command: str
    exit_code: int
    summary: str
    log_path: str
    code_version: str
    recorded_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRecord:
    """One durable SDD task record."""

    task_id: str
    project: str
    task_text: str
    status: str = "planned"  # planned | applied | verified | failed
    spec_ids: list[str] = field(default_factory=list)
    spec_sources: list[str] = field(default_factory=list)
    code_targets: list[str] = field(default_factory=list)
    functional_tests: list[str] = field(default_factory=list)
    regression_tests: list[str] = field(default_factory=list)
    context_hashes: dict[str, str] = field(default_factory=dict)
    todo: list[TodoItem] = field(default_factory=list)
    verification: list[VerificationResult] = field(default_factory=list)
    plan_summary: str = ""
    diff_path: str = ""
    applied_files: list[str] = field(default_factory=list)
    model: str = ""
    updated_at: str = field(default_factory=_now)
    saved_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project": self.project,
            "task": self.task_text,
            "status": self.status,
            "spec_ids": self.spec_ids,
            "spec_sources": self.spec_sources,
            "code_targets": self.code_targets,
            "functional_tests": self.functional_tests,
            "regression_tests": self.regression_tests,
            "context_hashes": self.context_hashes,
            "todo": [item.as_dict() for item in self.todo],
            "verification": [item.as_dict() for item in self.verification],
            "plan_summary": self.plan_summary,
            "diff_path": self.diff_path,
            "applied_files": self.applied_files,
            "model": self.model,
            "updated_at": self.updated_at,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskRecord:
        return cls(
            task_id=data["task_id"],
            project=data["project"],
            task_text=data["task"],
            status=data.get("status", "planned"),
            spec_ids=list(data.get("spec_ids") or []),
            spec_sources=list(data.get("spec_sources") or []),
            code_targets=list(data.get("code_targets") or []),
            functional_tests=list(data.get("functional_tests") or []),
            regression_tests=list(data.get("regression_tests") or []),
            context_hashes=dict(data.get("context_hashes") or {}),
            todo=[TodoItem(**item) for item in data.get("todo") or []],
            verification=[VerificationResult(**item) for item in data.get("verification") or []],
            plan_summary=data.get("plan_summary", ""),
            diff_path=data.get("diff_path", ""),
            applied_files=list(data.get("applied_files") or []),
            model=data.get("model", ""),
            updated_at=data.get("updated_at", ""),
            saved_at=data.get("saved_at", ""),
        )

    # -- derived views -----------------------------------------------------

    def done_items(self) -> list[str]:
        return [item.text for item in self.todo if item.status == "done"]

    def pending_items(self) -> list[str]:
        return [item.text for item in self.todo if item.status != "done"]

    def latest_verification(self) -> VerificationResult | None:
        return self.verification[-1] if self.verification else None


class TaskStateStore:
    """PowerContext-backed store for :class:`TaskRecord`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- runtime plumbing --------------------------------------------------

    @asynccontextmanager
    async def _runtime(self) -> Iterator[Any]:
        from powercontext.builtin.persistence.seekdb import SeekDBConfig
        from powercontext.builtin.persistence.sqlite import SQLiteConfig
        from powercontext.builtin.runtime import BuiltinConfig, open_builtin_runtime

        if self._settings.state_backend == "seekdb":
            database = SeekDBConfig(path=self._settings.state_seekdb_path)
        else:
            database = SQLiteConfig(url=self._settings.state_sqlite_url)

        scheduler = self._settings.home / "scheduler.db"
        scheduler.parent.mkdir(parents=True, exist_ok=True)
        config = BuiltinConfig(database=database)
        async with open_builtin_runtime(config, scheduler_path=str(scheduler)) as runtime:
            yield runtime

    async def _scope(self, runtime: Any, project: str) -> Any:
        from powercontext.builtin.scope import ScopeDraft

        title = f"sdd:{project}"
        try:
            return await runtime.scopes.create(
                ScopeDraft(title=title, summary="SDD task state", idempotency_key=f"sddctx:{project}")
            )
        except Exception:  # noqa: BLE001 - fall back to lookup when the key already exists
            for scope in await runtime.scopes.list():
                if getattr(scope, "title", None) == title:
                    return scope
            raise

    # -- public API --------------------------------------------------------

    async def save(self, record: TaskRecord) -> TaskRecord:
        """Persist ``record`` as a new immutable memory revision."""
        from powercontext.builtin.artifacts.atomic_memory.models import AtomicMemoryContent

        record.updated_at = _now()
        record.saved_at = _now()
        async with self._runtime() as runtime:
            scope = await self._scope(runtime, record.project)
            memory = runtime.atomic_memory.for_scope(scope.scope_id)
            await memory.create(
                (
                    AtomicMemoryContent(
                        kind=f"{TASK_KIND_PREFIX}:{record.task_id}",
                        text=json.dumps(record.as_dict(), ensure_ascii=False),
                    ),
                )
            )
        return record

    async def load(self, task_id: str, *, project: str) -> TaskRecord | None:
        """Return the most recently saved record for ``task_id``."""
        from powercontext.builtin.artifacts.atomic_memory.models import AtomicMemoryStateValue

        kind = f"{TASK_KIND_PREFIX}:{task_id}"
        async with self._runtime() as runtime:
            scope = await self._scope(runtime, project)
            memory = runtime.atomic_memory.for_scope(scope.scope_id)
            page = await memory.list()
        candidates: list[TaskRecord] = []
        for item in page.items:
            artifact = item.artifact
            if artifact.content.kind != kind:
                continue
            if item.state.state is not AtomicMemoryStateValue.ACTIVE:
                continue
            try:
                candidates.append(TaskRecord.from_dict(json.loads(artifact.content.text)))
            except (ValueError, KeyError):
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda rec: rec.saved_at)
        return candidates[-1]

    async def list_tasks(self, *, project: str) -> list[dict[str, Any]]:
        """Summarise every task recorded for ``project``."""
        from powercontext.builtin.artifacts.atomic_memory.models import AtomicMemoryStateValue

        async with self._runtime() as runtime:
            scope = await self._scope(runtime, project)
            page = runtime.atomic_memory.for_scope(scope.scope_id)
            listing = await page.list()
        latest: dict[str, TaskRecord] = {}
        for item in listing.items:
            artifact = item.artifact
            if not artifact.content.kind.startswith(f"{TASK_KIND_PREFIX}:"):
                continue
            if item.state.state is not AtomicMemoryStateValue.ACTIVE:
                continue
            try:
                record = TaskRecord.from_dict(json.loads(artifact.content.text))
            except (ValueError, KeyError):
                continue
            previous = latest.get(record.task_id)
            if previous is None or record.saved_at > previous.saved_at:
                latest[record.task_id] = record
        return [
            {
                "task_id": record.task_id,
                "status": record.status,
                "updated_at": record.updated_at,
                "specs": record.spec_ids,
                "done": record.done_items(),
                "todo": record.pending_items(),
                "verification": [
                    {"command": v.command, "exit_code": v.exit_code} for v in record.verification
                ],
            }
            for record in sorted(latest.values(), key=lambda rec: rec.task_id)
        ]

    async def scope_id(self, *, project: str) -> str:
        async with self._runtime() as runtime:
            scope = await self._scope(runtime, project)
            return scope.scope_id
