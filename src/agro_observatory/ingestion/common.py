"""Building blocks shared by all raw ingestions: logging, raw tables and Parquet writing."""

import logging
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class InvalidResponseError(ValueError):
    """The API answered, but not with the shape the ingestion expects."""


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def raw_table(
    rows: Sequence[Mapping[str, str | None]],
    columns: Sequence[str],
    source_url: str,
    ingested_at: datetime,
) -> pa.Table:
    """Build a table with every source column as text, plus ingestion metadata columns."""
    data = {name: pa.array([row[name] for row in rows], pa.string()) for name in columns}
    data["_source_url"] = pa.array([source_url] * len(rows), pa.string())
    data["_ingested_at"] = pa.array([ingested_at] * len(rows), pa.timestamp("us", tz="UTC"))
    return pa.table(data)


def write_parquet_atomic(table: pa.Table, path: Path) -> None:
    """Write to a temporary file and rename, so an interrupted run never leaves a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp_path)
    os.replace(tmp_path, path)
