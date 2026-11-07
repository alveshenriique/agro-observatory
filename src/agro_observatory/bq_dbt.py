"""Run dbt against the BigQuery production target, with the storage-quota safety lock.

Usage (from the repository root):
    uv run bq-dbt [--yes] build [--empty] [--select ...] [other dbt options]
    uv run bq-dbt test | docs generate | ls ...   (read-only commands run directly)

For commands that write (run, build, seed, snapshot), it lists the tables the command will
create, estimates their logical size from the same tables on the local Postgres (zero with
--empty, zero for views), shows the estimate next to the quota log, asks for confirmation and
only then runs `dbt ... --target prod` with the variable that the dbt `guard_bigquery_writes`
hook requires. Afterwards it measures the logical size of the tables written and appends it to
the quota log. dbt itself refuses writing commands on BigQuery that do not come through here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import dotenv_values, find_dotenv, load_dotenv

from agro_observatory import bigquery_ops as ops
from agro_observatory.load_raw import conninfo_from_env

DBT_DIR = Path("dbt")
WRITING_COMMANDS = {"run", "build", "seed", "snapshot"}
SELECTION_FLAGS = {"--select", "-s", "--exclude", "--selector", "--models", "-m"}
DATASETS = ("staging", "intermediate", "marts", "seeds")
# BigQuery logical bytes per value for each Postgres type of the local tables.
POSTGRES_SIZES = {
    "numeric": 16,
    "double precision": 8,
    "real": 8,
    "integer": 8,
    "bigint": 8,
    "smallint": 8,
    "boolean": 1,
    "date": 8,
    "timestamp with time zone": 8,
    "timestamp without time zone": 8,
}


def selection_args(args: list[str]) -> list[str]:
    """The node-selection options of a dbt command line (what `dbt ls` understands)."""
    out, i = [], 0
    while i < len(args):
        if args[i] in SELECTION_FLAGS:
            out.append(args[i])
            i += 1
            while i < len(args) and not args[i].startswith("-"):
                out.append(args[i])
                i += 1
        else:
            i += 1
    return out


def dbt_env() -> dict[str, str]:
    env = {**os.environ, **{k: v for k, v in dotenv_values(find_dotenv(usecwd=True)).items() if v}}
    return env


def nodes_to_write(args: list[str]) -> list[dict]:
    """Models and seeds selected by the command, with their materialization and dataset."""
    command = [
        "dbt",
        "--quiet",
        "ls",
        "--target",
        "prod",
        "--resource-type",
        "model",
        "seed",
        "--output",
        "json",
        "--output-keys",
        "name resource_type config",
        *selection_args(args),
    ]
    result = subprocess.run(
        command, cwd=DBT_DIR, env=dbt_env(), capture_output=True, text=True, check=True
    )
    nodes = []
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            node = json.loads(line)
            nodes.append(
                {
                    "name": node["name"],
                    "resource_type": node["resource_type"],
                    "materialized": node["config"].get("materialized"),
                    "schema": node["config"].get("schema"),
                }
            )
    return nodes


def writes_storage(node: dict) -> bool:
    return node["resource_type"] == "seed" or node["materialized"] == "table"


def postgres_logical_bytes(conn: psycopg.Connection, schema: str, table: str) -> int | None:
    """Logical size the local Postgres table would have in BigQuery (None if it is missing)."""
    columns = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    ).fetchall()
    if not columns:
        return None
    parts = []
    for name, data_type in columns:
        column = psycopg.sql.Identifier(name)
        if data_type in ("text", "character varying"):
            parts.append(psycopg.sql.SQL("coalesce(sum(2 + octet_length({})), 0)").format(column))
        else:
            size = psycopg.sql.Literal(POSTGRES_SIZES.get(data_type, 8))
            parts.append(psycopg.sql.SQL("count({}) * {}").format(column, size))
    query = psycopg.sql.SQL("SELECT {} FROM {}").format(
        psycopg.sql.SQL(" + ").join(parts), psycopg.sql.Identifier(schema, table)
    )
    return int(conn.execute(query).fetchone()[0])


def estimate(nodes: list[dict], empty: bool) -> tuple[int, list[str]]:
    lines, total = [], 0
    writers = [n for n in nodes if writes_storage(n)]
    if empty:
        return 0, [f"  {len(writers)} tables and seeds with zero rows (--empty)"]
    with psycopg.connect(conninfo_from_env()) as conn:
        conn.execute("SET statement_timeout = '60s'")
        for node in writers:
            size = postgres_logical_bytes(conn, node["schema"], node["name"])
            if size is None:
                raise SystemExit(f"{node['schema']}.{node['name']} is missing on Postgres")
            total += size
            lines.append(f"  {node['schema']}.{node['name']}: {ops.mib(size)}")
    views = len(nodes) - len(writers)
    lines.append(f"  (+ {views} views, no storage)")
    return total, lines


def measure(client, since: datetime) -> int:
    """Logical bytes of the tables in the dbt datasets modified since `since`."""
    total = 0
    for dataset in DATASETS:
        try:
            tables = list(client.list_tables(f"{client.project}.{dataset}"))
        except Exception:  # noqa: BLE001 - dataset not created by this run
            continue
        for item in tables:
            table = client.get_table(item.reference)
            if table.table_type == "TABLE" and table.modified and table.modified >= since:
                total += table.num_bytes or 0
    return total


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    yes = "--yes" in argv
    argv = [a for a in argv if a != "--yes"]
    if not argv:
        raise SystemExit(__doc__)
    load_dotenv(find_dotenv(usecwd=True))
    command, rest = argv[0], argv[1:]
    dbt_command = ["dbt", command, *rest, "--target", "prod"]
    if command not in WRITING_COMMANDS:
        return subprocess.run(dbt_command, cwd=DBT_DIR, env=dbt_env()).returncode

    empty = "--empty" in rest
    nodes = nodes_to_write(rest)
    size, lines = estimate(nodes, empty)
    project, location = ops.bigquery_settings()
    ops.confirm_write(
        f"dbt {command} --target prod in {project}, {location}:\n"
        + "\n".join(lines)
        + "\n"
        + ops.quota_report(size, ops.read_quota_log()),
        yes,
    )
    started = datetime.now(UTC)
    time.sleep(1)  # table modification times have millisecond resolution
    env = {**dbt_env(), "AGRO_CONFIRM_BIGQUERY_WRITE": "yes"}
    code = subprocess.run(dbt_command, cwd=DBT_DIR, env=env).returncode
    measured = measure(ops.client(), started)
    ops.append_quota_log(
        f"dbt {command}" + (" --empty" if empty else ""),
        " ".join(rest) or "all",
        size,
        measured,
    )
    print(f"measured {ops.mib(measured)} written (exit code {code}); quota log updated")
    return code


if __name__ == "__main__":
    sys.exit(main())
