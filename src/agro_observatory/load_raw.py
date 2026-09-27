"""Load the raw Parquet files into the `raw` schema in PostgreSQL.

One table per source, mirroring the Parquet columns (source columns as text, no keys,
indexes or type casts: that is dbt's job), plus `_source_file` and `_loaded_at`.
Each file is loaded in its own transaction with COPY:
- partitioned sources (PAM) delete the rows of that partition, then copy the file;
- snapshot sources (localities, IPCA) truncate the table, then copy the file.
Files whose `_ingested_at` already matches what is in the table are skipped (unless --force),
so a rerun only reloads what the ingestion actually changed. Rows whose `_source_file` no
longer exists on disk (orphans) are reported, and deleted only with --prune.
"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import find_dotenv, load_dotenv
from psycopg import sql

from agro_observatory.ingestion.common import configure_logging

logger = logging.getLogger(__name__)

RAW_SCHEMA = "raw"
DEFAULT_DATA_DIR = Path("data/raw")
LOAD_COLUMNS = (("_source_file", "text"), ("_loaded_at", "timestamptz"))


@dataclass(frozen=True)
class Source:
    table: str
    pattern: str  # glob relative to the data dir
    partitioned: bool


SOURCES = {
    "pam": Source("pam", "pam/crop=*/year=*/data.parquet", partitioned=True),
    "localities": Source("localities", "localities/municipalities.parquet", partitioned=False),
    "ipca": Source("ipca", "ipca/ipca.parquet", partitioned=False),
}


class SchemaMismatchError(RuntimeError):
    pass


def find_files(source: Source, data_dir: Path) -> list[Path]:
    files = sorted(data_dir.glob(source.pattern))
    if not files:
        raise FileNotFoundError(f"no files for {source.table}: {data_dir / source.pattern}")
    if not source.partitioned and len(files) > 1:
        raise ValueError(f"snapshot source {source.table} must have a single file: {files}")
    return files


def postgres_columns(schema: pa.Schema) -> list[tuple[str, str]]:
    """Map Parquet columns to Postgres types: text for source data, timestamptz for timestamps."""
    columns = []
    for field in schema:
        if pa.types.is_string(field.type):
            columns.append((field.name, "text"))
        elif pa.types.is_timestamp(field.type) and field.type.tz is not None:
            columns.append((field.name, "timestamptz"))
        else:
            raise SchemaMismatchError(f"unsupported raw column type: {field.name} {field.type}")
    return [*columns, *LOAD_COLUMNS]


def create_table_sql(table: str, columns: list[tuple[str, str]]) -> sql.Composed:
    definitions = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(pg_type)) for name, pg_type in columns
    )
    return sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
        sql.Identifier(RAW_SCHEMA, table), definitions
    )


def copy_sql(table: str, column_names: list[str]) -> sql.Composed:
    return sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(RAW_SCHEMA, table),
        sql.SQL(", ").join(sql.Identifier(name) for name in column_names),
    )


def clear_sql(source: Source) -> sql.Composed:
    target = sql.Identifier(RAW_SCHEMA, source.table)
    if source.partitioned:
        return sql.SQL("DELETE FROM {} WHERE _source_file = %s").format(target)
    return sql.SQL("TRUNCATE {}").format(target)


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


def ensure_table(cur: psycopg.Cursor, table: str, columns: list[tuple[str, str]]) -> None:
    cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(RAW_SCHEMA)))
    cur.execute(create_table_sql(table, columns))
    cur.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (RAW_SCHEMA, table),
    )
    existing = [(name, "timestamptz" if "timestamp" in t else t) for name, t in cur.fetchall()]
    if existing != columns:
        raise SchemaMismatchError(
            f"{RAW_SCHEMA}.{table} does not match the Parquet schema; drop it to recreate.\n"
            f"table:   {existing}\nparquet: {columns}"
        )


def file_version(path: Path) -> datetime:
    """A file's version is its ingestion timestamp (constant within a file)."""
    return pq.read_table(path, columns=["_ingested_at"]).column(0)[0].as_py()


def needs_load(
    source_file: str, version: datetime, loaded: dict[str, datetime], force: bool
) -> bool:
    return force or loaded.get(source_file) != version


def loaded_versions(conn: psycopg.Connection, table: str) -> dict[str, datetime]:
    """Ingestion timestamp of each file already in the table, in a single scan."""
    if conn.execute("SELECT to_regclass(%s)", (f"{RAW_SCHEMA}.{table}",)).fetchone()[0] is None:
        return {}
    query = sql.SQL("SELECT _source_file, max(_ingested_at) FROM {} GROUP BY 1").format(
        sql.Identifier(RAW_SCHEMA, table)
    )
    return dict(conn.execute(query).fetchall())


def load_file(conn: psycopg.Connection, source: Source, path: Path, source_file: str) -> int:
    table = pq.read_table(path)
    columns = postgres_columns(table.schema)

    with conn.transaction(), conn.cursor() as cur:
        ensure_table(cur, source.table, columns)
        cur.execute(clear_sql(source), (source_file,) if source.partitioned else None)
        with cur.copy(copy_sql(source.table, [name for name, _ in columns])) as copy:
            for row in iter_rows(table, source_file, datetime.now(UTC)):
                copy.write_row(row)
    return table.num_rows


def handle_orphans(conn: psycopg.Connection, table: str, orphans: list[str], prune: bool) -> None:
    if not orphans:
        return
    if not prune:
        logger.warning(
            "%s.%s has rows from %d file(s) no longer on disk (use --prune to delete): %s",
            RAW_SCHEMA,
            table,
            len(orphans),
            orphans,
        )
        return
    with conn.transaction():
        deleted = conn.execute(prune_sql(table), (orphans,)).rowcount
    logger.warning(
        "%s.%s: pruned %d orphan rows from %d file(s): %s",
        RAW_SCHEMA,
        table,
        deleted,
        len(orphans),
        orphans,
    )


def load_source(
    conn: psycopg.Connection, source: Source, data_dir: Path, force: bool, prune: bool
) -> None:
    files = find_files(source, data_dir)
    loaded = loaded_versions(conn, source.table)
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
    handle_orphans(conn, source.table, find_orphans(loaded, disk_files), prune)


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
