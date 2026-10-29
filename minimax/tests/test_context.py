"""Tests for context selection, using an in-memory stand-in for the database.

The selection rules are what make the context useful, so they are tested without
standing up seekdb: :class:`FakeDatabase` implements the same two read methods that
:func:`sdd_context.context.build_context` relies on.
"""

from __future__ import annotations

from pathlib import Path

from sdd_context.context import build_context, extract_identifiers, extract_spec_ids
from sdd_context.db import MaterialRow, SearchHit
from sdd_context.materials import collect_materials
from sdd_context.textutil import analyze

SAMPLE = Path(__file__).resolve().parents[1] / "sample-project"
TASK = (
    "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only "
    "orders whose total is at least min_total are returned"
)


class FakeDatabase:
    """Token-overlap search that mirrors the SQL full-text behaviour closely enough."""

    backend = "fake"

    def __init__(self, rows: list[MaterialRow]) -> None:
        self._rows = rows

    def _hit(self, row: MaterialRow, score: float) -> SearchHit:
        lines = row.body.count("\n")
        return SearchHit(
            kind=row.kind,
            path=row.path,
            symbol=row.symbol,
            start_line=row.start_line,
            end_line=row.start_line + lines,
            title=row.title,
            body=row.body,
            content_hash=row.content_hash,
            score=score,
        )

    def search(self, project: str, query: str, *, kinds=("spec", "code", "test"), limit: int = 8) -> list[SearchHit]:
        wanted = set(analyze(query))
        scored: list[tuple[float, MaterialRow]] = []
        for row in self._rows:
            if row.kind not in kinds:
                continue
            tokens = set(analyze(f"{row.title} {row.body} {row.symbol} {row.path}"))
            overlap = len(wanted & tokens)
            if overlap:
                scored.append((float(overlap), row))
        scored.sort(key=lambda item: (-item[0], item[1].path, item[1].start_line))
        return [self._hit(row, score) for score, row in scored[:limit]]

    def fetch_by_symbol(self, project: str, symbol: str, *, kinds=("spec", "code", "test")) -> list[SearchHit]:
        return [self._hit(row, 1.0) for row in self._rows if row.symbol == symbol and row.kind in kinds]


def make_context():
    database = FakeDatabase(collect_materials(SAMPLE))
    return build_context(database, task_id="T1", task_text=TASK, project="sample-project")


def test_extracts_the_spec_named_in_the_task():
    assert extract_spec_ids(TASK) == ["SPEC-ORD-004"]


def test_extracts_called_symbols_from_the_task():
    identifiers = extract_identifiers(TASK)
    assert "list_orders" in identifiers
    assert "min_total" in identifiers


def test_context_pins_the_named_spec_first():
    context = make_context()
    assert context.specs, "no specs retrieved"
    assert context.specs[0].title.startswith("SPEC-ORD-004")


def test_context_locates_the_code_to_change():
    context = make_context()
    locators = [item.locator for item in context.code_targets]
    assert any("service.py" in locator for locator in locators)
    assert any(item.title.endswith("list_orders") for item in context.code_targets)


def test_context_selects_the_functional_tests_that_cover_the_spec():
    context = make_context()
    sources = {item.source for item in context.functional_tests}
    assert sources == {"tests/test_min_total_filter.py"}


def test_context_keeps_regression_tests_separate():
    context = make_context()
    functional = {item.title.split(" [")[0] for item in context.functional_tests}
    regression = {item.title.split(" [")[0] for item in context.regression_tests}
    assert not functional & regression
    assert regression


def test_every_context_item_points_at_a_real_file():
    context = make_context()
    items = context.specs + context.code_targets + context.functional_tests + context.regression_tests
    assert items
    for item in items:
        path = SAMPLE / item.source
        assert path.is_file(), f"context cites a missing file: {item.source}"
        line = int(item.locator.rsplit(":", 1)[1].split("-")[0]) if ":" in item.locator else 1
        assert line >= 1
        assert line <= len(path.read_text(encoding="utf-8").splitlines())


def test_context_is_not_hard_coded():
    """A different task must produce a different context."""
    database = FakeDatabase(collect_materials(SAMPLE))
    other = build_context(
        database,
        task_id="T2",
        task_text="SPEC-PRC-003: gold tier discount thresholds",
        project="sample-project",
    )
    assert other.specs[0].title.startswith("SPEC-PRC-003")
    assert other.specs[0].title != make_context().specs[0].title
