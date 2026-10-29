"""Task orchestration: ingest → context → model plan → apply → verify → persist.

The flow is deliberately explicit so that each acceptance item maps to one command:

======================  ==========================================================
``ingest``              specs/code/tests land in seekdb (or OceanBase)
``context``             retrieval produces a located development context
``task plan``           the context is handed to MiniMax, which returns the change
``task apply``          the model's change is written to the project
``task verify``         functional + regression tests run; results are recorded
``task status``         state is read back from PowerContext in a fresh process
======================  ==========================================================
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdd_context.config import Settings
from sdd_context.context import DevContext, build_context
from sdd_context.db import open_materials_database
from sdd_context.llm import LlmClient
from sdd_context.materials import IngestReport, collect_materials, project_key
from sdd_context.state import TaskRecord, TaskStateStore, TodoItem, VerificationResult

SYSTEM_PROMPT = """\
You are a senior engineer performing a spec-driven development (SDD) change.

You will receive:
- the task to perform,
- the authoritative specification entries that apply,
- the current source of the code that must change,
- the functional tests that must go from failing to passing,
- the regression tests that must keep passing.

Rules:
1. Implement exactly what the specifications require. Do not invent behaviour.
2. Do NOT modify, delete, skip or weaken any test. Tests are the acceptance criteria.
3. Do NOT change unrelated files.
4. Keep the change minimal and idiomatic for the project's existing style.
5. Every requirement that mentions a preserved behaviour must remain satisfied.
6. The COMPLETE current content of every file you may change is included in the prompt.
   You have everything you need; never reply that you cannot read files or need a tool.
   Always return at least one entry in "changes".

Respond with ONE JSON object and nothing else, using this shape:

{
  "summary": "<one paragraph describing what you changed and why>",
  "changes": [
    {"path": "<project-relative path>", "content": "<the complete new file content>"}
  ],
  "spec_coverage": [{"spec": "SPEC-...", "how": "<how the change satisfies it>"}],
  "risks": ["<anything a reviewer should double-check>"]
}
"""


class TaskFlowError(RuntimeError):
    """Raised when a task step cannot be completed."""


@dataclass
class PlanResult:
    """The parsed plan returned by the model."""

    summary: str
    changes: list[dict[str, str]]
    spec_coverage: list[dict[str, str]]
    risks: list[str]
    raw: str
    model: str
    prompt_sha256: str
    latency_ms: int


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _strip_fence(text: str) -> str:
    """Extract the JSON object from a possibly fenced model reply."""
    match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


class TaskFlow:
    """High-level SDD operations bound to one project and one settings object."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.project_dir = settings.project_dir
        self.project = project_key(self.project_dir)
        self.state = TaskStateStore(settings)

    # -- ingest ------------------------------------------------------------

    def ingest(self) -> IngestReport:
        rows = collect_materials(self.project_dir)
        if not rows:
            raise TaskFlowError(f"no materials found under {self.project_dir}")
        with open_materials_database(self.settings) as database:
            stats = database.replace_project(self.project, rows)
            counts = database.count(self.project)
        spec_ids = [row.symbol for row in rows if row.kind == "spec"]
        files: dict[str, int] = {}
        for row in rows:
            files[row.path] = files.get(row.path, 0) + 1
        report = IngestReport(project=self.project, counts=counts, files=files, spec_ids=spec_ids)
        report.as_dict()["storage"] = {"backend": self.settings.materials_db_label, **stats}
        return report

    # -- context -----------------------------------------------------------

    def build_context(self, *, task_id: str, task_text: str, task_state: dict[str, Any] | None = None) -> DevContext:
        with open_materials_database(self.settings) as database:
            context = build_context(
                database,
                task_id=task_id,
                task_text=task_text,
                project=self.project,
            )
        context.database = self.settings.materials_db_label
        if task_state is not None:
            context.task_state = task_state
        return context

    # -- plan --------------------------------------------------------------

    async def plan(self, *, task_id: str, task_text: str) -> TaskRecord:
        previous = await self.state.load(task_id, project=self.project)
        task_state = previous.as_dict() if previous else None

        context = self.build_context(task_id=task_id, task_text=task_text, task_state=task_state)
        if not context.specs:
            raise TaskFlowError(
                "no applicable specification was retrieved; check that `ingest` ran and the task names a spec"
            )

        user_prompt = self._render_prompt(context)
        client = LlmClient(self.settings)
        # MiniMax-M3 emits reasoning blocks that count towards max_tokens, so leave
        # enough room for the thinking plus the complete new file content.
        response = client.complete(system=SYSTEM_PROMPT, user=user_prompt, max_tokens=32768)
        plan = self._parse_plan(response.text, response.model, response.prompt_sha256, response.latency_ms)

        diff_dir = self.settings.artifacts_dir / "diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)
        patch_path = diff_dir / f"{task_id}.patch"
        patch_path.write_text(self._diff_for(plan.changes), encoding="utf-8", newline="\n")
        # Persist the full plan so `apply` works from a *fresh* process, not just this one.
        plan_path = self.plan_path(task_id)
        plan_path.write_text(
            json.dumps(
                {
                    "summary": plan.summary,
                    "model": plan.model,
                    "prompt_sha256": plan.prompt_sha256,
                    "latency_ms": plan.latency_ms,
                    "spec_coverage": plan.spec_coverage,
                    "risks": plan.risks,
                    "changes": plan.changes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        record = TaskRecord(
            task_id=task_id,
            project=self.project,
            task_text=task_text,
            status="planned",
            spec_ids=[item.title.split()[0] for item in context.specs],
            spec_sources=[item.locator for item in context.specs],
            code_targets=[item.locator for item in context.code_targets],
            functional_tests=[item.locator for item in context.functional_tests],
            regression_tests=[item.locator for item in context.regression_tests],
            context_hashes={item.locator: item.content_hash for item in context.specs + context.code_targets},
            todo=[
                TodoItem(id="1", text="select applicable specs, code and tests", status="done"),
                TodoItem(id="2", text="ask MiniMax for the change", status="done"),
                TodoItem(id="3", text="apply the change to the worktree", status="pending"),
                TodoItem(id="4", text="run the functional tests", status="pending"),
                TodoItem(id="5", text="run the regression tests", status="pending"),
            ],
            plan_summary=plan.summary,
            diff_path=str(patch_path.relative_to(self.settings.artifacts_dir.parent)),
            model=plan.model,
        )
        await self.state.save(record)
        return record

    def plan_path(self, task_id: str) -> Path:
        return self.settings.artifacts_dir / "diffs" / f"{task_id}.plan.json"

    def load_plan(self, task_id: str) -> dict[str, Any]:
        path = self.plan_path(task_id)
        if not path.is_file():
            raise TaskFlowError(f"no persisted plan at {path}; run `task plan` first")
        return json.loads(path.read_text(encoding="utf-8"))

    def _render_prompt(self, context: DevContext) -> str:
        parts = [context.render()]

        # The retrieval excerpt is truncated on purpose, so the model gets the complete
        # current content of every file it is allowed to rewrite.
        sources: list[str] = []
        for item in context.code_targets:
            if item.source not in sources:
                sources.append(item.source)
        if sources:
            parts.append("\n## Complete current content of the files you may change\n")
            for rel in sources:
                path = (self.project_dir / rel).resolve()
                try:
                    path.relative_to(self.project_dir.resolve())
                except ValueError:
                    continue
                if path.is_file():
                    parts.append(f"\n### {rel}\n```python\n{path.read_text(encoding='utf-8')}\n```\n")

        parts.append("\n## Required output\n")
        parts.append(
            "Return only the JSON object described in the system prompt. "
            "The complete current content of each file you may change is included above, so you "
            "need no tools. Every entry in `changes` must hold the ENTIRE new file content — "
            "never a fragment, a diff, or a comment like 'unchanged'."
        )
        return "\n".join(parts)

    @staticmethod
    def _parse_plan(text: str, model: str, prompt_sha256: str, latency_ms: int) -> PlanResult:
        payload = _strip_fence(text)
        try:
            data = json.loads(payload)
        except ValueError as error:
            raise TaskFlowError(f"model did not return valid JSON: {error}\n---\n{text[:2000]}") from error
        changes = data.get("changes")
        if not isinstance(changes, list) or not changes:
            raise TaskFlowError("model returned no file changes")
        for change in changes:
            if not isinstance(change, dict) or "path" not in change or "content" not in change:
                raise TaskFlowError(f"malformed change entry: {change!r}")
        return PlanResult(
            summary=str(data.get("summary", "")),
            changes=[{"path": str(c["path"]), "content": str(c["content"])} for c in changes],
            spec_coverage=[
                {"spec": str(item.get("spec", "")), "how": str(item.get("how", ""))}
                for item in data.get("spec_coverage") or []
                if isinstance(item, dict)
            ],
            risks=[str(item) for item in data.get("risks") or []],
            raw=text,
            model=model,
            prompt_sha256=prompt_sha256,
            latency_ms=latency_ms,
        )

    def _diff_for(self, changes: list[dict[str, str]]) -> str:
        chunks: list[str] = []
        for change in changes:
            path = self.project_dir / change["path"]
            before = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.is_file() else []
            after = change["content"].splitlines(keepends=True)
            chunks.extend(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{change['path']}",
                    tofile=f"b/{change['path']}",
                )
            )
        return "".join(chunks)

    # -- apply -------------------------------------------------------------

    async def apply(self, *, task_id: str) -> TaskRecord:
        record = await self.state.load(task_id, project=self.project)
        if record is None:
            raise TaskFlowError(f"no recorded task {task_id!r}; run `task plan` first")
        plan = self.load_plan(task_id)

        applied: list[str] = []
        for change in plan["changes"]:
            target = (self.project_dir / change["path"]).resolve()
            if not str(target).startswith(str(self.project_dir.resolve())):
                raise TaskFlowError(f"refusing to write outside the project: {change['path']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Force LF: the model returns "\n", and letting Python translate it would
            # make the applied file differ from its snapshot by line endings alone.
            target.write_text(change["content"].replace("\r\n", "\n"), encoding="utf-8", newline="\n")
            applied.append(change["path"])

        record.status = "applied"
        record.applied_files = applied
        for item in record.todo:
            if item.id == "3":
                item.status = "done"
        await self.state.save(record)
        return record

    # -- verify ------------------------------------------------------------

    async def verify(
        self,
        *,
        task_id: str,
        functional_targets: list[str] | None = None,
        regression_targets: list[str] | None = None,
    ) -> TaskRecord:
        record = await self.state.load(task_id, project=self.project)
        if record is None:
            raise TaskFlowError(f"no recorded task {task_id!r}; run `task plan` first")

        logs = self.settings.artifacts_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)

        functional = functional_targets or ["tests/test_min_total_filter.py"]
        regression = regression_targets or [
            "tests/test_orders.py",
            "tests/test_pricing.py",
            "tests/test_inventory.py",
            "tests/test_service.py",
        ]

        for label, targets, todo_id in (
            ("functional", functional, "4"),
            ("regression", regression, "5"),
        ):
            result = self._run_pytest(targets)
            log_path = logs / f"{task_id}-{label}.log"
            log_path.write_text(self._format_log(label, targets, result), encoding="utf-8", newline="\n")
            record.verification.append(
                VerificationResult(
                    command=result["command"],
                    exit_code=result["exit_code"],
                    summary=f"{label}: {result['summary']}",
                    log_path=str(log_path.relative_to(self.settings.artifacts_dir.parent)),
                    code_version=self._code_version(),
                )
            )
            for item in record.todo:
                if item.id == todo_id:
                    item.status = "done" if result["exit_code"] == 0 else "blocked"

        all_passed = all(v.exit_code == 0 for v in record.verification)
        record.status = "verified" if all_passed else "failed"
        await self.state.save(record)
        return record

    def _run_pytest(self, targets: list[str]) -> dict[str, Any]:
        command = [sys.executable, "-m", "pytest", "-q", *targets]
        completed = subprocess.run(  # noqa: S603 - fixed command, no shell
            command,
            cwd=str(self.project_dir),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        summary = ""
        for line in reversed(output.strip().splitlines()):
            stripped = line.strip()
            if "passed" in stripped or "failed" in stripped or "error" in stripped:
                summary = stripped.strip("= ")
                break
        return {
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "summary": summary or "no summary line",
            "output": output,
        }

    def _format_log(self, label: str, targets: list[str], result: dict[str, Any]) -> str:
        return (
            f"# Test run — {label}\n"
            f"timestamp: {_now()}\n"
            f"command: {result['command']}\n"
            f"cwd: {self.project_dir}\n"
            f"targets: {', '.join(targets)}\n"
            f"code_version: {self._code_version()}\n"
            f"exit_code: {result['exit_code']}\n"
            f"summary: {result['summary']}\n"
            f"\n--- output ---\n{result['output']}"
        )

    def _code_version(self) -> str:
        """Best-effort code version marker without requiring git."""
        files = sorted((self.project_dir / "src").rglob("*.py"))
        import hashlib

        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(self.project_dir).as_posix().encode())
            digest.update(path.read_bytes())
        return f"sha256:{digest.hexdigest()[:16]}"

    # -- status ------------------------------------------------------------

    async def status(self, *, task_id: str) -> dict[str, Any]:
        record = await self.state.load(task_id, project=self.project)
        if record is None:
            raise TaskFlowError(f"no recorded task {task_id!r} in PowerContext")
        scope = await self.state.scope_id(project=self.project)
        return {
            "powercontext_scope": scope,
            "task_id": record.task_id,
            "status": record.status,
            "task": record.task_text,
            "specs": record.spec_ids,
            "spec_sources": record.spec_sources,
            "code_targets": record.code_targets,
            "functional_tests": record.functional_tests,
            "regression_tests": record.regression_tests,
            "done": record.done_items(),
            "todo": record.pending_items(),
            "verification": [
                {
                    "command": item.command,
                    "exit_code": item.exit_code,
                    "summary": item.summary,
                    "log": item.log_path,
                    "recorded_at": item.recorded_at,
                }
                for item in record.verification
            ],
            "plan_summary": record.plan_summary,
            "diff": record.diff_path,
            "applied_files": record.applied_files,
            "model": record.model,
            "updated_at": record.updated_at,
        }

    async def list_tasks(self) -> list[dict[str, Any]]:
        return await self.state.list_tasks(project=self.project)
