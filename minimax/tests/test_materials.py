"""Tests for material extraction: specs, code symbols and tests."""

from __future__ import annotations

from pathlib import Path

from sdd_context.materials import collect_materials, parse_code, parse_specs, parse_tests

SAMPLE = Path(__file__).resolve().parents[1] / "sample-project"


def test_specs_are_split_per_requirement():
    rows = parse_specs(SAMPLE / "specs", project_root=SAMPLE)
    ids = [row.symbol for row in rows]
    assert "SPEC-ORD-004" in ids
    assert "SPEC-PRC-003" in ids
    assert len(ids) == len(set(ids))


def test_spec_row_carries_locator_and_body():
    rows = {row.symbol: row for row in parse_specs(SAMPLE / "specs", project_root=SAMPLE)}
    spec = rows["SPEC-ORD-004"]
    assert spec.path == "specs/orders.md"
    assert spec.start_line >= 1
    assert spec.end_line >= spec.start_line
    assert "min_total" in spec.body
    assert spec.content_hash


def test_code_extracts_module_and_symbols():
    rows = parse_code(SAMPLE / "src", project_root=SAMPLE)
    symbols = {row.symbol for row in rows}
    assert "orderflow.service.OrderService.list_orders" in symbols
    assert "orderflow.models.Order.total" in symbols
    # module rows carry an empty symbol
    assert any(row.symbol == "" and row.path == "src/orderflow/service.py" for row in rows)


def test_code_locator_points_at_the_symbol_lines():
    rows = {row.symbol: row for row in parse_code(SAMPLE / "src", project_root=SAMPLE)}
    symbol = rows["orderflow.service.OrderService.list_orders"]
    text = (SAMPLE / "src/orderflow/service.py").read_text(encoding="utf-8").splitlines()
    segment = "\n".join(text[symbol.start_line - 1 : symbol.end_line])
    assert "def list_orders" in segment


def test_tests_are_extracted_with_coverage_tags():
    rows = parse_tests(SAMPLE / "tests", project_root=SAMPLE)
    names = {row.symbol for row in rows}
    assert "test_min_total_filters_out_smaller_orders" in names
    tagged = [row for row in rows if "covers SPEC-ORD-004" in row.title]
    assert len(tagged) == 8


def test_collect_materials_covers_all_three_kinds():
    rows = collect_materials(SAMPLE)
    kinds = {row.kind for row in rows}
    assert kinds == {"spec", "code", "test"}


def test_material_ids_are_stable_and_distinct():
    rows = collect_materials(SAMPLE)
    ids = [row.material_id("demo") for row in rows]
    assert len(ids) == len(set(ids))
    again = [row.material_id("demo") for row in collect_materials(SAMPLE)]
    assert ids == again
