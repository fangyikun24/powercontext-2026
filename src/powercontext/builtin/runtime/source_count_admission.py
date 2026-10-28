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

"""Count-based admission of Family invocations from persisted Journal identity.

The count is the number of Source Journal rows a Scope accumulated after its
Family's last committed Source cursor. Persisted identity is the only input:
replayed captures keep their original position, a trusted receipt upgrade
rewrites one payload in place, and a lineage-only server Source still owns one
row even though it can never become generation evidence.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.errors import InvalidRepositoryArgumentError
from powercontext.builtin.persistence.tables import (
    ARTIFACT_PROCESSING_INTENTS_TABLE,
    SOURCE_JOURNAL_HEADS_TABLE,
)


async def scopes_reaching_source_count(
    connection: AsyncConnection,
    binding_name: str,
    threshold: int,
    /,
    *,
    limit: int,
) -> tuple[str, ...]:
    """Return the Scopes whose pending Journal identities reach ``threshold``.

    Only Scopes with unreconciled domain progress are inspected, so ordinary
    quiescent traffic costs one indexed read. Journal positions are allocated
    contiguously per Scope and are never reclaimed, which makes the distance
    between the committed cursor and the current head the exact number of
    entries still waiting for that Family.
    """

    if type(threshold) is not int or isinstance(threshold, bool) or threshold < 1:
        raise InvalidRepositoryArgumentError("threshold", "must be a positive integer")
    if type(limit) is not int or isinstance(limit, bool) or limit < 1:
        raise InvalidRepositoryArgumentError("limit", "must be a positive integer")
    intents = ARTIFACT_PROCESSING_INTENTS_TABLE
    heads = SOURCE_JOURNAL_HEADS_TABLE
    statement = (
        select(intents.c.scope_id, func.coalesce(heads.c.position, 0))
        .select_from(intents)
        .join(heads, heads.c.scope_id == intents.c.scope_id, isouter=True)
        .where(
            intents.c.binding_name == binding_name,
            intents.c.dirty_generation > intents.c.clean_generation,
        )
        .order_by(intents.c.pending_sequence)
        .limit(limit)
    )
    candidates = tuple(
        (str(scope_id), int(head)) for scope_id, head in (await connection.execute(statement)).all()
    )
    if not candidates:
        return ()
    cursors = await SourceCursorRepository().load_many(
        connection, tuple(scope_id for scope_id, _ in candidates), binding_name
    )
    return tuple(
        scope_id
        for scope_id, head in candidates
        if head - (0 if scope_id not in cursors else cursors[scope_id].cursor.sequence) >= threshold
    )


__all__ = ["scopes_reaching_source_count"]
