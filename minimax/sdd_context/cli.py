"""Command-line entry point for the SDD context module."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sdd_context.config import Settings
from sdd_context.taskflow import TaskFlow, TaskFlowError


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_context(flow: TaskFlow, task_id: str, task_text: str, *, as_json: bool) -> int:
    context = flow.build_context(task_id=task_id, task_text=task_text)
    if as_json:
        _emit(context.as_dict(), as_json=True)
        return 0
    print(context.render())
    print("\n--- located sources ---")
    print(json.dumps(_sources(context), ensure_ascii=False, indent=2))
    return 0


def _sources(context) -> dict[str, list[str]]:
    return {
        "specs": [item.locator for item in context.specs],
        "code": [item.locator for item in context.code_targets],
        "functional_tests": [item.locator for item in context.functional_tests],
        "regression_tests": [item.locator for item in context.regression_tests],
    }


async def _run_async(args: argparse.Namespace, flow: TaskFlow) -> int:
    if args.command == "plan":
        record = await flow.plan(task_id=args.task_id, task_text=args.task)
        _emit(
            {
                "task_id": record.task_id,
                "status": record.status,
                "model": record.model,
                "specs": record.spec_ids,
                "code_targets": record.code_targets,
                "functional_tests": record.functional_tests,
                "regression_tests": record.regression_tests,
                "diff": record.diff_path,
                "plan": record.plan_summary,
                "todo": [item.as_dict() for item in record.todo],
            },
            as_json=args.json,
        )
        return 0

    if args.command == "apply":
        record = await flow.apply(task_id=args.task_id)
        _emit(
            {
                "task_id": record.task_id,
                "status": record.status,
                "applied_files": record.applied_files,
                "diff": record.diff_path,
            },
            as_json=args.json,
        )
        return 0

    if args.command == "verify":
        record = await flow.verify(task_id=args.task_id)
        _emit(
            {
                "task_id": record.task_id,
                "status": record.status,
                "verification": [item.as_dict() for item in record.verification],
            },
            as_json=args.json,
        )
        return 0 if record.status == "verified" else 1

    if args.command == "status":
        payload = await flow.status(task_id=args.task_id)
        _emit(payload, as_json=args.json)
        return 0

    if args.command == "list":
        _emit(await flow.list_tasks(), as_json=True)
        return 0

    raise TaskFlowError(f"unknown command {args.command!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdd_context",
        description="Spec-driven development context manager (seekdb/OceanBase + PowerContext + MiniMax).",
    )
    parser.add_argument("--project", type=Path, default=None, help="project directory (default: sample-project)")
    parser.add_argument("--home", type=Path, default=None, help="state directory (default: ./state)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="import specs, code and tests into the database")
    ingest.add_argument("--json", action="store_true")

    context = sub.add_parser("context", help="build the development context for a task")
    context.add_argument("--task", required=True, help="natural-language task description")
    context.add_argument("--task-id", default="TASK-001")
    context.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="validate configuration and show resolved settings")
    doctor.add_argument("--json", action="store_true")

    task = sub.add_parser("task", help="task lifecycle: plan / apply / verify / status / list")
    task_sub = task.add_subparsers(dest="action", required=True)

    plan = task_sub.add_parser("plan", help="retrieve context and ask the model for the change")
    plan.add_argument("--task-id", required=True)
    plan.add_argument("--task", required=True)
    plan.add_argument("--json", action="store_true")

    apply_cmd = task_sub.add_parser("apply", help="write the planned change to the project")
    apply_cmd.add_argument("--task-id", required=True)
    apply_cmd.add_argument("--json", action="store_true")

    verify = task_sub.add_parser("verify", help="run functional and regression tests")
    verify.add_argument("--task-id", required=True)
    verify.add_argument("--json", action="store_true")

    status = task_sub.add_parser("status", help="read the task record back from PowerContext")
    status.add_argument("--task-id", required=True)
    status.add_argument("--json", action="store_true")

    listing = task_sub.add_parser("list", help="list recorded tasks")
    listing.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "task":
        args.command = args.action

    project = args.project
    settings = Settings.from_env(project)
    if args.home is not None:
        session_home = args.home.resolve()
        settings = Settings(**{**settings.__dict__, "home": session_home})

    flow = TaskFlow(settings)

    try:
        if args.command == "doctor":
            payload = {
                "project": str(settings.project_dir),
                "home": str(settings.home),
                "materials_backend": settings.materials_backend,
                "materials_seekdb_path": str(settings.materials_seekdb_path),
                "oceanbase_url_set": bool(settings.oceanbase_url),
                "state_backend": settings.state_backend,
                "llm_provider": settings.llm_provider,
                "llm_model": settings.minimax_model if settings.llm_provider == "minimax" else settings.deepseek_model,
                "llm_key_set": bool(
                    settings.minimax_api_key if settings.llm_provider == "minimax" else settings.deepseek_api_key
                ),
                "problems": settings.validate(),
                "llm_problems": settings.llm_problems(),
            }
            _emit(payload, as_json=args.json)
            return 0 if not payload["problems"] else 1

        if args.command == "ingest":
            report = flow.ingest()
            _emit(report.as_dict(), as_json=args.json)
            return 0

        if args.command == "context":
            return _print_context(flow, args.task_id, args.task, as_json=args.json)

        return asyncio.run(_run_async(args, flow))
    except TaskFlowError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
