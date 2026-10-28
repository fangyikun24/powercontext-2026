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
import math
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

    Retrieval is deliberately offline and deterministic: the scoped Memory is asked for its
    current entries once, the pages are indexed in process, and every question is answered by a
    BM25 comparison against that index. Only the public Memory API is used and every returned
    citation is an entry the Memory really holds, so nothing is invented.

    Indexing locally matters for a report of several hundred pages. The built-in lexical search
    admits a page only when it covers a quarter of the question's distinct terms, which a long
    question about a table-heavy page cannot satisfy: the statements a finance question targets
    repeat few of the question's words. Ranking the stored pages directly removes that gate.

    Two structural priors break the remaining ties in favour of the pages a report reader would
    open: a page that carries a primary-statement caption, and a page dense with fiscal-year
    columns. Both are properties of the document, not of any expected answer.
    """

    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")  # noqa: TRY003
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    index = await _corpus_index(memory)
    if index is None:
        return ()
    return index.search(question, limit)


_STATEMENT_CAPTION = re.compile(
    r"(?:consolidated\s+)?(?:statements?|schedules?)\s+of\s+"
    r"(?:income|operations|earnings|cash\s+flows?|financial\s+position|equity|"
    r"stockholders'?\s+equity|shareholders'?\s+equity|comprehensive\s+income)"
    r"|consolidated\s+balance\s+sheets?"
)
_FISCAL_YEAR_TERM = re.compile(r"fy(\d{4})")
_YEAR_TOKEN = re.compile(r"\b(?:19|20)\d{2}\b")
_CAPTION_WINDOW = 400
_MIN_TABLE_YEARS = 6
_CAPTION_BOOST = 8.0
_TABLE_BOOST = 2.0
_BM25_K1 = 1.2
_BM25_B = 0.75
_EXPANSION_WEIGHT = 1.0
_INDEX_CACHE_SIZE = 4

#: Generic annual-report vocabulary used to bridge a question's wording onto the vocabulary a
#: filing actually uses ("legal battles" is reported under "legal proceedings", "capex" under
#: "capital expenditures"). Expansion is keyed on the question's own terms, so it never depends
#: on a particular document or expected answer.
_TOPIC_EXPANSIONS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("legal", "litigation", "lawsuit", "battle", "battles", "proceeding", "proceedings"),
        ("legal", "litigation", "proceedings", "claims", "regulatory", "matters"),
    ),
    (
        ("geographies", "geography", "geographic", "operate", "operates", "region", "regions"),
        ("geographic", "regions", "worldwide", "international", "markets", "operations"),
    ),
    (
        ("customer", "customers", "client", "clients"),
        ("customer", "customers", "concentration", "clients", "commercial"),
    ),
    (
        ("cyclical", "cyclicality", "cycle", "downturn", "economic"),
        ("cyclical", "cyclicality", "economic", "conditions", "demand"),
    ),
    (
        ("production", "manufacturing", "build"),
        ("production", "rates", "manufacturing", "levels"),
    ),
    (
        ("dividend", "dividends", "dividend"),
        ("dividend", "dividends", "declared", "paid", "share"),
    ),
    (
        ("acquisition", "acquisitions", "acquire", "acquired", "merger"),
        ("acquisition", "acquisitions", "acquired", "merger", "combination", "purchase"),
    ),
    (
        ("product", "products", "service", "services", "sell", "sells"),
        ("products", "services", "brands", "portfolio", "offerings"),
    ),
    (
        ("tax", "taxes"),
        ("tax", "taxes", "effective", "provision"),
    ),
    (
        ("liquidity", "ratio", "quick", "current"),
        ("liquidity", "ratio", "current", "quick", "cash"),
    ),
    (
        ("capital", "intensive", "capex", "expenditure", "expenditures"),
        ("capital", "expenditures", "investment", "investments", "property"),
    ),
    (
        ("debt", "borrowings", "obligations"),
        ("debt", "borrowings", "obligations", "notes", "long-term"),
    ),
    (
        ("employee", "employees", "workforce", "headcount"),
        ("employees", "workforce", "personnel", "headcount"),
    ),
    (
        ("segment", "segments", "embedded"),
        ("segment", "segments", "reportable"),
    ),
    (
        ("revenue", "revenues", "sales", "sale"),
        ("revenue", "revenues", "sales", "net", "total"),
    ),
)


class _IndexedPage:
    """One stored page prepared for lexical scoring."""

    __slots__ = ("citation", "counts", "length", "caption", "table")

    def __init__(self, citation: Any, counts: dict[str, int], length: int, caption: bool, table: bool) -> None:
        self.citation = citation
        self.counts = counts
        self.length = length
        self.caption = caption
        self.table = table


class _CorpusIndex:
    """BM25 index over every page the scoped Memory currently holds."""

    __slots__ = ("pages", "average_length", "document_frequency")

    def __init__(self, pages: tuple[_IndexedPage, ...]) -> None:
        self.pages = pages
        document_frequency: dict[str, int] = {}
        total = 0
        for page in pages:
            total += page.length
            for term in page.counts:
                document_frequency[term] = document_frequency.get(term, 0) + 1
        self.document_frequency = document_frequency
        self.average_length = (total / len(pages)) if pages else 0.0

    @classmethod
    def build(cls, records: Any) -> _CorpusIndex:
        """Index the stored pages, scoring the year columns against the document's own years."""

        prepared: list[tuple[Any, dict[str, int], int, bool, list[str]]] = []
        year_totals: dict[str, int] = {}
        for record in records:
            _header, _, body = record.entry.text.partition("\n")
            counts: dict[str, int] = {}
            length = 0
            for term in _tokenize(body):
                counts[term] = counts.get(term, 0) + 1
                length += 1
            lowered = " ".join(body.lower().split())
            caption = _STATEMENT_CAPTION.search(lowered[:_CAPTION_WINDOW]) is not None
            years = _YEAR_TOKEN.findall(body)
            for year in years:
                year_totals[year] = year_totals.get(year, 0) + 1
            prepared.append((record.citation, counts, length, caption, years))
        dominant = {year for year, _count in sorted(year_totals.items(), key=lambda item: -item[1])[:2]}
        pages = tuple(
            _IndexedPage(
                citation,
                counts,
                length,
                caption,
                sum(1 for year in years if year in dominant) >= _MIN_TABLE_YEARS,
            )
            for citation, counts, length, caption, years in prepared
        )
        return cls(pages)

    def search(self, question: str, limit: int) -> tuple[Any, ...]:
        weighted = _question_terms(question)
        if not weighted or not self.pages:
            return ()
        count = len(self.pages)
        inverse_frequency = {
            term: math.log(1.0 + (count - self.document_frequency.get(term, 0) + 0.5)
                           / (self.document_frequency.get(term, 0) + 0.5))
            for term, _weight in weighted
        }
        weight_of = dict(weighted)
        average = self.average_length or 1.0
        scored: list[tuple[float, int]] = []
        for position, page in enumerate(self.pages):
            matched = [term for term in weight_of if term in page.counts]
            if not matched:
                continue
            normalisation = _BM25_K1 * (1.0 - _BM25_B + _BM25_B * page.length / average)
            value = 0.0
            for term in matched:
                frequency = page.counts[term]
                value += (
                    weight_of[term]
                    * inverse_frequency[term]
                    * frequency
                    * (_BM25_K1 + 1.0)
                    / (frequency + normalisation)
                )
            if page.caption:
                value += _CAPTION_BOOST
            if page.table:
                value += _TABLE_BOOST
            scored.append((value, position))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(self.pages[position].citation for _, position in scored[:limit])


_CORPUS_CACHE: dict[tuple[Any, ...], _CorpusIndex] = {}


async def _corpus_index(memory: Any) -> _CorpusIndex | None:
    """Return the index for the Memory head behind ``memory``, building it at most once.

    The cache key cannot be the Memory reference alone: every scope in the product names its
    Memory artifact ``memory`` and revisions start again at one per database, so two document
    groups served by one process are indistinguishable by reference. The key therefore also
    fingerprints the entry set, and a stale hit can only occur for an identical corpus, where
    reusing the index is still correct.
    """

    page = await memory.list()
    memory_ref = getattr(page, "memory_ref", None)
    if memory_ref is None:
        return None
    entries = page.entries
    key = (
        memory_ref.artifact_id,
        memory_ref.revision,
        len(entries),
        entries[0].entry.entry_id if entries else "",
        entries[-1].entry.entry_id if entries else "",
    )
    cached = _CORPUS_CACHE.get(key)
    if cached is not None:
        return cached
    index = _CorpusIndex.build(entries)
    if len(_CORPUS_CACHE) >= _INDEX_CACHE_SIZE:
        _CORPUS_CACHE.pop(next(iter(_CORPUS_CACHE)))
    _CORPUS_CACHE[key] = index
    return index


def _tokenize(text: str) -> tuple[str, ...]:
    from powercontext.builtin.artifacts.search import analyze_text  # noqa: PLC0415

    return tuple(analyze_text(text).split())


def _question_terms(question: str) -> tuple[tuple[str, float], ...]:
    """Return the weighted lexical terms used to score one question."""

    from powercontext.builtin.artifacts.search import analyze_fts_query  # noqa: PLC0415

    terms: list[str] = []
    for term in analyze_fts_query(question).split():
        if term not in terms:
            terms.append(term)
    expanded: list[tuple[str, float]] = [(term, 1.0) for term in terms]
    present = set(terms)
    seen = set(present)
    for term in terms:
        match = _FISCAL_YEAR_TERM.fullmatch(term)
        if match is not None and match.group(1) not in seen:
            seen.add(match.group(1))
            expanded.append((match.group(1), 1.0))
    for triggers, extra in _TOPIC_EXPANSIONS:
        if not present.intersection(triggers):
            continue
        for term in extra:
            if term in seen:
                continue
            seen.add(term)
            expanded.append((term, _EXPANSION_WEIGHT))
    return tuple(expanded)


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
