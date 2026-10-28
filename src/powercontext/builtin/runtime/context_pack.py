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

"""Incremental transport for prepared context.

A :class:`ContextPack` is the whole prepared context chopped into chunks that are
individually addressable on the wire: Base64 strings inside one canonical JSON object. A
:class:`ContextPackDelta` names a prefix of an already-delivered pack that the receiver may
keep and carries only the chunks after it, so a receiver holding the previous pack restores
byte-identical content from ``pack`` bytes plus the delta.

The module is deliberately free of runtime imports: encoding and decoding depend on nothing
but ``hashlib``/``json``/``base64``, which keeps it usable by a bare receiver and makes the
wire format auditable in one screen.

Wire contract (both objects are **closed**: the exact key set is checked on decode):

============================  ==========================================================
Pack                          ``schema``, ``items``, ``digest``, ``byte_count``
Delta                         ``schema``, ``base_digest``, ``target_digest``,
                              ``prefix_items``, ``appended``
JSON                          UTF-8, sorted keys, ``,`` and ``:`` separators, no padding
Chunks                        standard Base64 strings (bytes in memory)
Digest                        SHA-256 over the JSON of ``schema`` + ``items`` only,
                              rendered ``sha256:<hex>``
============================  ==========================================================

``byte_count`` is the length of the very object that carries it, so it is a fixed point
rather than a plain sum: the decimal width of the number itself is part of the length.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

CONTEXT_PACK_SCHEMA: Final = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA: Final = "powercontext.context-pack-delta.v1"

#: Chunk ceiling used by :meth:`ContextPack.from_content` unless the caller overrides it.
DEFAULT_CONTEXT_PACK_CHUNK_BYTES: Final = 512

_DIGEST_PREFIX: Final = "sha256:"
_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_DIGEST_HEX_LENGTH: Final = 64
_PACK_FIELDS: Final = frozenset({"schema", "items", "digest", "byte_count"})
_DELTA_FIELDS: Final = frozenset({"schema", "base_digest", "target_digest", "prefix_items", "appended"})
#: ``byte_count`` is a fixed point of its own length; the width changes at most once per pass.
_MAX_BYTE_COUNT_PASSES: Final = 8


class ContextPackError(Exception):
    """A pack or delta violates the transport contract.

    Raised for structural problems (missing/extra fields, wrong JSON type, non-Base64 chunk),
    for failed integrity checks (pack digest, base digest, target digest, byte count) and for
    chunking requests that cannot be satisfied. Never raised for a legitimately empty pack.
    """


def _canonical_json(payload: dict[str, Any]) -> bytes:
    """One encoding for both directions: sorted keys, tight separators, UTF-8, no padding."""

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _encode_chunks(chunks: Iterable[bytes]) -> list[str]:
    return [base64.b64encode(chunk).decode("ascii") for chunk in chunks]


def _decode_chunks(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list):
        raise ContextPackError("chunks-must-be-an-array")
    decoded: list[bytes] = []
    for encoded in value:
        if not isinstance(encoded, str):
            raise ContextPackError("chunk-must-be-a-base64-string")
        try:
            decoded.append(base64.b64decode(encoded.encode("ascii"), validate=True))
        except (binascii.Error, UnicodeEncodeError, ValueError) as error:
            raise ContextPackError("chunk-is-not-valid-base64") from error
    return tuple(decoded)


def _pack_digest(chunks: tuple[bytes, ...]) -> str:
    """Digest covers exactly ``schema`` and ``items`` — never ``digest``/``byte_count``."""

    unsigned = {"schema": CONTEXT_PACK_SCHEMA, "items": _encode_chunks(chunks)}
    return f"{_DIGEST_PREFIX}{hashlib.sha256(_canonical_json(unsigned)).hexdigest()}"


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        raise ContextPackError("digest-must-be-a-sha256-string")
    hexadecimal = value[len(_DIGEST_PREFIX) :]
    if len(hexadecimal) != _DIGEST_HEX_LENGTH or not _HEX_DIGITS.issuperset(hexadecimal):
        raise ContextPackError("digest-must-carry-64-lowercase-hex-digits")
    return value


def _parse_object(data: object) -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ContextPackError("payload-must-be-bytes")
    try:
        payload = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContextPackError("payload-is-not-utf8-json") from error
    if not isinstance(payload, dict):
        raise ContextPackError("payload-must-be-a-json-object")
    return payload


def _require_fields(payload: dict[str, Any], expected: frozenset[str]) -> None:
    if set(payload) != expected:
        missing = sorted(expected.difference(payload))
        extra = sorted(set(payload).difference(expected))
        raise ContextPackError(f"payload-fields-must-be-exact:{missing}:{extra}")


def _settle_byte_count(encoded: list[str], digest: str) -> int:
    """Solve ``byte_count == len(serialize(byte_count))``.

    The right-hand side only changes when the decimal width of ``byte_count`` grows, so
    iterating from ``0`` reaches the fixed point in at most a couple of passes: the number
    is inside the object it measures.
    """

    byte_count = 0
    for _ in range(_MAX_BYTE_COUNT_PASSES):
        payload = {
            "schema": CONTEXT_PACK_SCHEMA,
            "items": encoded,
            "digest": digest,
            "byte_count": byte_count,
        }
        measured = len(_canonical_json(payload))
        if measured == byte_count:
            return measured
        byte_count = measured
    raise ContextPackError("byte-count-has-no-fixed-point")


def _chunk_payload(data: bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    """Split deterministically, preferring a line break in the second half of each window.

    Two properties matter and neither alone is enough:

    * **No split code point.** Boundary detection only looks at continuation bits
      (``10xxxxxx``), so every chunk is valid UTF-8 on its own and concatenation reproduces
      the input byte for byte — including a byte order mark or any other multi-byte sequence.
    * **Structural breaks first.** Context text is a fixed preamble followed by one long JSON
      line. Cutting on pure byte offsets slices through the preamble, so the first chunk of
      every turn differs as soon as anything later in the content changes, and no prefix can be
      reused. Preferring the last newline in the second half of the window keeps the preamble
      in whole chunks of its own, which stays byte-identical across turns; inside the JSON line
      there is no newline, so the window fills to ``chunk_bytes`` and overhead stays low.

    A window that cannot hold even one code point is reported rather than silently emitting a
    corrupt chunk.
    """

    chunks: list[bytes] = []
    total = len(data)
    floor_offset = max(1, chunk_bytes // 2)
    start = 0
    while start < total:
        end = min(start + chunk_bytes, total)
        if end < total:
            while end > start and data[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("a-single-character-exceeds-chunk-bytes")
            break_at = data.rfind(b"\n", min(start + floor_offset, end), end)
            if break_at >= 0:
                end = break_at + 1
        chunks.append(data[start:end])
        start = end
    return tuple(chunks)


@dataclass(frozen=True)
class ContextPack:
    """Content split into ordered chunks, plus the digest and wire length that identify it."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(bytes(item) for item in self.items))

    @classmethod
    def build(cls, items: Iterable[bytes]) -> ContextPack:
        """Wrap already-chunked bytes. Empty is legal and means "no context"."""

        chunks = tuple(bytes(item) for item in items)
        digest = _pack_digest(chunks)
        return cls(items=chunks, digest=digest, byte_count=_settle_byte_count(_encode_chunks(chunks), digest))

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = DEFAULT_CONTEXT_PACK_CHUNK_BYTES) -> ContextPack:
        """Chunk ``content`` deterministically under a per-chunk byte ceiling.

        ``content`` is encoded to UTF-8 when it is text. The ceiling applies to the encoded
        bytes of each chunk, so a chunk never splits a code point and never exceeds the
        caller's limit; text that cannot satisfy a positive ceiling fails instead of being
        silently corrupted.
        """

        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk-bytes-must-be-a-positive-integer")
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        return cls.build(_chunk_payload(data, chunk_bytes))

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "schema": CONTEXT_PACK_SCHEMA,
                "items": _encode_chunks(self.items),
                "digest": self.digest,
                "byte_count": self.byte_count,
            }
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPack:
        """Decode and fully re-derive the pack: digest and byte count are both re-checked."""

        payload = _parse_object(data)
        _require_fields(payload, _PACK_FIELDS)
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("pack-schema-is-unknown")
        chunks = _decode_chunks(payload["items"])
        digest = _require_digest(payload["digest"])
        if digest != _pack_digest(chunks):
            raise ContextPackError("pack-digest-does-not-cover-items")
        byte_count = payload["byte_count"]
        if type(byte_count) is not int or byte_count < 0:
            raise ContextPackError("pack-byte-count-must-be-a-non-negative-integer")
        pack = cls.build(chunks)
        if pack.byte_count != byte_count:
            raise ContextPackError("pack-byte-count-does-not-match-serialization")
        return pack

    @property
    def content_bytes(self) -> int:
        """Total payload bytes carried, ignoring protocol overhead."""

        return sum(len(item) for item in self.items)


@dataclass(frozen=True)
class ContextPackDelta:
    """A prefix of the receiver's base pack to keep, plus the chunks that follow it."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "appended", tuple(bytes(item) for item in self.appended))

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        """Keep the longest shared prefix; everything after it is the suffix to send.

        A longer prefix is never more expensive on the wire — it strictly shrinks
        ``appended`` — so the longest one is chosen. Chunk equality is byte equality, which
        makes the kept prefix verifiable by the receiver against its own base.
        """

        shared = 0
        ceiling = min(len(base.items), len(target.items))
        while shared < ceiling and base.items[shared] == target.items[shared]:
            shared += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=shared,
            appended=target.items[shared:],
        )

    def to_bytes(self) -> bytes:
        return _canonical_json(
            {
                "schema": CONTEXT_PACK_DELTA_SCHEMA,
                "base_digest": self.base_digest,
                "target_digest": self.target_digest,
                "prefix_items": self.prefix_items,
                "appended": _encode_chunks(self.appended),
            }
        )

    @property
    def byte_count(self) -> int:
        """Delta length is derived, never a field: the delta JSON stays minimal."""

        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> ContextPackDelta:
        payload = _parse_object(data)
        _require_fields(payload, _DELTA_FIELDS)
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("delta-schema-is-unknown")
        base_digest = _require_digest(payload["base_digest"])
        target_digest = _require_digest(payload["target_digest"])
        prefix_items = payload["prefix_items"]
        # ``type(...) is int`` rather than ``isinstance``: JSON ``true`` is an ``int`` subclass.
        if type(prefix_items) is not int or prefix_items < 0:
            raise ContextPackError("prefix-items-must-be-a-non-negative-integer")
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix_items,
            appended=_decode_chunks(payload["appended"]),
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild the target pack from a base pack and a delta, or fail.

    Three independent checks decide success: the delta must name this base, the retained
    prefix must fit inside it, and the rebuilt chunks must hash to the delta's
    ``target_digest``. Nothing else — no sender state, no ordering assumption — is trusted.
    """

    if not isinstance(base, ContextPack):
        raise ContextPackError("base-must-be-a-context-pack")
    if not isinstance(delta, ContextPackDelta):
        raise ContextPackError("delta-must-be-a-context-pack-delta")
    if delta.base_digest != base.digest:
        raise ContextPackError("delta-base-digest-does-not-match-base")
    if type(delta.prefix_items) is not int or delta.prefix_items < 0:
        raise ContextPackError("prefix-items-must-be-a-non-negative-integer")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("prefix-items-exceeds-base-chunk-count")
    rebuilt = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("rebuilt-content-digest-does-not-match-target")
    return rebuilt
