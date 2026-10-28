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

"""Dependency-aware Source lifecycle for Memory and Topic Memory.

A Scope registers its evidence as a small DAG: captured Sources at the roots,
Memory entries and Topic Memory revisions as derived nodes. Withdrawing or
restoring a Source therefore only has to change its own row; every dependent
node is re-derived from the graph, and the native Memory state follows so that
listing, search and Context assembly agree.

Propagation is a reconcile rather than an incremental edit. That makes a
successful event replay free of new Memory revisions and lets an interrupted
propagation finish when the same event is retried.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.source_lifecycle_schema import (
    SOURCE_LIFECYCLE_EVENTS_TABLE,
    SOURCE_LIFECYCLE_NODES_TABLE,
)
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime

NodeFamily = Literal["source", "memory", "topic"]
LifecyclePolicy = Literal["all", "any"]
LifecyclePurpose = Literal["generation", "audit"]

_PURPOSES = frozenset({"generation", "audit"})
_POLICIES = frozenset({"all", "any"})
_FAMILIES = frozenset({"source", "memory", "topic"})
_REFERENCES = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}
_REGISTRATION_REASON = "source lifecycle registration"

_NODES = SOURCE_LIFECYCLE_NODES_TABLE
_EVENTS = SOURCE_LIFECYCLE_EVENTS_TABLE


class SourceLifecycleError(ValueError):
    """A lifecycle request violates the dependency contract."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"source lifecycle: {detail}")
        self.detail = detail


class SourceLifecycleEvent(BaseModel):
    """One explicit availability change for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    revision: int
    sequence: int
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def _require_text(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("revision", "sequence", mode="before")
    @classmethod
    def _require_positive_integer(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("must be a positive integer")
        return value

    @field_validator("available", mode="before")
    @classmethod
    def _require_boolean(cls, value: Any) -> bool:
        if not isinstance(value, bool):
            raise ValueError("must be a bool")
        return value


@dataclass(frozen=True, slots=True)
class _Node:
    node_id: str
    family: str
    reference: str
    parents: tuple[str, ...]
    policy: str
    revision: int
    available: bool


class SourceLifecycleApplication:
    """Resolve one Scope's dependency graph for the calling Runtime."""

    def __init__(self, runtime: BuiltinRuntime, database: AsyncDatabase) -> None:
        self.runtime = runtime
        self.database = database

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycleService:
        return ScopedSourceLifecycleService(self, scope_id)

    async def unavailable_topics(self, scope_id: str, /) -> frozenset[str]:
        """Return Topic artifacts that no longer have enough support.

        Read-only and empty whenever a Scope never registered a dependency, so
        Topic Memory search pays one bounded lookup instead of a join.
        """

        _require_identifier("scope_id", scope_id)
        async with self.database.transaction() as connection:
            references = (
                (
                    await connection.execute(
                        select(_NODES.c.reference).where(
                            _NODES.c.scope_id == scope_id,
                            _NODES.c.family == "topic",
                            _NODES.c.available == 0,
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not references:
            return frozenset()
        return frozenset(_decode_artifact(str(reference)).artifact_id for reference in references)


class ScopedSourceLifecycleService:
    """Register, propagate, and resolve one Scope's evidence dependencies."""

    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        _require_identifier("scope_id", scope_id)
        self._application = application
        self._runtime = application.runtime
        self._database = application.database
        self.scope_id = scope_id

    # ------------------------------------------------------------------ register

    async def register_source(self, node_id: str, source_ref: SourceRef, revision: int = 1) -> None:
        """Bind a node to one captured Source and its lifecycle revision."""

        _require_identifier("node_id", node_id)
        _require_positive_integer("revision", revision)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("registration-reference")
        await self._require_captured_source(source_ref)
        await self._register(
            node_id,
            family="source",
            reference=_encode(source_ref),
            parents=(),
            policy="all",
            revision=revision,
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        parents: Iterable[str],
        policy: str = "all",
    ) -> None:
        """Bind a node to one exact Memory entry and the nodes that support it."""

        _require_identifier("node_id", node_id)
        _require_policy(policy)
        parent_ids = _require_parents(node_id, parents)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("registration-reference")
        await self._require_citation(citation)
        created, available = await self._register(
            node_id,
            family="memory",
            reference=_encode(citation),
            parents=parent_ids,
            policy=policy,
            revision=0,
        )
        if created and not available:
            # A derived node settles at registration: it must never be usable
            # before the event that would have withdrawn the support.
            await self._set_memory_state(frozenset({citation.entry_id}), available=False, reason=_REGISTRATION_REASON)

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        parents: Iterable[str],
        policy: str = "all",
    ) -> None:
        """Bind a node to one exact Topic Memory revision and its supporters."""

        _require_identifier("node_id", node_id)
        _require_policy(policy)
        parent_ids = _require_parents(node_id, parents)
        if not isinstance(artifact_ref, ArtifactRef):
            raise SourceLifecycleError("registration-reference")
        await self._require_artifact(artifact_ref)
        await self._register(
            node_id,
            family="topic",
            reference=_encode(artifact_ref),
            parents=parent_ids,
            policy=policy,
            revision=0,
        )

    # --------------------------------------------------------------------- event

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Record one Source event and propagate the new evidence graph."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event")
        await self._record_event(event)
        return await self._reconcile(event.reason)

    async def _record_event(self, event: SourceLifecycleEvent) -> None:
        async with self._database.transaction() as connection:
            node = await self._load_node(connection, event.node_id)
            if node is None or node.family != "source":
                raise SourceLifecycleError("unknown-source")
            if node.revision != event.revision:
                raise SourceLifecycleError("revision-mismatch")
            last = await connection.scalar(
                select(func.max(_EVENTS.c.sequence)).where(
                    _EVENTS.c.scope_id == self.scope_id,
                    _EVENTS.c.node_id == event.node_id,
                )
            )
            if last is not None:
                if event.sequence < last:
                    raise SourceLifecycleError("sequence-regression")
                if event.sequence == last and not await self._matches_stored_event(connection, event):
                    raise SourceLifecycleError("sequence-conflict")
                if event.sequence == last:
                    # An identical replay still republishes the state it names,
                    # so a retry after an interrupted propagation converges.
                    await self._store_source_availability(connection, event)
                    return
            await connection.execute(
                insert(_EVENTS).values(
                    scope_id=self.scope_id,
                    node_id=event.node_id,
                    sequence=event.sequence,
                    revision=event.revision,
                    available=int(event.available),
                    reason=event.reason,
                )
            )
            await self._store_source_availability(connection, event)

    async def _matches_stored_event(self, connection: AsyncConnection, event: SourceLifecycleEvent) -> bool:
        row = (
            await connection.execute(
                select(_EVENTS.c.revision, _EVENTS.c.available).where(
                    _EVENTS.c.scope_id == self.scope_id,
                    _EVENTS.c.node_id == event.node_id,
                    _EVENTS.c.sequence == event.sequence,
                )
            )
        ).one_or_none()
        if row is None:
            return False
        return int(row[0]) == event.revision and bool(row[1]) == event.available

    async def _store_source_availability(
        self,
        connection: AsyncConnection,
        event: SourceLifecycleEvent,
    ) -> None:
        await connection.execute(
            update(_NODES)
            .where(_NODES.c.scope_id == self.scope_id, _NODES.c.node_id == event.node_id)
            .values(available=int(event.available))
        )

    # ------------------------------------------------------------------- resolve

    async def resolve(self, node_id: str, purpose: str = "generation") -> SourceRef | MemoryCitation | ArtifactRef:
        """Return the node's original reference for generation or audit use."""

        if purpose not in _PURPOSES:
            raise SourceLifecycleError("purpose")
        _require_identifier("node_id", node_id)
        async with self._database.transaction() as connection:
            node = await self._load_node(connection, node_id)
        if node is None:
            raise SourceLifecycleError("unknown-node")
        if purpose == "generation" and not node.available:
            raise SourceLifecycleError("unavailable")
        return _decode(node)

    # ------------------------------------------------------------------- internal

    async def _register(
        self,
        node_id: str,
        *,
        family: str,
        reference: str,
        parents: tuple[str, ...],
        policy: str,
        revision: int,
    ) -> tuple[bool, bool]:
        async with self._database.transaction() as connection:
            existing = await self._load_node(connection, node_id)
            if existing is not None:
                if (
                    existing.family != family
                    or existing.reference != reference
                    or existing.parents != parents
                    or existing.policy != policy
                    or existing.revision != revision
                ):
                    raise SourceLifecycleError("registration-conflict")
                return False, existing.available
            available = True if family == "source" else await self._derive(connection, parents, policy)
            await connection.execute(
                insert(_NODES).values(
                    scope_id=self.scope_id,
                    node_id=node_id,
                    family=family,
                    reference=reference,
                    parents=json.dumps(list(parents)),
                    policy=policy,
                    revision=revision,
                    available=int(available),
                )
            )
            return True, available

    async def _derive(self, connection: AsyncConnection, parents: tuple[str, ...], policy: str) -> bool:
        rows = {node.node_id: node for node in await self._load_nodes(connection)}
        missing = [parent for parent in parents if parent not in rows]
        if missing:
            raise SourceLifecycleError("unknown-parent")
        values = [rows[parent].available for parent in parents]
        return all(values) if policy == "all" else any(values)

    async def _reconcile(self, reason: str) -> list[str]:
        async with self._database.transaction() as connection:
            nodes = await self._load_nodes(connection)
        desired = _propagate(nodes)
        stale = [node for node in nodes if node.available != desired[node.node_id]]
        for target in (False, True):
            selected = [node for node in stale if node.family == "memory" and desired[node.node_id] is target]
            if not selected:
                continue
            entry_ids = frozenset(_decode_citation(node.reference).entry_id for node in selected)
            # Native Memory state first: a failure here leaves the recorded row
            # unchanged, so the retry repeats an operation that is idempotent.
            await self._set_memory_state(entry_ids, available=target, reason=reason)
            await self._store_availability({node.node_id: target for node in selected})
        remaining = {node.node_id: desired[node.node_id] for node in stale if node.family != "memory"}
        if remaining:
            await self._store_availability(remaining)
        return sorted(node_id for node_id, available in desired.items() if available)

    async def _store_availability(self, states: Mapping[str, bool]) -> None:
        async with self._database.transaction() as connection:
            for node_id, available in states.items():
                await connection.execute(
                    update(_NODES)
                    .where(_NODES.c.scope_id == self.scope_id, _NODES.c.node_id == node_id)
                    .values(available=int(available))
                )

    async def _set_memory_state(self, entry_ids: frozenset[str], *, available: bool, reason: str) -> None:
        async with self._runtime._context(self.scope_id) as context:
            async with self._runtime._locked(self.scope_id):
                service = context.artifacts.memory
                memory = await service.head(context.artifacts.memory_artifact_id)
                targeted = tuple(entry for entry in await service.entries(memory) if entry.entry_id in entry_ids)
                if not targeted:
                    return
                # The Memory audit reason is bounded; the lifecycle event itself
                # keeps the caller's full text.
                bounded = reason if len(reason) <= 500 else reason[:500]
                if available:
                    await service.reactivate(memory, entries=targeted, reason=bounded)
                else:
                    await service.forget(memory, entries=targeted, reason=bounded)

    async def _load_nodes(self, connection: AsyncConnection) -> tuple[_Node, ...]:
        rows = (
            await connection.execute(
                select(
                    _NODES.c.node_id,
                    _NODES.c.family,
                    _NODES.c.reference,
                    _NODES.c.parents,
                    _NODES.c.policy,
                    _NODES.c.revision,
                    _NODES.c.available,
                ).where(_NODES.c.scope_id == self.scope_id)
            )
        ).mappings()
        return tuple(_node(row) for row in rows.all())

    async def _load_node(self, connection: AsyncConnection, node_id: str) -> _Node | None:
        row = (
            await connection.execute(
                select(
                    _NODES.c.node_id,
                    _NODES.c.family,
                    _NODES.c.reference,
                    _NODES.c.parents,
                    _NODES.c.policy,
                    _NODES.c.revision,
                    _NODES.c.available,
                ).where(_NODES.c.scope_id == self.scope_id, _NODES.c.node_id == node_id)
            )
        ).mappings()
        found = row.one_or_none()
        return None if found is None else _node(found)

    async def _require_captured_source(self, source_ref: SourceRef) -> None:
        async with self._runtime._context(self.scope_id) as context:
            journal = await context.sources.journal.entries()
        if not any(entry.source_ref == source_ref for entry in journal):
            raise SourceLifecycleError("unknown-source")

    async def _require_citation(self, citation: MemoryCitation) -> None:
        async with self._runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            if citation.memory_ref.artifact_id != context.artifacts.memory_artifact_id:
                raise SourceLifecycleError("unknown-citation")
            try:
                memory = await service.revision(citation.memory_ref)
            except LookupError as error:
                raise SourceLifecycleError("unknown-citation") from error
            if not any(
                item.entry_id == citation.entry_id and item.entry_version_id == citation.entry_version_id
                for item in memory.content.manifest.entries
            ):
                raise SourceLifecycleError("unknown-citation")

    async def _require_artifact(self, artifact_ref: ArtifactRef) -> None:
        from powercontext.builtin.records import BaseValueNotFoundError

        try:
            await self._runtime.records.for_scope(self.scope_id).get_artifact_revision(
                artifact_ref.family,
                artifact_ref.artifact_id,
                artifact_ref.revision,
            )
        except (BaseValueNotFoundError, LookupError, ValueError) as error:
            raise SourceLifecycleError("unknown-artifact") from error


def _propagate(nodes: tuple[_Node, ...]) -> dict[str, bool]:
    """Derive every node's availability from the graph's Source roots."""

    by_id = {node.node_id: node for node in nodes}
    state = {node.node_id: node.available for node in nodes if node.family == "source"}

    def resolve(node_id: str, active_path: set[str]) -> bool:
        known = state.get(node_id)
        if known is not None:
            return known
        node = by_id.get(node_id)
        if node is None:
            raise SourceLifecycleError("unknown-parent")
        if node_id in active_path:
            raise SourceLifecycleError("dependency-cycle")
        active_path.add(node_id)
        values = [resolve(parent, active_path) for parent in node.parents]
        active_path.discard(node_id)
        value = all(values) if node.policy == "all" else any(values)
        state[node_id] = value
        return value

    for node in nodes:
        resolve(node.node_id, set())
    return state


def _node(row: Any) -> _Node:
    family = str(row["family"])
    if family not in _FAMILIES:
        raise SourceLifecycleError("node-family")
    return _Node(
        node_id=str(row["node_id"]),
        family=family,
        reference=str(row["reference"]),
        parents=tuple(str(parent) for parent in json.loads(str(row["parents"]))),
        policy=str(row["policy"]),
        revision=int(row["revision"]),
        available=bool(row["available"]),
    )


def _encode(reference: SourceRef | MemoryCitation | ArtifactRef) -> str:
    return json.dumps(reference.model_dump(mode="json"), sort_keys=True)


def _decode(node: _Node) -> SourceRef | MemoryCitation | ArtifactRef:
    return _REFERENCES[node.family].model_validate(json.loads(node.reference))


def _decode_citation(reference: str) -> MemoryCitation:
    return MemoryCitation.model_validate(json.loads(reference))


def _decode_artifact(reference: str) -> ArtifactRef:
    return ArtifactRef.model_validate(json.loads(reference))


def _require_identifier(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError(f"{label}-invalid")
    return value


def _require_positive_integer(label: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SourceLifecycleError(f"{label}-invalid")
    return value


def _require_policy(policy: Any) -> str:
    if policy not in _POLICIES:
        raise SourceLifecycleError("policy")
    return policy


def _require_parents(node_id: str, parents: Iterable[str]) -> tuple[str, ...]:
    if isinstance(parents, str) or not isinstance(parents, Iterable):
        raise SourceLifecycleError("parents")
    parent_ids = tuple(parents)
    if not parent_ids:
        raise SourceLifecycleError("parents-required")
    for parent in parent_ids:
        _require_identifier("parent", parent)
        if parent == node_id:
            raise SourceLifecycleError("self-dependency")
    if len(set(parent_ids)) != len(parent_ids):
        raise SourceLifecycleError("duplicate-parent")
    return parent_ids


__all__ = [
    "LifecyclePolicy",
    "LifecyclePurpose",
    "NodeFamily",
    "ScopedSourceLifecycleService",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
