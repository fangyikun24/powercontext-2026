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

"""Pi session branch history as immutable, incrementally captured Sources.

A Pi v3 session archive is a JSONL graph: every record declares an ``id`` and a
``parentId``, so one selected leaf node pins a single branch. Every visible event
on that branch becomes an independent :data:`CAPTURED` Source whose identity is
``pi:{session_id}:{event_id}``. Control nodes keep the graph connected but never
produce textual evidence, and compaction/branch summaries never erase the
evidence captured before them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunStatus, ConnectorRunSession
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_HISTORY_VERSION = "1"


class PiSessionInput(BaseModel):
    """A complete offline Pi v3 JSONL archive and an optional selected leaf."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event on the selected Pi branch, preserving its raw record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


class PiEventSource(Source):
    """A captured Pi event whose identity is the session id and event id."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, Any]


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable Source identity ``pi:{session_id}:{event_id}``.

    Both components are percent-encoded with no safe characters so event ids
    containing separators cannot collide. The identity is bounded to the shared
    source id length limit.
    """

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a non-empty string")
    identifier = f"pi:{quote(session_id, safe='')}:{quote(event_id, safe='')}"
    if len(identifier) > MAX_SOURCE_ID_LENGTH:
        raise ValueError("pi event source_id exceeds the maximum allowed length")
    return identifier


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse the complete ancestor chain of one selected leaf into visible events.

    The archive is validated atomically: invalid encoding, JSON, duplicated ids,
    missing parents, cycles, or a missing leaf all raise :class:`ValueError`
    without returning partial results. Control nodes are traversed to keep the
    graph connected but are not emitted.
    """

    try:
        text = value.content.decode("utf-8-sig")
    except UnicodeError as error:
        raise ValueError("session content must be valid UTF-8 text") from error

    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("session content is not valid JSONL") from error
        if not isinstance(record, dict):
            raise ValueError("each session record must be a JSON object")
        records.append(record)

    if not records:
        raise ValueError("session has no header record")

    header = records[0]
    if header.get("type") != "session":
        raise ValueError("the first record must be a session header")
    version = header.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version != 3:
        raise ValueError("session version must be 3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session id must be a non-empty string")

    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("each session record must declare a non-empty string id")
        if event_id in nodes:
            raise ValueError("session record ids must be unique")
        if "parentId" not in record:
            raise ValueError("each session record must declare parentId")
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or not parent_id:
                raise ValueError("parentId must be null or a non-empty string")
            if parent_id not in nodes:
                raise ValueError("parentId must reference an earlier session record")
        nodes[event_id] = record
        order.append(event_id)

    if not nodes:
        raise ValueError("session has no events")

    leaf_id = value.leaf_id
    if leaf_id is None:
        leaf_id = order[-1]
    elif leaf_id not in nodes:
        raise ValueError("leaf id does not exist in the session")

    chain: list[str] = []
    cursor: str | None = leaf_id
    visited: set[str] = set()
    while cursor is not None:
        if cursor in visited or cursor not in nodes:
            raise ValueError("session parent chain is not a valid tree")
        visited.add(cursor)
        chain.append(cursor)
        cursor = nodes[cursor].get("parentId")
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = nodes[event_id]
        rendered = _render_event(record)
        if rendered is None:
            continue
        role, body = rendered
        if not body.strip():
            continue
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=event_id,
                parent_id=record.get("parentId"),
                event_type=record.get("type"),
                role=role,
                content=f"{role}: {body}",
                record=record,
            )
        )
    return tuple(events)


def _render_event(record: dict[str, Any]) -> tuple[str, str] | None:
    """Render one record into ``(role, body)`` or ``None`` for control events."""

    event_type = record.get("type")
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str) or not role:
            return None
        if role == "toolResult":
            tool_name = _as_text(message.get("toolName")) or "unknown"
            call_id = _as_text(message.get("toolCallId"))
            return role, f"[tool_result {tool_name} {call_id}] {_text_of(message.get('content'))}"
        if role == "bashExecution":
            command = _as_text(message.get("command"))
            output = _as_text(message.get("output"))
            return role, f"$ {command}\n{output}"
        return role, _message_body(message.get("content"))
    if event_type in ("compaction", "branch_summary"):
        summary = _as_text(record.get("summary"))
        return event_type, summary
    if event_type == "custom_message":
        return "custom", _text_of(record.get("content"))
    return None


def _message_body(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif block_type == "toolCall":
                name = _as_text(block.get("name")) or "unknown"
                call_id = _as_text(block.get("id"))
                arguments = block.get("arguments", {})
                parts.append(f"[tool_call {name} {call_id}] {_compact_json(arguments)}")
        return "\n".join(parts)
    return ""


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return "null"


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _record_fingerprint(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_imported_events(checkpoint: Any) -> dict[str, str]:
    if checkpoint is None:
        return {}
    if not isinstance(checkpoint, dict):
        raise ValueError("pi session checkpoint must be an object")
    version = checkpoint.get("version")
    events = checkpoint.get("events")
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise ValueError("pi session checkpoint must be version 1")
    if not isinstance(events, dict):
        raise ValueError("pi session checkpoint must contain an event map")
    imported: dict[str, str] = {}
    for event_id, fingerprint in events.items():
        if not isinstance(event_id, str) or not isinstance(fingerprint, str):
            raise ValueError("pi session checkpoint entries must be strings")
        imported[event_id] = fingerprint
    return imported


class PiEventSourceAdapter:
    """Resolve and read one adapter-native Pi event."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        identity = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=identity,
            source_id=identity,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Expose a captured Pi event as standard text evidence."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.source_id,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PiEventSourceAdapter(),
    version=PI_HISTORY_VERSION,
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Import only the newly visible events of the selected Pi branch."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_HISTORY_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self._path = Path(path)
        self._leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        content = self._path.read_bytes()
        events = parse_pi_session(PiSessionInput(content=content, leaf_id=self._leaf_id))

        imported = _load_imported_events(session.checkpoint)
        for event in events:
            fingerprint = imported.get(event.event_id)
            if fingerprint is not None and fingerprint != _record_fingerprint(event.record):
                raise ValueError(f"imported event {event.event_id!r} was rewritten")

        merged = dict(imported)
        for event in events:
            if event.event_id in imported:
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            merged[event.event_id] = _record_fingerprint(event.record)
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint={"version": 1, "events": merged},
        )


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
