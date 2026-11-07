"""Shared helpers for writing to BigQuery under the sandbox's lifetime storage quota.

The BigQuery sandbox grants 10 GiB of storage for its whole life, not refunded when data is
deleted, so every load and every table rebuild uses quota for good. Every command that writes
to BigQuery (`load-raw --target bigquery`, `bq-dbt build`) therefore:
1. estimates the logical bytes it will write (BigQuery's own sizing rules);
2. shows the estimate next to what the quota log says was already used;
3. writes only after an explicit confirmation (interactive "yes", or --yes);
4. measures the logical size of what it wrote and appends it to the quota log
   (docs/bigquery_quota_log.csv, versioned, summarised in docs/DECISOES.md).
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc

LIFETIME_QUOTA_BYTES = 10 * 1024**3
QUOTA_LOG = Path(os.environ.get("BIGQUERY_QUOTA_LOG", "docs/bigquery_quota_log.csv"))
QUOTA_LOG_FIELDS = ["date_utc", "operation", "detail", "estimated_bytes", "measured_bytes"]
MIB = 1024**2

# Logical bytes per value in BigQuery (the sizing used for storage pricing and quotas).
_FIXED_SIZE = {"int": 8, "float": 8, "date": 8, "timestamp": 8, "bool": 1, "decimal": 16}


def logical_bytes(table: pa.Table) -> int:
    """Logical size of an Arrow table once loaded into BigQuery.

    STRING: 2 bytes + UTF-8 length; INT64, FLOAT64, DATE, TIMESTAMP: 8; NUMERIC: 16; BOOL: 1.
    Null values take no space.
    """
    total = 0
    for column in table.columns:
        non_null = len(column) - column.null_count
        kind = arrow_kind(column.type)
        if kind == "string":
            total += 2 * non_null + (pc.sum(pc.binary_length(column)).as_py() or 0)
        else:
            total += _FIXED_SIZE[kind] * non_null
    return total


def arrow_kind(arrow_type: pa.DataType) -> str:
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_integer(arrow_type):
        return "int"
    if pa.types.is_floating(arrow_type):
        return "float"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_timestamp(arrow_type):
        return "timestamp"
    if pa.types.is_boolean(arrow_type):
        return "bool"
    if pa.types.is_decimal(arrow_type):
        return "decimal"
    raise TypeError(f"unsupported column type for BigQuery: {arrow_type}")


@dataclass(frozen=True)
class QuotaStatus:
    used_bytes: int
    entries: int

    @property
    def remaining_bytes(self) -> int:
        return LIFETIME_QUOTA_BYTES - self.used_bytes


def read_quota_log(path: Path = QUOTA_LOG) -> QuotaStatus:
    if not path.exists():
        return QuotaStatus(0, 0)
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return QuotaStatus(sum(int(r["measured_bytes"] or 0) for r in rows), len(rows))


def append_quota_log(
    operation: str, detail: str, estimated: int, measured: int, path: Path = QUOTA_LOG
) -> None:
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=QUOTA_LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "date_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "operation": operation,
                "detail": detail,
                "estimated_bytes": estimated,
                "measured_bytes": measured,
            }
        )


def mib(n: int) -> str:
    return f"{n / MIB:,.1f} MiB"


def quota_report(estimate: int, status: QuotaStatus) -> str:
    after = status.used_bytes + estimate
    return (
        f"Estimated write: {mib(estimate)}. Sandbox lifetime quota: {mib(LIFETIME_QUOTA_BYTES)}; "
        f"used so far (quota log, {status.entries} entries): {mib(status.used_bytes)}; "
        f"after this operation: {mib(after)} ({100 * after / LIFETIME_QUOTA_BYTES:.1f}%), "
        f"remaining {mib(LIFETIME_QUOTA_BYTES - after)}."
    )


class NotConfirmedError(SystemExit):
    pass


def confirm_write(summary: str, yes: bool, stdin=sys.stdin) -> None:
    """Require an explicit confirmation before writing to BigQuery."""
    print(summary, flush=True)
    if yes:
        print("Confirmed by --yes.", flush=True)
        return
    if not stdin.isatty():
        raise NotConfirmedError("Not confirmed: rerun with --yes to write to BigQuery.")
    answer = input("Type 'yes' to write to BigQuery: ").strip().lower()
    if answer != "yes":
        raise NotConfirmedError("Not confirmed: nothing was written.")


def bigquery_settings() -> tuple[str, str]:
    project = os.environ.get("BIGQUERY_PROJECT", "")
    location = os.environ.get("BIGQUERY_LOCATION", "southamerica-east1")
    if not project:
        raise SystemExit("BIGQUERY_PROJECT is not set (see .env.example).")
    return project, location


def client():
    """BigQuery client with the machine's Application Default Credentials (no key files)."""
    from google.cloud import bigquery

    project, location = bigquery_settings()
    return bigquery.Client(project=project, location=location)
