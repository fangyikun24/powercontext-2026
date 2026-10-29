"""Text analysis helpers shared by ingestion and retrieval.

seekdb/OceanBase full-text indexes here use ``WITH PARSER SPACE``, i.e. tokens are
whitespace delimited. To get useful recall for both English identifiers and Chinese
spec text, every stored document and every query is normalised through
:func:`analyze` into an explicit token stream:

* snake_case / camelCase / dotted identifiers are split into their parts;
* ASCII words are lowercased and kept as-is;
* CJK runs contribute unigrams **and** bigrams, so ``金额下限`` matches ``下限``.
"""

from __future__ import annotations

import re
import unicodedata

_ASCII_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

_STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could do does for from has have how i if in into is it
    its may must not of on or our shall should so than that the their then there these they this
    to was were when where which who will with would you your
    """.split()
)


def _split_identifier(token: str) -> list[str]:
    parts: list[str] = []
    for chunk in token.split("_"):
        if not chunk:
            continue
        parts.extend(_CAMEL.split(chunk))
    return [part.lower() for part in parts if part]


def analyze(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Return the ordered token stream for ``text``."""
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text)
    tokens: list[str] = []

    for match in _ASCII_WORD.finditer(normalized):
        raw = match.group(0)
        for part in _split_identifier(raw):
            if len(part) < 2 and not part.isdigit():
                continue
            if not keep_stopwords and part in _STOPWORDS:
                continue
            tokens.append(part)

    for run in _CJK.findall(normalized):
        tokens.append(run)

    # CJK bigrams preserve neighbourhood information for multi-character terms.
    cjk_runs = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,}", normalized)
    for run in cjk_runs:
        for index in range(len(run) - 1):
            tokens.append(run[index : index + 2])

    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def searchable_text(*parts: str) -> str:
    """Build the ``searchable_text`` column value from several fields."""
    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for token in analyze(part):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return " ".join(tokens)
