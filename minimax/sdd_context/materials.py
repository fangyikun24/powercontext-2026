"""Ingest a project's engineering materials (specs, code, tests) into the database.

Materials are stored at *atomic* granularity so that a retrieved context can point at a
single requirement or a single symbol rather than a whole file:

===========  ==========================================================================
kind         granularity
===========  ==========================================================================
``spec``     one ``### SPEC-...`` requirement block from ``specs/*.md``
``code``     one module (``symbol == ""``) and one row per class/function/method
``test``     one ``def test_*`` function from ``tests/test_*.py``
===========  ==========================================================================
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from sdd_context.db import MaterialRow

_SPEC_HEADING = re.compile(r"^(#{2,4})\s+(SPEC-[A-Z]+-\d+)\s*[—:-]?\s*(.*)$", re.MULTILINE)
_COVERS = re.compile(r"covers\s*:\s*([A-Z]+-[A-Z]+-\d+(?:\s*,\s*[A-Z]+-[A-Z]+-\d+)*)", re.IGNORECASE)
_SPEC_ID = re.compile(r"SPEC-[A-Z]+-\d+")


@dataclass
class IngestReport:
    project: str
    counts: dict[str, int]
    files: dict[str, int] = field(default_factory=dict)
    spec_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "counts": self.counts,
            "files": self.files,
            "spec_ids": self.spec_ids,
        }


# ---------------------------------------------------------------------------
# specs
# ---------------------------------------------------------------------------


def parse_specs(spec_dir: Path, *, project_root: Path) -> list[MaterialRow]:
    """Split markdown specs into one material per ``SPEC-...`` requirement heading."""
    rows: list[MaterialRow] = []
    if not spec_dir.is_dir():
        return rows
    for path in sorted(spec_dir.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(project_root).as_posix()
        headings = list(_SPEC_HEADING.finditer(text))
        for index, match in enumerate(headings):
            spec_id = match.group(2)
            title = (match.group(3) or "").strip() or spec_id
            start_offset = match.start()
            end_offset = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            # Stop at the next heading of the same or higher level that is not a SPEC block.
            body = text[start_offset:end_offset].rstrip()
            start_line = text.count("\n", 0, start_offset) + 1
            end_line = start_line + body.count("\n")
            rows.append(
                MaterialRow(
                    kind="spec",
                    path=rel,
                    symbol=spec_id,
                    start_line=start_line,
                    end_line=end_line,
                    title=f"{spec_id} {title}".strip(),
                    body=body,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# code
# ---------------------------------------------------------------------------


def _segment(lines: list[str], node: ast.AST) -> str:
    start = (getattr(node, "decorator_list", None) or [node])[0].lineno
    end = getattr(node, "end_lineno", node.lineno)
    return "\n".join(lines[start - 1 : end])


def parse_code(source_dir: Path, *, project_root: Path) -> list[MaterialRow]:
    """Extract one material per module and one per top-level symbol (plus methods)."""
    rows: list[MaterialRow] = []
    if not source_dir.is_dir():
        return rows
    for path in sorted(source_dir.rglob("*.py")):
        rel = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        # Module name is relative to the import root (``src``), not to the project root.
        module_path = path.relative_to(source_dir).as_posix().removesuffix(".py")
        module = module_path.replace("/", ".")
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        elif module == "__init__":
            module = ""
        rows.append(
            MaterialRow(
                kind="code",
                path=rel,
                symbol="",
                start_line=1,
                end_line=max(len(lines), 1),
                title=f"module {module}",
                body=text,
            )
        )
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                rows.append(_symbol_row(rel, module, node, lines, prefix=""))
            elif isinstance(node, ast.ClassDef):
                rows.append(_symbol_row(rel, module, node, lines, prefix=""))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        rows.append(_symbol_row(rel, module, child, lines, prefix=f"{node.name}."))
    return rows


def _symbol_row(
    rel: str,
    module: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    lines: list[str],
    *,
    prefix: str,
) -> MaterialRow:
    body = _segment(lines, node)
    end_line = getattr(node, "end_lineno", node.lineno)
    start_line = (getattr(node, "decorator_list", None) or [node])[0].lineno
    doc = ast.get_docstring(node) or ""
    return MaterialRow(
        kind="code",
        path=rel,
        symbol=f"{module}.{prefix}{node.name}",
        start_line=start_line,
        end_line=end_line,
        title=f"{prefix}{node.name}",
        body=(doc + "\n\n" + body).strip(),
    )


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def parse_tests(test_dir: Path, *, project_root: Path) -> list[MaterialRow]:
    """Extract one material per test function, tagging the specs it covers."""
    rows: list[MaterialRow] = []
    if not test_dir.is_dir():
        return rows
    for path in sorted(test_dir.rglob("test_*.py")):
        rel = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        covered = sorted(set(_SPEC_ID.findall(" ".join(_COVERS.findall(text))))) if _COVERS.search(text) else []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            body = _segment(lines, node)
            start_line = (getattr(node, "decorator_list", None) or [node])[0].lineno
            end_line = getattr(node, "end_lineno", node.lineno)
            tag = f" [covers {', '.join(covered)}]" if covered else ""
            rows.append(
                MaterialRow(
                    kind="test",
                    path=rel,
                    symbol=node.name,
                    start_line=start_line,
                    end_line=end_line,
                    title=f"{node.name}{tag}",
                    body=body,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def collect_materials(project_root: Path) -> list[MaterialRow]:
    """Read every spec, source and test file of ``project_root``."""
    rows: list[MaterialRow] = []
    rows.extend(parse_specs(project_root / "specs", project_root=project_root))
    rows.extend(parse_code(project_root / "src", project_root=project_root))
    rows.extend(parse_tests(project_root / "tests", project_root=project_root))
    return rows


def project_key(project_root: Path) -> str:
    """Stable project identifier used as the tenant key in the material table."""
    return project_root.resolve().name
