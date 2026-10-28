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

"""One-statement hybrid candidate retrieval for the embedded seekdb profile.

A ``mode="hybrid"`` search used to dispatch two independent statements - a FULLTEXT scan
over ``pc_memory_entry_heads`` and an HNSW scan over ``pc_memory_vector_entries`` - and
merge their rows on the application side. seekdb returns both candidate lists from a
single statement, so this adapter keeps every product-level guarantee the two-query path
had and pays one round trip instead of two:

* scope, Memory artifact and tag filtering stay in the database and run *before* each
  channel's ``LIMIT``, so a per-channel candidate set is still bounded at the storage
  layer;
* each channel keeps its own ``ORDER BY``/``LIMIT``, which is what makes the native
  operator - not a Python loop - the thing that selects the candidates. The lexical block
  is planned as a ``TEXT RETRIEVAL SCAN`` over the FULLTEXT index and the semantic block
  as a ``VECTOR INDEX`` scan;
* ``UNION ALL`` never deduplicates, so an entry both channels return arrives twice and is
  fused with both channel labels instead of being lost;
* identities are re-stamped from the requested, already validated head exactly like the
  single-channel paths (``memory_channel_hits``), so a projection row that still carries
  an older ``head_revision`` neither drops an active entry nor leaks a stale reference.

The result is the same backend-neutral channel pair the two-query path produced, which
means fusion, admission and reranking downstream are untouched.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pyobvector import VECTOR
from sqlalchemy import Table, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.expression import TextClause

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryCapabilities,
    MemoryProjection,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

_FTS_BLOCK = """
SELECT
    'fts' AS channel,
    f.memory_artifact_id AS memory_artifact_id,
    f.entry_id AS entry_id,
    f.entry_version_id AS entry_version_id,
    v.`text` AS `text`,
    NULL AS distance,
    MATCH (f.searchable_text) AGAINST (:query_text) AS channel_score
FROM pc_memory_entry_heads AS f
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = f.scope_id
 AND v.memory_artifact_id = f.memory_artifact_id
 AND v.entry_version_id = f.entry_version_id
WHERE f.scope_id = :scope_id
  AND f.memory_artifact_id IN :fts_artifact_ids
  AND MATCH (f.searchable_text) AGAINST (:query_text){tag}
ORDER BY MATCH (f.searchable_text) AGAINST (:query_text) DESC,
         f.memory_artifact_id,
         f.entry_id,
         f.entry_version_id
LIMIT :candidate_limit
"""

_VECTOR_BLOCK = """
SELECT
    'vector' AS channel,
    m.memory_artifact_id AS memory_artifact_id,
    m.entry_id AS entry_id,
    m.entry_version_id AS entry_version_id,
    v.`text` AS `text`,
    l2_distance(m.embedding, :query_vector) AS distance,
    NULL AS channel_score
FROM pc_memory_vector_entries AS m
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = m.scope_id
 AND v.memory_artifact_id = m.memory_artifact_id
 AND v.entry_version_id = m.entry_version_id
WHERE m.scope_id = :scope_id
  AND m.memory_artifact_id IN :vec_artifact_ids{tag}
ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
LIMIT :candidate_limit
"""


def hybrid_candidate_statement(*, tagged: bool = False) -> str:
    """One statement carrying both ranked candidate lists, filtered in the database."""

    lexical_tag = "" if not tagged else memory_tag_sql("f", suffix="fts")
    semantic_tag = "" if not tagged else memory_tag_sql("m", suffix="vec")
    lexical = _FTS_BLOCK.replace("{tag}", lexical_tag)
    semantic = _VECTOR_BLOCK.replace("{tag}", semantic_tag)
    return f"({lexical})\nUNION ALL\n({semantic})"


class SeekDBHybridMemoryIndex:
    """Hybrid candidates from one statement while the single-channel paths stay frozen."""

    def __init__(
        self,
        *,
        fts: OceanBaseMemoryFTSIndex,
        vector: OceanBaseMemoryVectorIndex,
    ) -> None:
        self._fts = fts
        self._vector = vector
        self.profile = vector.profile
        # Same capability answer the two independent indexes used to compose into.
        self.capabilities = MemoryCapabilities(
            fts=fts.capabilities.fts,
            vector=vector.capabilities.vector,
            hybrid=fts.capabilities.fts and vector.capabilities.vector,
            tag_filter=fts.capabilities.tag_filter and vector.capabilities.tag_filter,
            embedding_profile=vector.capabilities.embedding_profile,
        )
        self.tables: tuple[Table, ...] = fts.tables + vector.tables
        self._statement = _bind_hybrid_statement(vector.profile.dimension, tagged=False)
        self._tagged_statement = _bind_hybrid_statement(vector.profile.dimension, tagged=True)

    async def initialize(self, connection: AsyncConnection, /) -> None:
        await self._fts.initialize(connection)
        await self._vector.initialize(connection)

    async def replace(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.replace(connection, scope_id, memory_ref, projections)
        await self._vector.replace(connection, scope_id, memory_ref, projections)

    async def delete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        entry_ids: tuple[str, ...],
        /,
    ) -> None:
        await self._fts.delete(connection, scope_id, memory_ref, entry_ids)
        await self._vector.delete(connection, scope_id, memory_ref, entry_ids)

    async def upsert(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memory_ref: ArtifactRef,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> None:
        await self._fts.upsert(connection, scope_id, memory_ref, projections)
        await self._vector.upsert(connection, scope_id, memory_ref, projections)

    async def search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
        /,
    ) -> MemorySearchChannels:
        if request.mode != "hybrid":
            lexical = await self._fts.search(connection, scope_id, request)
            semantic = await self._vector.search(connection, scope_id, request)
            return MemorySearchChannels(fts=lexical.fts, vector=semantic.vector)
        return await self._hybrid_search(connection, scope_id, request)

    async def vector_complete(
        self,
        connection: AsyncConnection,
        scope_id: str,
        memories: tuple[ArtifactRef, ...],
        profile: EmbeddingProfile,
        /,
    ) -> bool:
        return await self._vector.vector_complete(connection, scope_id, memories, profile)

    async def hydrate(
        self,
        connection: AsyncConnection,
        scope_id: str,
        projections: tuple[MemoryProjection, ...],
        /,
    ) -> tuple[MemoryProjection, ...]:
        # The lexical index projects no vectors, so hydrating through it is an identity map.
        hydrated = await self._fts.hydrate(connection, scope_id, projections)
        return await self._vector.hydrate(connection, scope_id, hydrated)

    async def _hybrid_search(
        self,
        connection: AsyncConnection,
        scope_id: str,
        request: MemorySearchRequest,
    ) -> MemorySearchChannels:
        if request.embedding_profile != self.profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        # Reject an incomplete vector projection before the statement runs, exactly as the
        # single-channel vector path does: a missing or stale embedding is a capability
        # answer, not an empty result.
        if not await self._vector.vector_complete(connection, scope_id, request.memories, self.profile):
            raise CapabilityNotSupportedError("vector")
        artifact_ids = tuple(memory.artifact_id for memory in request.memories)
        rows = (
            await connection.execute(
                self._tagged_statement if request.tag_filter is not None else self._statement,
                {
                    "scope_id": scope_id,
                    "fts_artifact_ids": artifact_ids,
                    "vec_artifact_ids": artifact_ids,
                    "query_text": request.analyzed_query,
                    "query_vector": validate_embedding(
                        request.query_vector,
                        dimension=self.profile.dimension,
                    ),
                    "candidate_limit": request.candidate_limit,
                    **memory_tag_parameters(request.tag_filter, suffix="fts"),
                    **memory_tag_parameters(request.tag_filter, suffix="vec"),
                },
            )
        ).mappings().all()
        lexical_rows = [row for row in rows if str(row["channel"]) == "fts"]
        semantic_rows = [row for row in rows if str(row["channel"]) == "vector"]
        # Each block already returned its own ranking; restoring it here keeps the channel
        # contract independent of how the engine interleaves a UNION ALL result.
        lexical_rows.sort(key=_lexical_order)
        semantic_rows.sort(key=_semantic_order)
        return MemorySearchChannels(
            fts=memory_channel_hits(lexical_rows, request.memories),
            vector=memory_channel_hits(semantic_rows, request.memories),
        )


def _lexical_order(row: Mapping[str, Any]) -> tuple[float, str, str, str]:
    return (
        -float(row["channel_score"]),
        str(row["memory_artifact_id"]),
        str(row["entry_id"]),
        str(row["entry_version_id"]),
    )


def _semantic_order(row: Mapping[str, Any]) -> tuple[float, str, str, str]:
    return (
        float(row["distance"]),
        str(row["memory_artifact_id"]),
        str(row["entry_id"]),
        str(row["entry_version_id"]),
    )


def _bind_hybrid_statement(dimension: int, *, tagged: bool) -> TextClause:
    statement = text(hybrid_candidate_statement(tagged=tagged)).bindparams(
        bindparam("fts_artifact_ids", expanding=True),
        bindparam("vec_artifact_ids", expanding=True),
        bindparam("query_vector", type_=VECTOR(dimension)),
    )
    if tagged:
        statement = statement.bindparams(
            bindparam("tag_fts_keys", expanding=True),
            bindparam("tag_fts_hashes", expanding=True),
            bindparam("tag_vec_keys", expanding=True),
            bindparam("tag_vec_hashes", expanding=True),
        )
    return statement
