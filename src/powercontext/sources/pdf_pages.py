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

"""Physical PDF pages as immutable, page-citable Sources.

A report is parsed once, end to end: every physical page of the original bytes becomes one
:data:`CAPTURED` Source whose identity is ``(document_id, document_sha256, page_number)``. The
physical page number counts from the first page of the file, so a citation can be resolved by
re-opening the original document with the same digest and jumping to that page. Text is kept
verbatim per page, which preserves the association between numbers in a table and the page that
carries them.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from pydantic import BaseModel
from pypdf import PdfReader

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.artifacts.memory.models import MemoryCitation

PDF_PAGE_SOURCE_NAME = "pdf-page"
PDF_PAGE_SOURCE_VERSION = "1"
PDF_PAGE_IDENTITY_PREFIX = "pdf"

#: Extraction modes tried in order. ``layout`` is only a rescue path for pages the default
#: mode cannot read; word-term statistics are whitespace-insensitive, so either mode yields
#: the same token multiset for a page the default mode can already read.
_EXTRACTION_MODES: tuple[str | None, ...] = (None, "layout")


class PDFDocumentInput(BaseModel):
    """A complete original PDF plus the caller-assigned document identity."""

    document_id: str
    content: bytes


class PDFPageInput(BaseModel):
    """One physical page of a parsed PDF, in reading order."""

    document_id: str
    document_sha256: str
    page_number: int
    text: str


class PDFPageSource(Source):
    """A captured PDF page anchored to a document digest and physical page number."""

    source_id: str
    document_id: str
    document_sha256: str
    page_number: int
    text: str


def pdf_page_source_id(document_id: str, document_sha256: str, page_number: int) -> str:
    """Build the stable Source identity for one physical page.

    The readable form is ``pdf:{document_id}:{sha256}:{page}``. It is percent-encoded with no
    safe characters so a document id containing ``:`` cannot collide with the digest. Any
    identity that would exceed the shared length limit falls back to a bounded form that
    digests the document id instead of spelling it out.
    """

    if not document_id or not document_id.strip():
        raise ValueError("document_id must be non-empty and not whitespace-only")  # noqa: TRY003
    if len(document_sha256) != 64 or any(character not in "0123456789abcdef" for character in document_sha256):
        raise ValueError("document_sha256 must be a lowercase hexadecimal SHA-256 digest")  # noqa: TRY003
    if page_number < 1:
        raise ValueError("page_number must be a positive physical page number")  # noqa: TRY003

    identity = f"{PDF_PAGE_IDENTITY_PREFIX}:{quote(document_id, safe='')}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()
        identity = f"{PDF_PAGE_IDENTITY_PREFIX}:~{digest}:{document_sha256}:{page_number}"
    if len(identity) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("pdf page source_id exceeds the maximum allowed length")  # noqa: TRY003
    return identity


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of one original PDF, in order.

    Parsing is atomic: an empty file, a non-PDF, a corrupted document, or a page that cannot be
    read raises :class:`ValueError` and never returns a partial page list. Blank pages are
    returned with empty text so page numbers keep matching the physical file.
    """

    document_id = value.document_id
    if not document_id or not document_id.strip():
        raise ValueError("document_id must be non-empty and not whitespace-only")  # noqa: TRY003

    content = value.content
    if not isinstance(content, bytes) or not content:
        raise ValueError("content must be a non-empty PDF byte string")  # noqa: TRY003

    digest = hashlib.sha256(content).hexdigest()
    reader = _open_reader(content)
    try:
        page_count = len(reader.pages)
    except Exception as error:  # noqa: BLE001 - any structural failure is an unparsable document
        raise ValueError("the PDF page tree cannot be read") from error
    if page_count < 1:
        raise ValueError("the PDF has no physical pages")  # noqa: TRY003

    pages: list[PDFPageInput] = []
    for index in range(page_count):
        pages.append(
            PDFPageInput(
                document_id=document_id,
                document_sha256=digest,
                page_number=index + 1,
                text=_page_text(reader, index),
            )
        )
    return tuple(pages)


def _open_reader(content: bytes) -> PdfReader:
    """Open the bytes with the PDF reader or fail with ``ValueError``."""

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as error:  # noqa: BLE001 - pypdf raises several unrelated exception types
        raise ValueError("content is not a readable PDF document") from error

    if reader.is_encrypted:
        # A document that only carries a permissions marker (empty user password) is a legal
        # input; anything that actually needs a secret raises below.
        try:
            if not reader.decrypt(""):
                raise ValueError("the PDF requires a user password")  # noqa: TRY003
        except ValueError:
            raise
        except Exception as error:  # noqa: BLE001 - undecryptable documents are unparsable
            raise ValueError("the PDF requires a user password") from error
    return reader


def _page_text(reader: PdfReader, index: int) -> str:
    """Extract one page's text, raising when no extraction mode can read it."""

    last_error: Exception | None = None
    for mode in _EXTRACTION_MODES:
        try:
            page = reader.pages[index]
            text: Any = page.extract_text() if mode is None else page.extract_text(extraction_mode=mode)
        except Exception as error:  # noqa: BLE001 - try the next mode before giving up
            last_error = error
            continue
        if isinstance(text, str):
            return text
        last_error = ValueError("page extraction did not produce text")
    raise ValueError(f"page {index + 1} cannot be extracted") from last_error


class PDFPageSourceAdapter:
    """Resolve and read one adapter-native PDF page."""

    input_class = PDFPageInput
    name = PDF_PAGE_SOURCE_NAME
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = pdf_page_source_id(value.document_id, value.document_sha256, value.page_number)
        return PDFPageSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose a captured PDF page as standard text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PDF_PAGE_SOURCE_NAME,
            source_id=source.source_id,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDFPageSourceAdapter(),
    version=PDF_PAGE_SOURCE_VERSION,
    projections=(PDFPageTextEvidenceProjection(),),
)


async def search_pdf_pages(
    memory: Any,
    question: str,
    limit: int = 10,
) -> tuple[MemoryCitation, ...]:
    """Return up to ``limit`` distinct page citations for one natural-language question.

    Only the public Memory search API is used, so every returned citation resolves through
    ``memory.get`` to a stored page: no citation is invented. Queries are issued in priority
    order and results are walked once in that order, keeping the first citation of each distinct
    page. The first query is the question itself; the later ones only backfill, which is what
    rescues a long question whose instruction-heavy phrasing admits very few pages on its own.
    """

    from powercontext.builtin.artifacts.memory.models import MemoryCitation  # noqa: PLC0415
    from powercontext.builtin.runtime.models import SearchMemoryRequest  # noqa: PLC0415

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    candidate_limit = max(limit * 3, 60)
    citations: list[MemoryCitation] = []
    seen: set[str] = set()
    for query in _query_variants(question):
        page = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=candidate_limit))
        for hit in page.hits:
            if hit.entry_version_id in seen:
                continue
            seen.add(hit.entry_version_id)
            citations.append(
                MemoryCitation(
                    memory_ref=hit.memory_ref,
                    entry_id=hit.entry_id,
                    entry_version_id=hit.entry_version_id,
                )
            )
            if len(citations) == limit:
                return tuple(citations)
    return tuple(citations)


_INSTRUCTION_SENTENCE = re.compile(r"^(respond|answer|give a response|assume|calculate)\b", re.I)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def _query_variants(question: str) -> tuple[str, ...]:
    """Return the lexical queries used to retrieve evidence pages, most reliable first."""

    stripped = question.strip()
    core = _core_question(stripped)
    variants = [
        stripped,
        _focus_query(stripped),
        _focus_query(core),
        *_sentences(stripped),
    ]
    return tuple(variant for variant in dict.fromkeys(variants) if variant)


def _sentences(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip())


def _core_question(text: str) -> str:
    """Drop trailing answer-formatting instructions that only add lexical noise."""

    kept = [sentence for sentence in _sentences(text) if not _INSTRUCTION_SENTENCE.match(sentence)]
    return " ".join(kept) if kept else text


def _analyze_fts_query(text: str) -> str:
    """Reuse the product's Analyzer so the focused query matches the indexed terms."""

    from powercontext.builtin.artifacts.search import analyze_fts_query  # noqa: PLC0415

    return analyze_fts_query(text)


def _focus_query(text: str, size: int = 10) -> str:
    """Build a compact query from the most distinctive terms of one question.

    A long question lifts the lexical-admission floor to a quarter of its distinct terms, which
    can leave a large report with almost no candidate pages. A short query of the longest content
    terms keeps that floor low while still naming the entities the evidence page must contain.
    """

    terms: list[str] = []
    seen: set[str] = set()
    for term in _analyze_fts_query(text).split():
        if term in seen or len(term) < 4:
            continue
        seen.add(term)
        terms.append(term)
    if len(terms) <= size:
        return " ".join(sorted(terms))
    terms.sort(key=lambda term: (-len(term), term))
    return " ".join(sorted(terms[:size]))


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDF_PAGE_SOURCE_NAME",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "pdf_page_source_id",
    "search_pdf_pages",
]
