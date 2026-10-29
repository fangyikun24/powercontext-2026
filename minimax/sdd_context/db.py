"""Engineering-material storage: embedded seekdb or an OceanBase MySQL-mode tenant.

The store keeps one row per *atomic engineering material* — a single spec requirement, a
single code symbol, or a single test function — together with a whitespace-tokenised
``searchable_text`` column that carries a native FULLTEXT index.

Everything is plain SQL over ``pymysql`` so the exact statements the module issues are
visible in the technical record, and so the same code path runs on both backends.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pymysql

from sdd_context.config import Settings
from sdd_context.textutil import searchable_text

TABLE = "sdd_materials"
FTS_INDEX = "ix_sdd_fts"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    material_id     CHAR(40)     NOT NULL,
    project         VARCHAR(128) NOT NULL,
    kind            VARCHAR(16)  NOT NULL,
    path            VARCHAR(512) NOT NULL,
    symbol          VARCHAR(255) NOT NULL DEFAULT '',
    start_line      INT          NOT NULL DEFAULT 0,
    end_line        INT          NOT NULL DEFAULT 0,
    title           VARCHAR(512) NOT NULL DEFAULT '',
    body            LONGTEXT     NOT NULL,
    content_hash    CHAR(64)     NOT NULL,
    updated_at      BIGINT       NOT NULL,
    searchable_text LONGTEXT     NOT NULL,
    PRIMARY KEY (material_id),
    KEY ix_sdd_project_kind (project, kind),
    KEY ix_sdd_path (path(191))
) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""

COLUMNS = (
    "material_id",
    "project",
    "kind",
    "path",
    "symbol",
    "start_line",
    "end_line",
    "title",
    "body",
    "content_hash",
    "searchable_text",
    "updated_at",
)


@dataclass(frozen=True)
class MaterialRow:
    """One atomic engineering material."""

    kind: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    title: str
    body: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()

    def material_id(self, project: str) -> str:
        key = f"{project}\x00{self.kind}\x00{self.path}\x00{self.symbol}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()  # noqa: S324 - identifier, not a secret

    def to_params(self, project: str) -> tuple[Any, ...]:
        return (
            self.material_id(project),
            project,
            self.kind,
            self.path,
            self.symbol,
            self.start_line,
            self.end_line,
            self.title,
            self.body,
            self.content_hash,
            searchable_text(self.kind, self.path, self.symbol, self.title, self.body),
            int(time.time()),
        )


@dataclass(frozen=True)
class SearchHit:
    kind: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    title: str
    body: str
    content_hash: str
    score: float

    @property
    def locator(self) -> str:
        if self.start_line and self.end_line:
            return f"{self.path}:{self.start_line}-{self.end_line}"
        return self.path


class MaterialDatabase:
    """Thin repository over the material table."""

    def __init__(self, connection: pymysql.connections.Connection, *, backend: str) -> None:
        self._connection = connection
        self.backend = backend

    # -- schema ------------------------------------------------------------

    def ensure_schema(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(SCHEMA)
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s",
                (TABLE, FTS_INDEX),
            )
            present = cursor.fetchone()[0]
            if not present:
                cursor.execute(
                    f"CREATE FULLTEXT INDEX {FTS_INDEX} ON {TABLE} (searchable_text) WITH PARSER SPACE"
                )
        self._connection.commit()

    # -- writes ------------------------------------------------------------

    def replace_project(self, project: str, rows: Sequence[MaterialRow]) -> dict[str, int]:
        """Replace every material for ``project`` with ``rows``.

        Re-importing therefore *uses the updated content*: changed specs get new
        ``content_hash`` values and removed materials disappear from the index.
        """
        params = [row.to_params(project) for row in rows]
        material_ids = [p[0] for p in params]
        placeholders = ", ".join(["%s"] * len(COLUMNS))
        upserted = 0
        removed = 0
        with self._connection.cursor() as cursor:
            if material_ids:
                marks = ", ".join(["%s"] * len(material_ids))
                cursor.execute(
                    f"DELETE FROM {TABLE} WHERE project = %s AND material_id NOT IN ({marks})",
                    (project, *material_ids),
                )
                removed = max(cursor.rowcount, 0)
                cursor.executemany(
                    f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({placeholders}) "
                    f"ON DUPLICATE KEY UPDATE "
                    f"project=VALUES(project), kind=VALUES(kind), path=VALUES(path), symbol=VALUES(symbol), "
                    f"start_line=VALUES(start_line), end_line=VALUES(end_line), title=VALUES(title), "
                    f"body=VALUES(body), content_hash=VALUES(content_hash), "
                    f"updated_at=VALUES(updated_at), searchable_text=VALUES(searchable_text)",
                    params,
                )
                upserted = len(params)
            else:
                cursor.execute(f"DELETE FROM {TABLE} WHERE project = %s", (project,))
                removed = max(cursor.rowcount, 0)
        self._connection.commit()
        return {"upserted": upserted, "removed": removed}

    # -- reads -------------------------------------------------------------

    def count(self, project: str) -> dict[str, int]:
        with self._connection.cursor() as cursor:
            cursor.execute(f"SELECT kind, COUNT(*) FROM {TABLE} WHERE project = %s GROUP BY kind", (project,))
            return {str(row[0]): int(row[1]) for row in cursor.fetchall()}

    def search(
        self,
        project: str,
        query: str,
        *,
        kinds: Iterable[str] = ("spec", "code", "test"),
        limit: int = 8,
    ) -> list[SearchHit]:
        terms = searchable_text(query)
        if not terms:
            return []
        kind_list = list(kinds)
        placeholders = ", ".join(["%s"] * len(kind_list))
        sql = (
            f"SELECT kind, path, symbol, start_line, end_line, title, body, content_hash, "
            f"MATCH(searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE) AS score "
            f"FROM {TABLE} "
            f"WHERE project = %s AND kind IN ({placeholders}) "
            f"AND MATCH(searchable_text) AGAINST (%s IN NATURAL LANGUAGE MODE) "
            f"ORDER BY score DESC, path, start_line LIMIT %s"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(sql, (terms, project, *kind_list, terms, limit))
            rows = cursor.fetchall()
        return [
            SearchHit(
                kind=str(row[0]),
                path=str(row[1]),
                symbol=str(row[2]),
                start_line=int(row[3]),
                end_line=int(row[4]),
                title=str(row[5]),
                body=str(row[6]),
                content_hash=str(row[7]),
                score=float(row[8]),
            )
            for row in rows
        ]

    def fetch_by_symbol(self, project: str, symbol: str, *, kinds: Iterable[str] = ("spec", "code", "test")) -> list[SearchHit]:
        kind_list = list(kinds)
        placeholders = ", ".join(["%s"] * len(kind_list))
        with self._connection.cursor() as cursor:
            cursor.execute(
                f"SELECT kind, path, symbol, start_line, end_line, title, body, content_hash "
                f"FROM {TABLE} WHERE project = %s AND symbol = %s AND kind IN ({placeholders}) "
                f"ORDER BY path, start_line",
                (project, symbol, *kind_list),
            )
            rows = cursor.fetchall()
        return [
            SearchHit(
                kind=str(row[0]),
                path=str(row[1]),
                symbol=str(row[2]),
                start_line=int(row[3]),
                end_line=int(row[4]),
                title=str(row[5]),
                body=str(row[6]),
                content_hash=str(row[7]),
                score=1.0,
            )
            for row in rows
        ]

    def close(self) -> None:
        self._connection.close()


# ---------------------------------------------------------------------------
# connection management
# ---------------------------------------------------------------------------


def _parse_oceanbase_url(url: str) -> dict[str, Any]:
    """Parse ``mysql+aoceanbase://user:pass@host:port/db?charset=utf8mb4`` for pymysql."""
    if not url.startswith("mysql+aoceanbase://"):
        raise ValueError("SDDCTX_OCEANBASE_URL must start with mysql+aoceanbase://")
    parts = urlsplit(url[len("mysql+aoceanbase") :])
    if not parts.hostname or not parts.port:
        raise ValueError("SDDCTX_OCEANBASE_URL must include an explicit host and port")
    database = parts.path.lstrip("/")
    if not database:
        raise ValueError("SDDCTX_OCEANBASE_URL must include a database name")
    return {
        "host": parts.hostname,
        "port": parts.port,
        "user": unquote(parts.username or "root"),
        "password": unquote(parts.password or ""),
        "database": database,
        "charset": "utf8mb4",
    }


@contextmanager
def open_materials_database(settings: Settings) -> Iterator[MaterialDatabase]:
    """Open the material store, initialising the seekdb instance or connecting to OceanBase."""
    if settings.materials_backend == "oceanbase":
        if not settings.oceanbase_url:
            raise RuntimeError("SDDCTX_OCEANBASE_URL is required for the oceanbase backend")
        params = _parse_oceanbase_url(settings.oceanbase_url)
        connection = pymysql.connect(
            **params,
            autocommit=False,
            connect_timeout=20,
            read_timeout=120,
            write_timeout=120,
        )
        database = MaterialDatabase(connection, backend="oceanbase")
        try:
            database.ensure_schema()
            yield database
        finally:
            database.close()
        return

    # Embedded seekdb: the engine is started by pylibseekdb and reached over MySQL.
    import pylibseekdb  # imported lazily so the oceanbase path needs no seekdb wheel

    path = settings.materials_seekdb_path
    path.mkdir(parents=True, exist_ok=True)
    instance = _open_seekdb(pylibseekdb, path)
    try:
        connect_kwargs = _seekdb_connect_kwargs(instance)
        connection = pymysql.connect(**connect_kwargs)
    except Exception:
        instance.close()
        raise
    database = MaterialDatabase(connection, backend="seekdb")
    try:
        database.ensure_schema()
        yield database
    finally:
        database.close()
        instance.close()


def _seekdb_connect_kwargs(instance: Any) -> dict[str, Any]:
    """Translate ``connection_options()`` into ``pymysql.connect`` arguments.

    The published wheels do not agree on how the embedded engine is reached: the
    Windows build listens on a loopback TCP port, while the Linux build exposes a
    unix socket inside a per-process temporary directory. Both shapes are accepted
    here so the module runs on either platform.
    """
    options = instance.connection_options() or {}
    kwargs: dict[str, Any] = {
        "user": options.get("user") or "root",
        "password": options.get("password") or "",
        "database": "test",
        "charset": "utf8mb4",
        "autocommit": False,
        "connect_timeout": 20,
        "read_timeout": 120,
        "write_timeout": 120,
    }
    if options.get("port"):
        kwargs["host"] = options.get("host") or "127.0.0.1"
        kwargs["port"] = int(options["port"])
    elif options.get("unix_socket"):
        kwargs["unix_socket"] = options["unix_socket"]
    else:
        raise RuntimeError(
            "unrecognised seekdb connection options: " + ", ".join(sorted(options))
        )
    return kwargs


def _open_seekdb(pylibseekdb: Any, path: Path, *, attempts: int = 3) -> Any:
    """Open the embedded engine, retrying the short-lived startup race on reopen."""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return pylibseekdb.open(str(path))
        except Exception as error:  # noqa: BLE001 - the binding raises a single error type
            last = error
            if attempt == attempts:
                break
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"could not open embedded seekdb at {path}: {last}") from last
