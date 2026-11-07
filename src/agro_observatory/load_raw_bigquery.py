"""BigQuery backend of `load-raw`: one load job per table, replacing it entirely.

The sandbox has no DML, so the Postgres strategy (delete a file's rows, then copy it) does not
apply. Each source becomes one Arrow table (all its Parquet files concatenated) loaded with a
single load job and WRITE_TRUNCATE: the table is replaced atomically, and a rerun never
duplicates data. Compared with Postgres:
- `_source_url` is the same for every row of a file, so it is kept once per file in
  `raw._load_manifest` instead of on every row (39% of the PAM's size); `_source_file` is not
  needed either, because whole tables are replaced, never single files. The columns dbt reads
  (source columns, `_ingested_at`, `_loaded_at`) are the same as on Postgres.
- Column names with a hyphen get `_`, as the `source_column` dbt macro expects.
- The daily climate is not loaded (lean architecture); the window indicators computed on
  Postgres come instead, from the derived source exported by `export-window-indicators`.
A table is reloaded only when one of its files changed (`_ingested_at` differs from the
manifest) or the table is missing (sandbox tables expire after 60 days), unless --force.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from agro_observatory import bigquery_ops as ops
from agro_observatory.load_raw import RAW_SCHEMA, SOURCES, Source, file_version, find_files

logger = logging.getLogger(__name__)

BIGQUERY_SOURCES = ("pam", "localities", "ipca", "climate_cells", "climate_window_indicators")
MANIFEST_TABLE = "_load_manifest"
MANIFEST_SCHEMA = pa.schema(
    [
        ("table_name", pa.string()),
        ("source_file", pa.string()),
        ("source_url", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="UTC")),
        ("loaded_at", pa.timestamp("us", tz="UTC")),
        ("row_count", pa.int64()),
    ]
)
_BIGQUERY_TYPES = {
    "string": "STRING",
    "int": "INT64",
    "float": "FLOAT64",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "bool": "BOOL",
    "decimal": "NUMERIC",
}


def bigquery_column_name(name: str) -> str:
    """BigQuery column names cannot contain hyphens (same rule as the source_column macro)."""
    return name.replace("-", "_")


@dataclass
class PreparedTable:
    source: Source
    table: pa.Table
    manifest: list[dict]

    @property
    def name(self) -> str:
        return self.source.table


def prepare_table(source: Source, files: list[Path], data_dir: Path, loaded_at: datetime):
    """All files of a source as one Arrow table, plus one manifest row per file."""
    parts, manifest = [], []
    for path in files:
        table = pq.read_table(path)
        source_url = None
        if "_source_url" in table.column_names:
            source_url = table.column("_source_url")[0].as_py() if table.num_rows else None
            table = table.drop_columns(["_source_url"])
        manifest.append(
            {
                "table_name": source.table,
                "source_file": path.relative_to(data_dir).as_posix(),
                "source_url": source_url,
                "ingested_at": file_version(path),
                "loaded_at": loaded_at,
                "row_count": table.num_rows,
            }
        )
        parts.append(table)
    table = pa.concat_tables(parts)
    table = table.append_column(
        "_loaded_at", pa.array([loaded_at] * table.num_rows, pa.timestamp("us", tz="UTC"))
    )
    table = table.rename_columns([bigquery_column_name(n) for n in table.column_names])
    return PreparedTable(source, table, manifest)


def bigquery_schema(schema: pa.Schema):
    from google.cloud import bigquery

    return [
        bigquery.SchemaField(field.name, _BIGQUERY_TYPES[ops.arrow_kind(field.type)])
        for field in schema
    ]


def needs_reload(prepared: PreparedTable, loaded: dict[str, datetime], exists: bool) -> bool:
    """Reload when the table is missing or any file differs from what the manifest records."""
    if not exists:
        return True
    on_disk = {row["source_file"]: row["ingested_at"] for row in prepared.manifest}
    return on_disk != loaded


def merge_manifest(existing: list[dict], new_rows: list[dict], reloaded: set[str]) -> pa.Table:
    kept = [row for row in existing if row["table_name"] not in reloaded]
    return pa.Table.from_pylist(kept + new_rows, schema=MANIFEST_SCHEMA)


def load_table(client, table_id: str, table: pa.Table) -> None:
    from google.cloud import bigquery

    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=bigquery_schema(table.schema),
    )
    client.load_table_from_file(buffer, table_id, job_config=config).result()


def ensure_dataset(client, dataset: str) -> None:
    from google.cloud import bigquery

    dataset_id = f"{client.project}.{dataset}"
    ds = bigquery.Dataset(dataset_id)
    ds.location = client.location
    created = client.create_dataset(ds, exists_ok=True)
    if created.location.lower() != client.location.lower():
        raise SystemExit(f"dataset {dataset_id} is in {created.location}, not {client.location}")


def table_exists(client, table_id: str) -> bool:
    from google.api_core.exceptions import NotFound

    try:
        client.get_table(table_id)
        return True
    except NotFound:
        return False


def read_manifest(client) -> list[dict]:
    table_id = f"{client.project}.{RAW_SCHEMA}.{MANIFEST_TABLE}"
    if not table_exists(client, table_id):
        return []
    return [dict(row) for row in client.list_rows(table_id)]


def run(sources: list[str], data_dir: Path, force: bool, empty: bool, yes: bool) -> int:
    unsupported = sorted(set(sources) - set(BIGQUERY_SOURCES))
    if unsupported:
        raise SystemExit(
            f"not loaded into BigQuery (lean architecture): {unsupported}; "
            f"BigQuery sources: {list(BIGQUERY_SOURCES)}"
        )
    client = ops.client()
    loaded_at = datetime.now(UTC)
    manifest = read_manifest(client)
    loaded = {}
    for row in manifest:
        loaded.setdefault(row["table_name"], {})[row["source_file"]] = row["ingested_at"]

    to_load: list[PreparedTable] = []
    for name in sources:
        source = SOURCES[name]
        prepared = prepare_table(source, find_files(source, data_dir), data_dir, loaded_at)
        table_id = f"{client.project}.{RAW_SCHEMA}.{source.table}"
        if empty:
            prepared.table = prepared.table.slice(0, 0)
        elif not force and not needs_reload(
            prepared, loaded.get(source.table, {}), table_exists(client, table_id)
        ):
            logger.info("%s.%s: unchanged, skipped", RAW_SCHEMA, source.table)
            continue
        to_load.append(prepared)

    if not to_load:
        logger.info("nothing to load")
        return 0
    lines = [
        f"  {RAW_SCHEMA}.{p.name}: {p.table.num_rows:,} rows, {ops.mib(ops.logical_bytes(p.table))}"
        for p in to_load
    ]
    estimate = sum(ops.logical_bytes(p.table) for p in to_load)
    mode = "empty tables (schema only)" if empty else "full replacement"
    ops.confirm_write(
        f"load-raw --target bigquery ({mode}) into {client.project}, {client.location}:\n"
        + "\n".join(lines)
        + "\n"
        + ops.quota_report(estimate, ops.read_quota_log()),
        yes,
    )

    ensure_dataset(client, RAW_SCHEMA)
    measured = 0
    for p in to_load:
        table_id = f"{client.project}.{RAW_SCHEMA}.{p.name}"
        load_table(client, table_id, p.table)
        size = client.get_table(table_id).num_bytes or 0
        measured += size
        logger.info("%s: %d rows loaded, %s", table_id, p.table.num_rows, ops.mib(size))
    if not empty:
        reloaded = {p.name for p in to_load}
        new_rows = [row for p in to_load for row in p.manifest]
        manifest_id = f"{client.project}.{RAW_SCHEMA}.{MANIFEST_TABLE}"
        load_table(client, manifest_id, merge_manifest(manifest, new_rows, reloaded))
        measured += client.get_table(manifest_id).num_bytes or 0
    ops.append_quota_log(
        "load-raw" + (" --empty" if empty else ""),
        " ".join(p.name for p in to_load),
        estimate,
        measured,
    )
    logger.info("measured %s written; quota log updated", ops.mib(measured))
    return 0
