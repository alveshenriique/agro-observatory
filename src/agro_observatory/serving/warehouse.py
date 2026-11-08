"""Read-only access to the serving views on Postgres or BigQuery, with the same queries.

Values come back as Python types the JSON writer accepts: int, str, bool, None, or Decimal
for NUMERIC (both warehouses return the rounded columns of the serving views as decimals).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import psycopg

from agro_observatory import bigquery_ops as ops
from agro_observatory.load_raw import conninfo_from_env

logger = logging.getLogger(__name__)

MONTHLY_QUERY_QUOTA_BYTES = 1024**4  # BigQuery sandbox and free tier: 1 TiB processed a month


@dataclass
class Table:
    columns: list[str]
    rows: list[tuple]

    def records(self) -> list[dict]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]


class Warehouse(Protocol):
    name: str

    def relation(self, schema: str, table: str) -> str: ...

    def query(self, sql: str) -> Table: ...

    def dry_run(self, sql: str) -> int | None: ...

    def close(self) -> None: ...


class PostgresWarehouse:
    name = "postgres"

    def __init__(self) -> None:
        self.conn = psycopg.connect(conninfo_from_env())
        self.conn.execute("SET statement_timeout = '300s'")

    def relation(self, schema: str, table: str) -> str:
        return f'"{schema}"."{table}"'

    def query(self, sql: str) -> Table:
        cur = self.conn.execute(sql)
        return Table([d.name for d in cur.description], cur.fetchall())

    def dry_run(self, sql: str) -> int | None:
        return None  # nothing is billed on Postgres

    def close(self) -> None:
        self.conn.close()


class BigQueryWarehouse:
    name = "bigquery"

    def __init__(self) -> None:
        from google.cloud import bigquery

        self._bigquery = bigquery
        self.client = ops.client()

    def relation(self, schema: str, table: str) -> str:
        return f"`{self.client.project}.{schema}.{table}`"

    def query(self, sql: str) -> Table:
        result = self.client.query(sql).result(page_size=100_000)
        columns = [field.name for field in result.schema]
        return Table(columns, [tuple(row.values()) for row in result])

    def dry_run(self, sql: str) -> int | None:
        config = self._bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        return int(self.client.query(sql, job_config=config).total_bytes_processed or 0)

    def close(self) -> None:
        self.client.close()


def connect(target: str) -> Warehouse:
    if target == "postgres":
        return PostgresWarehouse()
    if target == "bigquery":
        return BigQueryWarehouse()
    raise ValueError(f"unknown target {target!r}")
