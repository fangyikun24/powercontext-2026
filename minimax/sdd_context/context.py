"""Turn a development task into an actionable development context.

The builder does not answer from memory and does not hard-code any answer: every field
is produced by querying the material table built from the project's own files, so
re-importing an edited spec changes the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sdd_context.db import MaterialDatabase, SearchHit

_SPEC_ID = re.compile(r"SPEC-[A-Z]+-\d+")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass
class ContextItem:
    """One located source that belongs in the task context."""

    kind: str
    source: str
    locator: str
    title: str
    excerpt: str
    content_hash: str
    score: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "locator": self.locator,
            "title": self.title,
            "content_hash": self.content_hash,
            "score": round(self.score, 4),
            "reason": self.reason,
            "excerpt": self.excerpt,
        }


@dataclass
class DevContext:
    """The complete context handed to the development assistant."""

    task_id: str
    task_text: str
    project: str
    specs: list[ContextItem] = field(default_factory=list)
    code_targets: list[ContextItem] = field(default_factory=list)
    functional_tests: list[ContextItem] = field(default_factory=list)
    regression_tests: list[ContextItem] = field(default_factory=list)
    task_state: dict[str, Any] | None = None
    queries: list[str] = field(default_factory=list)
    database: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task": self.task_text,
            "project": self.project,
            "database": self.database,
            "queries": self.queries,
            "specs": [item.as_dict() for item in self.specs],
            "code_targets": [item.as_dict() for item in self.code_targets],
            "functional_tests": [item.as_dict() for item in self.functional_tests],
            "regression_tests": [item.as_dict() for item in self.regression_tests],
            "task_state": self.task_state,
        }

    # -- rendering ---------------------------------------------------------

    def render(self, *, max_excerpt: int = 1600) -> str:
        """Render the context as the prompt payload for the model."""
        out: list[str] = []
        out.append(f"# Development context for task {self.task_id}")
        out.append("")
        out.append(f"Task: {self.task_text}")
        out.append("")

        out.append("## Applicable specifications")
        if not self.specs:
            out.append("(none retrieved)")
        for item in self.specs:
            out.append(f"### {item.title}")
            out.append(f"source: {item.locator}")
            out.append(f"content_sha256: {item.content_hash}")
            out.append("```markdown")
            out.append(item.excerpt[:max_excerpt])
            out.append("```")
            out.append("")

        out.append("## Code to change")
        if not self.code_targets:
            out.append("(none retrieved)")
        for item in self.code_targets:
            out.append(f"### {item.title}")
            out.append(f"source: {item.locator}")
            out.append(f"content_sha256: {item.content_hash}")
            out.append("```python")
            out.append(item.excerpt[:max_excerpt])
            out.append("```")
            out.append("")

        out.append("## Functional tests (must fail before, pass after)")
        if not self.functional_tests:
            out.append("(none retrieved)")
        for item in self.functional_tests:
            out.append(f"- {item.title} — {item.locator}")
        out.append("")

        out.append("## Regression tests (must keep passing)")
        if not self.regression_tests:
            out.append("(none retrieved)")
        for item in self.regression_tests:
            out.append(f"- {item.title} — {item.locator}")
        out.append("")

        if self.task_state:
            out.append("## Recorded task state")
            out.append("```json")
            out.append(_pretty(self.task_state))
            out.append("```")
            out.append("")
        return "\n".join(out)


def _pretty(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)


def _excerpt(body: str, limit: int = 1200) -> str:
    return body if len(body) <= limit else body[:limit] + "\n... (truncated)"


def extract_spec_ids(text: str) -> list[str]:
    seen: list[str] = []
    for match in _SPEC_ID.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


def extract_identifiers(text: str) -> list[str]:
    """Pull candidate symbol names out of the task description."""
    skip = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "must",
        "should",
        "when",
        "only",
        "does",
        "not",
        "from",
        "list",
        "return",
    }
    out: list[str] = []
    for match in _IDENTIFIER.findall(text or ""):
        for part in match.split("."):
            if len(part) < 4 or part.lower() in skip:
                continue
            if "_" not in part and not any(ch.isupper() for ch in part[1:]):
                continue
            if part not in out:
                out.append(part)
    return out


def build_context(
    database: MaterialDatabase,
    *,
    task_id: str,
    task_text: str,
    project: str,
    top_k: int = 6,
) -> DevContext:
    """Query the material store and assemble the development context."""
    spec_ids = extract_spec_ids(task_text)
    identifiers = extract_identifiers(task_text)

    queries: list[str] = [task_text]
    queries.extend(spec_ids)
    queries.extend(identifiers)

    for spec_id in spec_ids:
        queries.extend(_spec_tokens(database, project, spec_id))

    queries = _dedupe([q for q in queries if q and q.strip()])

    spec_hits = _collect(database, project, queries, kinds=("spec",), per_query=top_k)
    code_hits = _collect(database, project, queries, kinds=("code",), per_query=top_k)
    # Tests need a wider net: the same query has to surface both the new functional
    # tests and the neighbouring regression tests.
    test_hits = _collect(database, project, queries, kinds=("test",), per_query=top_k * 3)

    # Specs named explicitly in the task always win, regardless of lexical score.
    pinned_specs = [hit for spec_id in spec_ids for hit in database.fetch_by_symbol(project, spec_id, kinds=("spec",))]
    specs = _merge(pinned_specs, spec_hits, limit=top_k)

    functional = _select_functional_tests(test_hits, spec_ids)
    code_targets = _select_code_targets(code_hits, functional, limit=top_k)

    # Regression scope is derived from real signals: the modules that the functional
    # tests live in, the modules of the code being edited, and the symbol names those
    # tests actually call.
    affected_modules = _modules_of({item.source for item in functional})
    affected_modules |= _modules_of({item.source for item in code_targets})
    target_symbols = _symbol_names(code_targets)
    regression = _select_regression_tests(
        test_hits, functional, affected_modules, target_symbols, top_k * 2
    )

    return DevContext(
        task_id=task_id,
        task_text=task_text,
        project=project,
        specs=[_to_item(hit, "named in the task") for hit in specs],
        code_targets=code_targets,
        functional_tests=functional,
        regression_tests=regression,
        queries=queries,
        database=database.backend,
    )


def _spec_tokens(database: MaterialDatabase, project: str, spec_id: str) -> list[str]:
    """Use the spec body itself as an extra query to pull related code and tests."""
    hits = database.fetch_by_symbol(project, spec_id, kinds=("spec",))
    if not hits:
        return []
    body = hits[0].body
    tokens = [line.strip("- ").strip() for line in body.splitlines() if line.strip().startswith("- **接口**")]
    return [" ".join(tokens[:2])[:400]] if tokens else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _collect(
    database: MaterialDatabase,
    project: str,
    queries: list[str],
    *,
    kinds: tuple[str, ...],
    per_query: int,
) -> list[SearchHit]:
    merged: dict[tuple[str, str], SearchHit] = {}
    for query in queries:
        for hit in database.search(project, query, kinds=kinds, limit=per_query):
            key = (hit.path, hit.symbol)
            existing = merged.get(key)
            if existing is None or hit.score > existing.score:
                merged[key] = hit
    return sorted(merged.values(), key=lambda hit: (-hit.score, hit.path, hit.start_line))


def _merge(pinned: list[SearchHit], scored: list[SearchHit], *, limit: int) -> list[SearchHit]:
    out: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()
    for hit in pinned:
        key = (hit.path, hit.symbol)
        if key not in seen:
            seen.add(key)
            out.append(hit)
    for hit in scored:
        key = (hit.path, hit.symbol)
        if key not in seen:
            seen.add(key)
            out.append(hit)
    return out[:limit]


def _to_item(hit: SearchHit, reason: str) -> ContextItem:
    return ContextItem(
        kind=hit.kind,
        source=hit.path,
        locator=hit.locator,
        title=hit.title,
        excerpt=_excerpt(hit.body),
        content_hash=hit.content_hash,
        score=hit.score,
        reason=reason,
    )


def _select_functional_tests(hits: list[SearchHit], spec_ids: list[str]) -> list[ContextItem]:
    """Tests that state they cover a target spec, plus tests that reference target specs."""
    selected: list[ContextItem] = []
    seen: set[str] = set()
    for hit in hits:
        covers = any(spec_id in hit.title or spec_id in hit.body for spec_id in spec_ids)
        if covers and hit.symbol not in seen:
            seen.add(hit.symbol)
            selected.append(_to_item(hit, "declares coverage of a target spec"))
    # Fall back to the strongest lexical test hits when no explicit coverage marker exists.
    if not selected:
        for hit in hits[:4]:
            if hit.symbol not in seen:
                seen.add(hit.symbol)
                selected.append(_to_item(hit, "highest lexical relevance to the task"))
    return selected


def _modules_of(paths: set[str]) -> set[str]:
    """Map file paths to the logical module names they belong to."""
    modules: set[str] = set()
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if name.startswith("test_"):
            name = name[len("test_") :]
        modules.add(name.removesuffix(".py"))
    return modules


def _symbol_names(code_targets: list[ContextItem]) -> set[str]:
    """Short symbol names (``OrderService.list_orders`` -> ``list_orders``) under change."""
    names: set[str] = set()
    for item in code_targets:
        symbol = item.title.rsplit(".", 1)[-1]
        if symbol and not symbol.startswith("module "):
            names.add(symbol)
    return names


def _select_regression_tests(
    hits: list[SearchHit],
    functional: list[ContextItem],
    affected_modules: set[str],
    target_symbols: set[str],
    limit: int,
) -> list[ContextItem]:
    """Other tests that exercise the module under change, then the strongest remaining."""
    functional_symbols = {item.title.split(" [")[0] for item in functional}
    functional_sources = {item.source for item in functional}
    selected: list[ContextItem] = []
    seen: set[str] = set(functional_symbols)

    for hit in hits:
        if hit.path in functional_sources and hit.symbol not in seen:
            seen.add(hit.symbol)
            selected.append(_to_item(hit, "same test module as a functional test"))

    for hit in hits:
        if len(selected) >= limit:
            return selected[:limit]
        if hit.symbol in seen:
            continue
        module = hit.path.rsplit("/", 1)[-1].removeprefix("test_").removesuffix(".py")
        if module in affected_modules:
            seen.add(hit.symbol)
            selected.append(_to_item(hit, "test module for a module under change"))

    for hit in hits:
        if len(selected) >= limit:
            return selected[:limit]
        if hit.symbol in seen:
            continue
        if any(symbol in hit.body for symbol in target_symbols):
            seen.add(hit.symbol)
            selected.append(_to_item(hit, "exercises a symbol under change"))

    return selected[:limit]


def _select_code_targets(
    hits: list[SearchHit],
    functional: list[ContextItem],
    *,
    limit: int,
) -> list[ContextItem]:
    """Rank symbols by lexical score, boosted when the functional tests actually call them."""
    test_bodies = "\n".join(item.excerpt for item in functional)
    ranked: list[tuple[float, SearchHit, bool]] = []
    for hit in hits:
        if hit.kind != "code" or not hit.symbol:
            continue
        short = hit.symbol.rsplit(".", 1)[-1]
        called = bool(short) and short in test_bodies
        ranked.append((hit.score + (3.0 if called else 0.0), hit, called))
    ranked.sort(key=lambda entry: (-entry[0], entry[1].path, entry[1].start_line))

    selected: list[ContextItem] = []
    seen: set[str] = set()
    for _, hit, called in ranked:
        if len(selected) >= limit:
            break
        if hit.symbol in seen:
            continue
        seen.add(hit.symbol)
        reason = "called by the functional tests" if called else "lexically closest code symbol"
        selected.append(_to_item(hit, reason))

    # Always offer the module row for the file that will be edited.
    if selected:
        path = selected[0].source
        for hit in hits:
            if hit.path == path and not hit.symbol and path not in seen:
                seen.add(path)
                selected.append(_to_item(hit, "module container for the edit"))
                break
    return selected[:limit]
