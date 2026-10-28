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

"""Relational storage for the explicit Source lifecycle dependency graph."""

from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.builtin.persistence.schema import create_tables
from powercontext.builtin.persistence.tables import identity_string

LIFECYCLE_METADATA = MetaData()

MAX_LIFECYCLE_IDENTITY_LENGTH = 128

SOURCE_LIFECYCLE_NODES_TABLE = Table(
    "pc_source_lifecycle_nodes",
    LIFECYCLE_METADATA,
    Column("scope_id", identity_string(MAX_LIFECYCLE_IDENTITY_LENGTH), primary_key=True),
    Column("node_id", identity_string(MAX_LIFECYCLE_IDENTITY_LENGTH), primary_key=True),
    Column("family", String(16), nullable=False),
    Column("reference", Text(), nullable=False),
    Column("parents", Text(), nullable=False),
    Column("policy", String(8), nullable=False),
    Column("revision", Integer(), nullable=False),
    Column("available", Integer(), nullable=False),
)

SOURCE_LIFECYCLE_EVENTS_TABLE = Table(
    "pc_source_lifecycle_events",
    LIFECYCLE_METADATA,
    Column("scope_id", identity_string(MAX_LIFECYCLE_IDENTITY_LENGTH), primary_key=True),
    Column("node_id", identity_string(MAX_LIFECYCLE_IDENTITY_LENGTH), primary_key=True),
    Column("sequence", Integer(), primary_key=True),
    Column("revision", Integer(), nullable=False),
    Column("available", Integer(), nullable=False),
    Column("reason", Text(), nullable=False),
)


async def ensure_source_lifecycle_schema(connection: AsyncConnection, /) -> None:
    """Create the dependency and event tables when the deployment lacks them."""

    await create_tables(
        connection,
        (SOURCE_LIFECYCLE_NODES_TABLE, SOURCE_LIFECYCLE_EVENTS_TABLE),
    )


__all__ = [
    "SOURCE_LIFECYCLE_EVENTS_TABLE",
    "SOURCE_LIFECYCLE_NODES_TABLE",
    "ensure_source_lifecycle_schema",
]
