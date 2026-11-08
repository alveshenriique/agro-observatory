"""Export the website's data files from the serving views (Postgres or BigQuery).

Usage (from the repository root):
    uv run export-serving --target postgres|bigquery [--out dist/site-data]
        [--data-version AAAA.MM.DD] [--mesh data/raw/ibge_mesh/municipalities.geojson]
        [--run-results dbt/target/run_results.json] [--sample] [--force]
    uv run export-serving --target bigquery --dry-run

Reads each serving view once (never one query per municipality), builds the files
(build.py), the simplified mesh (mesh.py), validates every file against its JSON Schema and
the validity rules (contract.py), reconciles the files with the marts (reconcile.py) and
writes them to <out>/<data version>/ with manifest.json. Nothing is written if a check
fails. Exporting only reads: on BigQuery it uses query quota (1 TiB a month), not storage;
--dry-run shows the bytes each query would process without running it.
--sample marks the CI sample (7 municipalities, partial mesh): it is never packaged.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from agro_observatory.ingestion.common import configure_logging
from agro_observatory.serving import contract, mesh, reconcile
from agro_observatory.serving.build import SCHEMA_VERSIONS, VIEWS, Bundle, Context
from agro_observatory.serving.warehouse import MONTHLY_QUERY_QUOTA_BYTES, Warehouse, connect

logger = logging.getLogger(__name__)

DEFAULT_OUT = Path("dist/site-data")
DEFAULT_RUN_RESULTS = Path("dbt/target/run_results.json")


def view_queries(wh: Warehouse) -> dict[str, str]:
    return {view: f"select * from {wh.relation('serve', view)}" for view in VIEWS}


def dry_run(wh: Warehouse) -> int:
    queries = {**view_queries(wh), **{f"check: {k}": v for k, v in reconcile.queries(wh).items()}}
    total = 0
    print(f"{'query':52s} {'bytes processed':>18s}")
    for name, sql in queries.items():
        size = wh.dry_run(sql) or 0
        total += size
        print(f"{name:52s} {size:>18,}")
    share = 100 * total / MONTHLY_QUERY_QUOTA_BYTES
    mib = total / 2**20
    print(f"{'total':52s} {total:>18,}  ({mib:.1f} MiB, {share:.3f}% of the 1 TiB monthly quota)")
    return total


def dbt_tests_summary(path: Path, warehouse: str) -> dict | None:
    """Test results of the last dbt run, if it was a full build/test on the same warehouse."""
    if not path.exists():
        logger.warning("%s not found: method.json gets no dbt test summary", path)
        return None
    data = json.loads(path.read_text())
    args = data.get("args", {})
    target = args.get("target")
    same_warehouse = (target == "prod") == (warehouse == "bigquery")
    selected = args.get("select") or args.get("exclude") or args.get("resource_types")
    if args.get("which") not in ("build", "test") or selected or not same_warehouse:
        logger.warning(
            "%s is from `dbt %s` (target %s, selection %s): not a full build/test of %s; "
            "method.json gets no dbt test summary",
            path, args.get("which"), target, selected, warehouse,
        )  # fmt: skip
        return None
    tests = [r for r in data["results"] if r["unique_id"].startswith("test.")]
    count = {
        s: sum(r["status"] == s for r in tests)
        for s in ("pass", "warn", "error", "fail", "skipped")
    }
    return {
        "dbt_version": data["metadata"]["dbt_version"],
        "invocation_id": data["metadata"]["invocation_id"],
        "generated_at": data["metadata"]["generated_at"],
        "target": target,
        "command": args.get("which"),
        "total": len(tests),
        **count,
        "warnings": sorted(r["unique_id"].split(".")[2] for r in tests if r["status"] == "warn"),
    }


def git_state() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def serialize(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def export(args: argparse.Namespace) -> int:
    wh = connect(args.target)
    try:
        if args.dry_run:
            if args.target != "bigquery":
                raise SystemExit(
                    "--dry-run only applies to BigQuery (Postgres has no query billing)"
                )
            dry_run(wh)
            return 0
        query_bytes = dry_run(wh) if args.target == "bigquery" else None
        now = datetime.now(UTC).replace(microsecond=0)
        version = args.data_version or ("sample" if args.sample else now.strftime("%Y.%m.%d"))
        out = args.out / version
        if out.exists() and not args.force:
            raise SystemExit(f"{out} exists; pass --force to replace it")

        logger.info("reading %d serving views from %s", len(VIEWS), args.target)
        tables = {name: wh.query(sql) for name, sql in view_queries(wh).items()}
        ctx = Context(version, now.isoformat().replace("+00:00", "Z"), args.target, args.sample)
        bundle = Bundle(tables, ctx)
        files = bundle.data_files(dbt_tests_summary(args.run_results, args.target))

        logger.info("building the mesh from %s", args.mesh)
        geo, mesh_stats = mesh.build(args.mesh, bundle.state_abbreviations())
        mesh_stats.pop("municipality_ids")
        for path, topology in geo.items():
            files[path] = {
                "type": topology["type"],
                "meta": ctx.meta("topology", ["ibge_mesh"]),
                **topology,
            }

        logger.info("validating %d files against the contract", len(files))
        errors = contract.check_all(files)
        if errors:
            for e in errors[:30]:
                logger.error("contract: %s", e)
            raise SystemExit(f"{len(errors)} contract error(s); nothing written")
        logger.info("reconciling the files with the marts")
        checks = reconcile.reconcile(wh, files, args.sample)
        for c in checks:
            (logger.info if c["status"] == "ok" else logger.error)(
                "check %s: %s (%s)", c["status"], c["name"], c["detail"]
            )
        if any(c["status"] == "fail" for c in checks):
            raise SystemExit("reconciliation failed; nothing written")
    finally:
        wh.close()

    tmp = args.out / f".{version}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    entries = []
    for path in sorted(files):
        data = serialize(files[path])
        target = tmp / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append(
            {
                "path": path,
                "schema": files[path]["meta"]["schema"],
                "schema_version": files[path]["meta"]["schema_version"],
                "bytes": len(data),
                "gzip_bytes": len(gzip.compress(data, 9, mtime=0)),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "meta": ctx.meta(
            "manifest", sorted({s for f in files.values() for s in f["meta"]["sources"]})
        ),
        "warehouse": args.target,
        "sample": args.sample,
        "git": git_state(),
        "mesh": mesh_stats,
        "query_bytes": query_bytes,
        "files": entries,
        "checks": checks,
    }
    errors = contract.schema_errors(manifest)
    if errors:
        raise SystemExit(f"manifest does not match its schema: {errors}")
    (tmp / "manifest.json").write_bytes(serialize(manifest))
    if out.exists():
        shutil.rmtree(out)
    tmp.rename(out)

    total = sum(e["bytes"] for e in entries)
    total_gz = sum(e["gzip_bytes"] for e in entries)
    logger.info(
        "%s: %d files, %.1f MiB (%.1f MiB with gzip), schema versions %s",
        out, len(entries) + 1, total / 2**20, total_gz / 2**20, SCHEMA_VERSIONS,
    )  # fmt: skip
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="export-serving", description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", choices=("postgres", "bigquery"), required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--data-version", help="default: today's date (UTC), AAAA.MM.DD")
    parser.add_argument("--mesh", type=Path, default=mesh.DEFAULT_MESH)
    parser.add_argument("--run-results", type=Path, default=DEFAULT_RUN_RESULTS)
    parser.add_argument(
        "--sample", action="store_true", help="CI sample: partial mesh, never packaged"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="BigQuery: show the bytes each query would process"
    )
    parser.add_argument("--force", action="store_true", help="replace an existing version folder")
    args = parser.parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    return export(args)


if __name__ == "__main__":
    sys.exit(main())
