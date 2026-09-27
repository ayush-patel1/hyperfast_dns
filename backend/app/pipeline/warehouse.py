"""DuckDB-backed warehouse.

Each tenant gets its own DuckDB schema; every table carries `_partition_id` so
loads are idempotent (delete-then-insert of one partition inside a transaction).
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import duckdb

from app.core.types import DUCKDB_TYPES, DataType, from_duckdb_type
from app.pipeline.definition import validate_identifier
from app.registry.models import Schema

STAGING = "staging"
TRANSFORMED = "transformed"


def q(identifier: str) -> str:
    return '"' + validate_identifier(identifier) + '"'


class Warehouse:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        con = duckdb.connect(str(self._path))
        try:
            yield con
        finally:
            con.close()

    # --- run-scoped operations (temp tables live on the run's connection) ---

    @staticmethod
    def stage(con: duckdb.DuckDBPyConnection, schema: Schema, records: list[dict[str, Any]]) -> None:
        """Stage via DuckDB's native JSON reader with the declared types; values that
        do not fit their declared type raise, exactly as a typed upstream load would."""
        cols = list(schema.fields)
        ddl = ", ".join(f"{q(c)} {DUCKDB_TYPES[schema.fields[c].type]}" for c in cols)
        con.execute(f"CREATE OR REPLACE TEMP TABLE {STAGING} ({ddl})")
        if not records:
            return
        columns = "{" + ", ".join(f"'{c}': '{DUCKDB_TYPES[schema.fields[c].type]}'" for c in cols) + "}"
        fd, tmp = tempfile.mkstemp(suffix=".ndjson")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps({c: r.get(c) for c in cols}))
                    fh.write("\n")
            con.execute(
                f"INSERT INTO {STAGING} SELECT * FROM read_json(?, format='newline_delimited', "
                f"columns={columns}, timestampformat='%Y-%m-%dT%H:%M:%S')",
                [tmp],
            )
        finally:
            os.unlink(tmp)

    @staticmethod
    def transform(
        con: duckdb.DuckDBPyConnection, transformations: dict[str, str], source_table: str = STAGING
    ) -> tuple[list[dict[str, Any]], dict[str, DataType]]:
        """Run the pipeline's column expressions. Expressions come from reviewed
        pipeline definitions; AI-proposed ones only ever run in the sandbox."""
        select = ", ".join(f"({expr}) AS {q(col)}" for col, expr in transformations.items())
        con.execute(f"CREATE OR REPLACE TEMP TABLE {TRANSFORMED} AS SELECT {select} FROM {source_table}")
        types = {row[0]: from_duckdb_type(row[1]) for row in con.execute(f"DESCRIBE {TRANSFORMED}").fetchall()}
        cursor = con.execute(f"SELECT * FROM {TRANSFORMED}")
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()], types

    @staticmethod
    def load(
        con: duckdb.DuckDBPyConnection,
        tenant_id: str,
        table: str,
        target_schema: Schema,
        partition_id: str,
        run_id: str,
        row_filter: str | None = None,
    ) -> int:
        cols = list(target_schema.fields)
        ddl = ", ".join(f"{q(c)} {DUCKDB_TYPES[target_schema.fields[c].type]}" for c in cols)
        fq = f"{q(tenant_id)}.{q(table)}"
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {q(tenant_id)}")
        con.execute(
            f"CREATE TABLE IF NOT EXISTS {fq} ({ddl}, _partition_id VARCHAR NOT NULL, "
            f"_run_id VARCHAR NOT NULL, _loaded_at TIMESTAMP NOT NULL)"
        )
        col_list = ", ".join(q(c) for c in cols)
        where = f" WHERE {row_filter}" if row_filter else ""
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(f"DELETE FROM {fq} WHERE _partition_id = ?", [partition_id])
            con.execute(
                f"INSERT INTO {fq} ({col_list}, _partition_id, _run_id, _loaded_at) "
                f"SELECT {col_list}, ?, ?, now()::TIMESTAMP FROM {TRANSFORMED}{where}",
                [partition_id, run_id],
            )
            loaded = con.execute(f"SELECT count(*) FROM {fq} WHERE _partition_id = ?", [partition_id]).fetchone()[0]
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return int(loaded)

    # --- read helpers ---

    def table_exists(self, tenant_id: str, table: str) -> bool:
        with self.connect() as con:
            return con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
                [validate_identifier(tenant_id), validate_identifier(table)],
            ).fetchone()[0] > 0

    def column_values(self, tenant_id: str, table: str, column: str, limit: int = 1000) -> list[Any]:
        if not self.table_exists(tenant_id, table):
            return []
        with self.connect() as con:
            cols = {r[0] for r in con.execute(f"DESCRIBE {q(tenant_id)}.{q(table)}").fetchall()}
            if column not in cols:
                return []
            rows = con.execute(
                f"SELECT {q(column)} FROM {q(tenant_id)}.{q(table)} ORDER BY _loaded_at DESC LIMIT ?", [limit]
            ).fetchall()
        return [r[0] for r in rows]

    def distinct_values(self, tenant_id: str, table: str, column: str) -> set[str]:
        return {str(v) for v in self.column_values(tenant_id, table, column, limit=1_000_000) if v is not None}

    def partition_count(self, tenant_id: str, table: str, partition_id: str) -> int:
        if not self.table_exists(tenant_id, table):
            return 0
        with self.connect() as con:
            return int(con.execute(
                f"SELECT count(*) FROM {q(tenant_id)}.{q(table)} WHERE _partition_id = ?", [partition_id]
            ).fetchone()[0])
