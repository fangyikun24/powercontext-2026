# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Row-level CSV source collection for stable, re-checkable table evidence.

Each data row of a CSV document becomes an independent, :data:`CAPTURED` Source whose
stable identity depends only on ``document_id`` and the primary key value. Reading and
projecting preserve the original field names, column order, and raw string values so a
retrieval citation can always resolve back to the exact source row.
"""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class CSVDocumentInput(BaseModel):
    """A complete, offline CSV document to parse into row Sources."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """A single parsed CSV row, keyed by its primary key value."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """A captured CSV row whose identity is ``document_id`` + primary key value."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Build the stable Source identity ``csv:{document_id}:{primary_key_value}``.

    Both components are percent-encoded with no safe characters. The function fails fast
    when the inputs cannot form a valid ``source_id``: ``document_id`` must be non-empty
    and free of leading/trailing whitespace, ``primary_key_value`` must be non-empty and
    not whitespace-only, and the resulting identity must not exceed the source id length.
    """

    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and free of leading/trailing whitespace")
    if not primary_key_value or not primary_key_value.strip():
        raise ValueError("primary_key_value must be non-empty and not whitespace-only")

    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("csv row source_id exceeds the maximum allowed length")
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse a complete offline CSV document into validated row inputs.

    The document is decoded as strict UTF-8 (a leading BOM is accepted) and parsed with
    Python's :func:`csv.reader` semantics under ``strict=True``. The first non-empty
    record is the header; every later record is a data row. The whole document is parsed
    and validated before any row is returned, so any error raises :class:`ValueError`
    without yielding partial rows.
    """

    document_id = value.document_id
    primary_key = value.primary_key

    if not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and free of leading/trailing whitespace")
    if not primary_key:
        raise ValueError("primary_key must be non-empty")

    try:
        text = value.content.decode("utf-8-sig")
    except (UnicodeDecodeError, UnicodeError) as error:
        raise ValueError("content must be valid UTF-8 text") from error

    try:
        records = [record for record in csv.reader(io.StringIO(text), strict=True)]
    except csv.Error as error:
        raise ValueError("content is not valid CSV") from error

    # Ignore completely empty physical records (e.g. trailing blank lines).
    records = [record for record in records if len(record) > 0]
    if not records:
        raise ValueError("document has no header")

    header = records[0]
    if len(header) == 0:
        raise ValueError("document has no header")

    seen_columns: set[str] = set()
    for field in header:
        if not field or not field.strip():
            raise ValueError("header fields must be non-empty and not whitespace-only")
        if field in seen_columns:
            raise ValueError("header fields must be unique")
        seen_columns.add(field)

    if primary_key not in seen_columns:
        raise ValueError("primary_key must match a header column")

    primary_key_index = header.index(primary_key)
    rows: list[CSVRowInput] = []
    seen_primary_key_values: set[str] = set()
    for record in records[1:]:
        if len(record) != len(header):
            raise ValueError("data record width must match header width")
        primary_key_value = record[primary_key_index]
        if not primary_key_value or not primary_key_value.strip():
            raise ValueError("primary_key_value must be non-empty and not whitespace-only")
        if primary_key_value in seen_primary_key_values:
            raise ValueError("primary_key_value must be unique within the document")
        seen_primary_key_values.add(primary_key_value)
        rows.append(
            CSVRowInput(
                document_id=document_id,
                primary_key=primary_key,
                primary_key_value=primary_key_value,
                columns=tuple(header),
                values=tuple(record),
            )
        )
    return tuple(rows)


class CSVRowSourceAdapter:
    """Resolve and read the row-level CSV Source."""

    input_class = CSVRowInput
    name = "csv-row"
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        identity = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Expose a captured CSV row as standard text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        mapping = dict(zip(source.columns, source.values))
        return TextEvidence(
            source_type="csv-row",
            source_id=source.source_id,
            content=json.dumps(mapping, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": mapping,
            },
        )


CSV_ROW_SOURCE_DEFINITION = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    projections=(CSVRowTextEvidenceProjection(),),
)


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
