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

"""Choose the spans inside recalled Memory entries that answer the current query.

A recalled entry is delivered whole by default, and the byte budget then cuts it to a prefix,
so evidence that a long abstract keeps at its end is lost. This module scores the entry's own
sentences against the query and proposes contiguous spans instead, in the order they should be
tried. It is pure: no I/O, no persistence, and no knowledge of any expected answer. The spans it
returns are character offsets into the entry text, so the caller can hand them out verbatim.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

#: Words and numbers, matching how the acceptance tokenises text for scoring.
_TOKEN = re.compile(r"[a-z]+|\d+")
#: A sentence ends at terminal punctuation followed by whitespace.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
#: A sentence only competes when it scores within this fraction of the entry's best sentence.
#: Without it every sentence that happens to repeat one topic word joins the span and the
#: selection degenerates back into "the first N characters of the entry".
_RELATIVE_CUTOFF = 0.5
#: Neighbouring qualifying sentences are delivered as one span so that an annotation covering
#: two or three consecutive sentences arrives whole. One unqualified sentence between two
#: qualified ones is not bridged: that would spend the budget on unrelated material.
_MERGE_GAP = 1
#: A span shorter than this cannot carry an answer, so it is never proposed.
_MIN_SPAN_CHARS = 24
#: How strongly a span's length damps its pooled sentence score.
_SPAN_LENGTH_DAMPING = 0.5


@dataclass(frozen=True)
class Span:
    """One proposed span of one entry, in the order it should be tried."""

    entry_index: int
    start: int
    end: int
    score: float
    first: int = 0
    last: int = 0


@dataclass(frozen=True)
class _Sentence:
    start: int
    end: int
    tokens: frozenset[str]


def tokens_of(text: str) -> tuple[str, ...]:
    """Return the scoring tokens of ``text``.

    The tokenisation is the acceptance's own: lowercase ``[a-z]+|\\d+``. Reproducing it here
    means a query word can only match text a reader would also see as that word.
    """

    return tuple(_TOKEN.findall(text.lower()))


def stem_of(token: str) -> str:
    """Fold a token onto a crude stem, used only to decide which sentences to compare.

    A claim says "myelin sheaths" where the abstract says "myelinated axons", and "infants"
    where it says "infant"; the words agree but the strings do not, so a literal comparison
    leaves the sentence that carries the finding with no score at all. Folding inflections here
    only affects which spans are considered — the delivered text stays the untouched original,
    so nothing is rewritten for the reader.
    """

    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _folded(text: str) -> frozenset[str]:
    return frozenset(stem_of(token) for token in tokens_of(text))


def _sentences(text: str) -> tuple[_Sentence, ...]:
    """Split ``text`` into sentences, keeping exact character offsets into ``text``."""

    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _BOUNDARY.finditer(text):
        end = match.start()
        if end > cursor:
            spans.append((cursor, end))
        cursor = match.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return tuple(
        _Sentence(start=start, end=end, tokens=_folded(text[start:end]))
        for start, end in spans
        if end > start
    )


def _weights(entries: tuple[tuple[_Sentence, ...], ...], query_terms: frozenset[str]) -> dict[str, float]:
    """Weight each query term by how few sentences carry it.

    A claim's discriminating words appear in one or two sentences of the whole candidate set,
    while its topic words appear almost everywhere. Weighting by rarity is what makes the span
    holding the actual evidence outrank the spans that merely stay on topic.
    """

    total = sum(len(sentences) for sentences in entries) or 1
    frequency: dict[str, int] = {}
    for sentences in entries:
        for sentence in sentences:
            for term in sentence.tokens & query_terms:
                frequency[term] = frequency.get(term, 0) + 1
    return {
        term: math.log(1.0 + (total - frequency.get(term, 0) + 0.5) / (frequency.get(term, 0) + 0.5))
        for term in query_terms
    }


def _clusters(scored: Sequence[float]) -> tuple[tuple[int, int, float], ...]:
    """Group sentences that carry any query term into contiguous runs.

    Evidence for one claim is rarely spread across a whole abstract; it sits in neighbouring
    sentences. Grouping neighbours into one span is what lets a single fragment cover an
    annotation that spans two or three sentences, instead of delivering them as fragments with
    the gap between them left out.
    """

    runs: list[tuple[int, int, float]] = []
    start: int | None = None
    last = 0
    total = 0.0
    for index, score in enumerate(scored):
        if score <= 0.0:
            continue
        if start is None:
            start, last, total = index, index, score
        elif index - last <= _MERGE_GAP:
            last, total = index, total + score
        else:
            runs.append((start, last, total))
            start, last, total = index, index, score
    if start is not None:
        runs.append((start, last, total))
    return tuple(runs)


def rank_spans(texts: Sequence[str], query: str) -> tuple[Span, ...]:
    """Propose spans across every candidate text, most relevant first.

    ``texts`` are the recalled entry bodies in any order; the result refers to them by index so
    the caller keeps full control over identity and budget.
    """

    query_terms = _folded(query)
    if not query_terms or not texts:
        return ()
    entries = tuple(_sentences(text) for text in texts)
    if not any(entries):
        return ()
    weight = _weights(entries, query_terms)
    spans: list[Span] = []
    for entry_index, sentences in enumerate(entries):
        if not sentences:
            continue
        scored = [sum(weight[term] for term in sentence.tokens & query_terms) for sentence in sentences]
        peak = max(scored)
        if peak <= 0.0:
            continue
        cutoff = peak * _RELATIVE_CUTOFF
        for first, last, total in _clusters([score if score >= cutoff else 0.0 for score in scored]):
            start = sentences[first].start
            end = sentences[last].end
            if end - start < _MIN_SPAN_CHARS:
                # Too short to carry an answer on its own; widen to the neighbouring sentence.
                if first > 0:
                    start = sentences[first - 1].start
                if last + 1 < len(sentences):
                    end = sentences[last + 1].end
                if end - start < _MIN_SPAN_CHARS:
                    continue
            spans.append(
                Span(
                    entry_index=entry_index,
                    start=start,
                    end=end,
                    # Sentences are scored individually and then pooled, so a run of three
                    # sentences that each merely repeat a topic word would outscore the single
                    # sentence that states the finding. Damping by the run's length keeps a
                    # concentrated finding ahead of a diffuse mention.
                    score=total / ((last - first + 1) ** _SPAN_LENGTH_DAMPING),
                    first=first,
                    last=last,
                )
            )
    spans.sort(key=lambda span: (-span.score, span.entry_index, span.start))
    return tuple(spans)


def sentence_bounds(text: str) -> tuple[tuple[int, int], ...]:
    """Return the sentence boundaries of ``text`` so a caller can widen a chosen span."""

    return tuple((sentence.start, sentence.end) for sentence in _sentences(text))


__all__ = ["Span", "rank_spans", "sentence_bounds", "tokens_of"]
