"""Export the window indicators computed on Postgres to the derived raw source.

`int_climate__window_indicators` is the only model that reads the daily climate (~94 million
rows), which stays on the local Postgres. This command writes its result to
data/raw/climate/window_indicators.parquet, with Arrow types that reproduce the model's
Postgres types (integer, bigint, real, double precision, numeric, text), so the derived source
loaded by `load-raw` (Postgres or BigQuery) yields exactly the model's columns. `numeric`
becomes decimal(38, 9), BigQuery's NUMERIC; the model rounds coverage to 4 decimals, so nothing
is lost. Run it after a full `dbt build` on Postgres. Usage:
    uv run export-window-indicators [--out data/raw/climate/window_indicators.parquet]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pyarrow as pa
from dotenv import find_dotenv, load_dotenv

from atlas_da_lavoura.ingestion.common import configure_logging, write_parquet_atomic
from atlas_da_lavoura.load_raw import conninfo_from_env

logger = logging.getLogger(__name__)

MODEL = ("intermediate", "int_climate__window_indicators")
SOURCE_URL = "dbt model intermediate.int_climate__window_indicators (local Postgres)"
DEFAULT_OUT = Path("data/raw/climate/window_indicators.parquet")
NUMERIC_TYPE = pa.decimal128(38, 9)
NUMERIC_QUANTUM = Decimal("1e-9")

# Postgres type OIDs -> Arrow types.
ARROW_TYPES = {
    23: pa.int32(),  # integer
    20: pa.int64(),  # bigint
    700: pa.float32(),  # real
    701: pa.float64(),  # double precision
    1700: NUMERIC_TYPE,  # numeric
    25: pa.string(),  # text
    1043: pa.string(),  # varchar
}


def arrow_array(values: list, arrow_type: pa.DataType) -> pa.Array:
    if arrow_type == NUMERIC_TYPE:
        values = [None if v is None else Decimal(v).quantize(NUMERIC_QUANTUM) for v in values]
    return pa.array(values, type=arrow_type)


def to_arrow(columns: list[tuple[str, int]], rows: list[tuple], exported_at: datetime) -> pa.Table:
    """Rows from Postgres as an Arrow table, plus the raw metadata columns."""
    unknown = [(name, oid) for name, oid in columns if oid not in ARROW_TYPES]
    if unknown:
        raise TypeError(f"unsupported Postgres types: {unknown}")
    data = {
        name: arrow_array([row[i] for row in rows], ARROW_TYPES[oid])
        for i, (name, oid) in enumerate(columns)
    }
    data["_source_url"] = pa.array([SOURCE_URL] * len(rows), pa.string())
    data["_ingested_at"] = pa.array([exported_at] * len(rows), pa.timestamp("us", tz="UTC"))
    return pa.table(data)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="export-window-indicators", description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True))
    query = psycopg.sql.SQL(
        "SELECT * FROM {} ORDER BY municipality_id, crop, window_name, harvest_year"
    ).format(psycopg.sql.Identifier(*MODEL))
    with psycopg.connect(conninfo_from_env()) as conn, conn.cursor() as cur:
        cur.execute(query)
        columns = [(d.name, d.type_code) for d in cur.description]
        rows = cur.fetchall()
    table = to_arrow(columns, rows, datetime.now(UTC))
    write_parquet_atomic(table, args.out)
    logger.info("%s.%s: %d rows written to %s", *MODEL, table.num_rows, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
