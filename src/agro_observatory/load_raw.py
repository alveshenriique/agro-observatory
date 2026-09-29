"""Load the raw Parquet files into the `raw` schema in PostgreSQL.

One table per source, mirroring the Parquet columns (source columns as text, no keys,
indexes or type casts: that is dbt's job), plus `_source_file` and `_loaded_at`.
Each file is loaded in its own transaction with COPY, according to the source kind:
- rows_by_file (PAM): delete the rows of that file, then copy it;
- snapshot (localities, IPCA, climate cell mapping): truncate the table, then copy the file;
- year_partitioned (daily climate, ~94M rows): a natively partitioned table by year; each
  file is one year and replaces its partition with TRUNCATE. Its columns are typed (derived
  data, see README), its metadata columns are kept once per file in `raw._load_manifest`
  instead of on every row, and it is copied as CSV for speed.
Files whose `_ingested_at` already matches what is loaded are skipped (unless --force),
so a rerun only reloads what the ingestion actually changed. Data from files no longer on
disk (orphans) is reported, and deleted only with --prune.
"""

import argparse
import io
import logging
import os
import re
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from dotenv import find_dotenv, load_dotenv
from psycopg import sql

from agro_observatory.ingestion.common import configure_logging

logger = logging.getLogger(__name__)

RAW_SCHEMA = "raw"
DEFAULT_DATA_DIR = Path("data/raw")
LOAD_COLUMNS = (("_source_file", "text"), ("_loaded_at", "timestamptz"))


MANIFEST_TABLE = "_load_manifest"


class Kind(Enum):
    ROWS_BY_FILE = "rows_by_file"
    SNAPSHOT = "snapshot"
    YEAR_PARTITIONED = "year_partitioned"


@dataclass(frozen=True)
class Source:
    table: str
    pattern: str  # glob relative to the data dir
    kind: Kind
    typed: bool = False  # derived sources keep numeric/date types instead of text
    partition_column: str | None = None  # for YEAR_PARTITIONED: a date column


SOURCES = {
    "pam": Source("pam", "pam/crop=*/year=*/data.parquet", Kind.ROWS_BY_FILE),
    "localities": Source("localities", "localities/municipalities.parquet", Kind.SNAPSHOT),
    "ipca": Source("ipca", "ipca/ipca.parquet", Kind.SNAPSHOT),
    "climate_cells": Source(
        "brdwgd_municipality_cells",
        "climate/brdwgd_municipality_cells.parquet",
        Kind.SNAPSHOT,
        typed=True,
    ),
    "climate_daily": Source(
        "brdwgd_municipality_daily",
        "climate/brdwgd_daily/year=*/data.parquet",
        Kind.YEAR_PARTITIONED,
        typed=True,
        partition_column="date",
    ),
}

TYPED_POSTGRES_TYPES = {
    pa.int32(): "integer",
    pa.int64(): "bigint",
    pa.float32(): "real",
    pa.float64(): "double precision",
    pa.date32(): "date",
}


class SchemaMismatchError(RuntimeError):
    pass


def find_files(source: Source, data_dir: Path) -> list[Path]:
    files = sorted(data_dir.glob(source.pattern))
    if not files:
        raise FileNotFoundError(f"no files for {source.table}: {data_dir / source.pattern}")
    if source.kind is Kind.SNAPSHOT and len(files) > 1:
        raise ValueError(f"snapshot source {source.table} must have a single file: {files}")
    return files


def postgres_columns(schema: pa.Schema, source: Source) -> list[tuple[str, str]]:
    """Map Parquet columns to Postgres types.

    Text for source data and timestamptz for timestamps; typed sources also keep integers,
    floats and dates. Year-partitioned sources drop the per-row metadata columns (`_*`),
    which go to the load manifest instead.
    """
    columns = []
    for field in schema:
        if source.kind is Kind.YEAR_PARTITIONED and field.name.startswith("_"):
            continue
        if pa.types.is_string(field.type):
            columns.append((field.name, "text"))
        elif pa.types.is_timestamp(field.type) and field.type.tz is not None:
            columns.append((field.name, "timestamptz"))
        elif source.typed and field.type in TYPED_POSTGRES_TYPES:
            columns.append((field.name, TYPED_POSTGRES_TYPES[field.type]))
        else:
            raise SchemaMismatchError(f"unsupported raw column type: {field.name} {field.type}")
    if source.kind is Kind.YEAR_PARTITIONED:
        return columns
    return [*columns, *LOAD_COLUMNS]


def create_table_sql(
    table: str, columns: list[tuple[str, str]], partition_column: str | None = None
) -> sql.Composed:
    definitions = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(pg_type)) for name, pg_type in columns
    )
    statement = sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
        sql.Identifier(RAW_SCHEMA, table), definitions
    )
    if partition_column:
        statement += sql.SQL(" PARTITION BY RANGE ({})").format(sql.Identifier(partition_column))
    return statement


def partition_table(table: str, year: int) -> str:
    return f"{table}_{year}"


def create_year_partition_sql(table: str, year: int) -> sql.Composed:
    return sql.SQL(
        "CREATE TABLE IF NOT EXISTS {} PARTITION OF {} FOR VALUES FROM ({}) TO ({})"
    ).format(
        sql.Identifier(RAW_SCHEMA, partition_table(table, year)),
        sql.Identifier(RAW_SCHEMA, table),
        sql.Literal(f"{year}-01-01"),
        sql.Literal(f"{year + 1}-01-01"),
    )


def year_from_file(source_file: str) -> int:
    match = re.search(r"year=(\d{4})", source_file)
    if not match:
        raise ValueError(f"no year=YYYY in {source_file}")
    return int(match.group(1))


def copy_sql(table: str, column_names: list[str], csv: bool = False) -> sql.Composed:
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(RAW_SCHEMA, table),
        sql.SQL(", ").join(sql.Identifier(name) for name in column_names),
    )
    if csv:
        statement += sql.SQL(" WITH (FORMAT csv)")
    return statement


def clear_sql(source: Source) -> sql.Composed:
    target = sql.Identifier(RAW_SCHEMA, source.table)
    if source.kind is Kind.ROWS_BY_FILE:
        return sql.SQL("DELETE FROM {} WHERE _source_file = %s").format(target)
    if source.kind is Kind.SNAPSHOT:
        return sql.SQL("TRUNCATE {}").format(target)
    raise ValueError(f"{source.kind} replaces a partition, see truncate_partition_sql")


def truncate_partition_sql(table: str, year: int) -> sql.Composed:
    return sql.SQL("TRUNCATE {}").format(sql.Identifier(RAW_SCHEMA, partition_table(table, year)))


def drop_partition_sql(table: str, year: int) -> sql.Composed:
    return sql.SQL("DROP TABLE IF EXISTS {}").format(
        sql.Identifier(RAW_SCHEMA, partition_table(table, year))
    )


def create_manifest_sql() -> sql.Composed:
    return sql.SQL(
        "CREATE TABLE IF NOT EXISTS {} (table_name text, source_file text, "
        "ingested_at timestamptz, loaded_at timestamptz, row_count bigint, "
        "PRIMARY KEY (table_name, source_file))"
    ).format(sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE))


def upsert_manifest_sql() -> sql.Composed:
    return sql.SQL(
        "INSERT INTO {} VALUES (%s, %s, %s, %s, %s) ON CONFLICT (table_name, source_file) "
        "DO UPDATE SET ingested_at = excluded.ingested_at, loaded_at = excluded.loaded_at, "
        "row_count = excluded.row_count"
    ).format(sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE))


def prune_sql(table: str) -> sql.Composed:
    return sql.SQL("DELETE FROM {} WHERE _source_file = ANY(%s)").format(
        sql.Identifier(RAW_SCHEMA, table)
    )


def find_orphans(loaded_files: Iterable[str], disk_files: Iterable[str]) -> list[str]:
    """Files present in the table but no longer on disk."""
    return sorted(set(loaded_files) - set(disk_files))


def iter_rows(table: pa.Table, source_file: str, loaded_at: datetime) -> Iterator[tuple[Any, ...]]:
    for batch in table.to_batches():
        columns = [column.to_pylist() for column in batch.columns]
        for row in zip(*columns, strict=True):
            yield (*row, source_file, loaded_at)


def ensure_table(cur: psycopg.Cursor, source: Source, columns: list[tuple[str, str]]) -> None:
    cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(RAW_SCHEMA)))
    cur.execute(create_table_sql(source.table, columns, source.partition_column))
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (RAW_SCHEMA, source.table),
    )
    existing = [(name, "timestamptz" if "timestamp" in t else t) for name, t in cur.fetchall()]
    if existing != columns:
        raise SchemaMismatchError(
            f"{RAW_SCHEMA}.{source.table} does not match the Parquet schema; drop it to recreate."
            f"\ntable:   {existing}\nparquet: {columns}"
        )


def csv_bytes(table: pa.Table) -> bytes:
    """Rows as CSV without header; nulls become empty fields, which COPY reads as NULL."""
    buffer = io.BytesIO()
    pacsv.write_csv(table, buffer, pacsv.WriteOptions(include_header=False))
    return buffer.getvalue()


def file_version(path: Path) -> datetime:
    """A file's version is its ingestion timestamp (constant within a file)."""
    return pq.read_table(path, columns=["_ingested_at"]).column(0)[0].as_py()


def needs_load(
    source_file: str, version: datetime, loaded: dict[str, datetime], force: bool
) -> bool:
    return force or loaded.get(source_file) != version


def loaded_versions(conn: psycopg.Connection, source: Source) -> dict[str, datetime]:
    """Ingestion timestamp of each file already loaded."""
    if source.kind is Kind.YEAR_PARTITIONED:
        table, query = (
            MANIFEST_TABLE,
            sql.SQL("SELECT source_file, ingested_at FROM {} WHERE table_name = %s").format(
                sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE)
            ),
        )
        params = (source.table,)
    else:
        table, query = (
            source.table,
            sql.SQL("SELECT _source_file, max(_ingested_at) FROM {} GROUP BY 1").format(
                sql.Identifier(RAW_SCHEMA, source.table)
            ),
        )
        params = None
    if conn.execute("SELECT to_regclass(%s)", (f"{RAW_SCHEMA}.{table}",)).fetchone()[0] is None:
        return {}
    return dict(conn.execute(query, params).fetchall())


def load_file(conn: psycopg.Connection, source: Source, path: Path, source_file: str) -> int:
    table = pq.read_table(path)
    columns = postgres_columns(table.schema, source)
    column_names = [name for name, _ in columns]

    with conn.transaction(), conn.cursor() as cur:
        ensure_table(cur, source, columns)
        if source.kind is Kind.YEAR_PARTITIONED:
            year = year_from_file(source_file)
            cur.execute(create_manifest_sql())
            cur.execute(create_year_partition_sql(source.table, year))
            cur.execute(truncate_partition_sql(source.table, year))
            target = partition_table(source.table, year)
            with cur.copy(copy_sql(target, column_names, csv=True)) as copy:
                copy.write(csv_bytes(table.select(column_names)))
            cur.execute(
                upsert_manifest_sql(),
                (source.table, source_file, file_version(path), datetime.now(UTC), table.num_rows),
            )
        else:
            cur.execute(
                clear_sql(source), (source_file,) if source.kind is Kind.ROWS_BY_FILE else None
            )
            with cur.copy(copy_sql(source.table, column_names)) as copy:
                for row in iter_rows(table, source_file, datetime.now(UTC)):
                    copy.write_row(row)
    return table.num_rows


def handle_orphans(
    conn: psycopg.Connection, source: Source, orphans: list[str], prune: bool
) -> None:
    if not orphans:
        return
    if not prune:
        logger.warning(
            "%s.%s has data from %d file(s) no longer on disk (use --prune to delete): %s",
            RAW_SCHEMA,
            source.table,
            len(orphans),
            orphans,
        )
        return
    with conn.transaction():
        if source.kind is Kind.YEAR_PARTITIONED:
            for source_file in orphans:
                conn.execute(drop_partition_sql(source.table, year_from_file(source_file)))
            conn.execute(
                sql.SQL("DELETE FROM {} WHERE table_name = %s AND source_file = ANY(%s)").format(
                    sql.Identifier(RAW_SCHEMA, MANIFEST_TABLE)
                ),
                (source.table, orphans),
            )
            action = "dropped the partitions of"
        else:
            deleted = conn.execute(prune_sql(source.table), (orphans,)).rowcount
            action = f"pruned {deleted} orphan rows from"
    logger.warning(
        "%s.%s: %s %d file(s): %s", RAW_SCHEMA, source.table, action, len(orphans), orphans
    )


def load_source(
    conn: psycopg.Connection, source: Source, data_dir: Path, force: bool, prune: bool
) -> None:
    files = find_files(source, data_dir)
    loaded = loaded_versions(conn, source)
    started, rows, skipped = time.monotonic(), 0, 0
    disk_files = []

    for i, path in enumerate(files, start=1):
        source_file = path.relative_to(data_dir).as_posix()
        disk_files.append(source_file)
        if not needs_load(source_file, file_version(path), loaded, force):
            skipped += 1
            continue
        count = load_file(conn, source, path, source_file)
        rows += count
        logger.info("[%d/%d] %s: %d rows", i, len(files), source_file, count)

    logger.info(
        "%s.%s: %d file(s) loaded (%d rows), %d unchanged skipped, in %.1fs",
        RAW_SCHEMA,
        source.table,
        len(files) - skipped,
        rows,
        skipped,
        time.monotonic() - started,
    )
    handle_orphans(conn, source, find_orphans(loaded, disk_files), prune)


def conninfo_from_env() -> str:
    return psycopg.conninfo.make_conninfo(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="load-raw", description="Load raw Parquet files into the Postgres raw schema."
    )
    parser.add_argument(
        "--sources", nargs="+", choices=list(SOURCES), default=list(SOURCES), help="default: all"
    )
    parser.add_argument(
        "--force", action="store_true", help="reload files even if they are unchanged"
    )
    parser.add_argument(
        "--prune", action="store_true", help="delete rows whose source file is no longer on disk"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True))
    with psycopg.connect(conninfo_from_env(), autocommit=True) as conn:
        for name in args.sources:
            load_source(conn, SOURCES[name], args.data_dir, args.force, args.prune)
    return 0


if __name__ == "__main__":
    sys.exit(main())
