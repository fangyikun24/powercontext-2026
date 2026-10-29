"""Print what is actually stored and queried in seekdb / OceanBase.

This is the evidence for the "database actually participates" acceptance item: it shows
the table definition, the native full-text index, the row counts per kind, a few real
rows, and the exact ranked rows that a task query returns.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sdd_context.config import Settings
from sdd_context.context import extract_spec_ids
from sdd_context.db import FTS_INDEX, TABLE, open_materials_database
from sdd_context.materials import project_key
from sdd_context.textutil import searchable_text

TASK = (
    "SPEC-ORD-004: add an optional min_total filter to OrderService.list_orders so only orders "
    "whose total is at least min_total are returned; negative min_total must be rejected"
)


def main() -> int:
    settings = Settings.from_env(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    project = project_key(settings.project_dir)
    report: dict[str, object] = {
        "backend": settings.materials_db_label,
        "project": project,
        "table": TABLE,
    }

    with open_materials_database(settings) as database:
        with database._connection.cursor() as cursor:  # noqa: SLF001 - diagnostic introspection
            cursor.execute(f"SHOW CREATE TABLE {TABLE}")
            row = cursor.fetchone()
            report["table_ddl"] = row[1] if row else ""

            cursor.execute(
                "SELECT index_name, index_type, column_name FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = %s ORDER BY index_name, seq_in_index",
                (TABLE,),
            )
            report["indexes"] = [list(item) for item in cursor.fetchall()]

            cursor.execute(
                "SELECT version(), DATABASE()"
            )
            version_row = cursor.fetchone()
            report["server"] = list(version_row) if version_row else []

        report["counts"] = database.count(project)

        with database._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT kind, path, symbol, content_hash FROM {TABLE} WHERE project = %s "
                f"ORDER BY kind, path, start_line LIMIT 10",
                (project,),
            )
            report["sample_rows"] = [list(item) for item in cursor.fetchall()]

        terms = searchable_text(TASK)
        report["query_terms"] = terms
        hits = database.search(project, TASK, kinds=("spec", "code", "test"), limit=8)
        report["ranked_hits"] = [
            {
                "kind": hit.kind,
                "locator": hit.locator,
                "title": hit.title,
                "score": round(hit.score, 4),
                "content_hash": hit.content_hash,
            }
            for hit in hits
        ]

        report["spec_ids_named"] = extract_spec_ids(TASK)
        pinned = database.fetch_by_symbol(project, "SPEC-ORD-004", kinds=("spec",))
        report["pinned_spec"] = [
            {"locator": item.locator, "content_hash": item.content_hash, "bytes": len(item.body)} for item in pinned
        ]

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
